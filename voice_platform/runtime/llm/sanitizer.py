"""StreamSanitizer — buffered sanitizer for streaming LLM output.

Strips internal instruction markers, unresolved templates, markdown formatting,
and spoken blocklist phrases from LLM output. Handles patterns that are split
across chunk boundaries by buffering a prefix window.

Moved from voice_platform/flow/nodes.py to fix architecture violation V-2
(agents layer was importing from flow layer).
"""

import re


# Patterns that should never appear in caller-facing LLM output
_INTERNAL_PATTERNS = [
    # Match [INSTRUCTION ...] when closed, or [INSTRUCTION ... up to a newline/end
    # when unclosed, so a leaked marker never reaches the caller.
    re.compile(r"\[INSTRUCTION\b[^\]]*(?:\]|\n|$)"),
    re.compile(r"\[FLOW CONTEXT\b[^\]]*\]"),
    re.compile(r"\[END FLOW CONTEXT\]"),
    re.compile(r"\[RE-ASK\b[^\]]*\]"),
    re.compile(r"\[BACKGROUND\b[^\]]*\]"),
    re.compile(r"\[QUESTIONS\b[^\]]*\]"),
    re.compile(r"\[KNOWLEDGE BASE\b[^\]]*\]"),
    re.compile(r"\[CONTEXT:[^\]]*\]"),
    re.compile(r"\[TOOL INSTRUCTIONS\]"),
    re.compile(r"\[AGENT HANDBOOK\]"),
    re.compile(r"\[Previous conversation summary:[^\]]*\]"),
    re.compile(r"\[NOTE:[^\]]*\]"),
    re.compile(r"\{\{[^}]+\}\}"),
    # Tokenizer EOS / control markers leaked by some models
    re.compile(r"<\|[a-zA-Z0-9_]+\|>"),
    re.compile(r"<｜[a-zA-Z0-9_▁]+｜>"),
    re.compile(r"</?s>", re.IGNORECASE),
]


# Instructional phrases that should never be spoken to the caller. These are
# stripped from node prompts before question extraction, and also scrubbed from
# LLM output by _sanitize_token.
_SPOKEN_BLOCKLIST = [
    # Prompt author imperative clauses
    re.compile(r"\bIf they give it,?\s*confirm it back to them\.?", re.IGNORECASE),
    re.compile(r"\bIf they don't,?\s*ask for it\.?", re.IGNORECASE),
    re.compile(r"\bIf they give it,?\s*confirm it back\.?", re.IGNORECASE),
    re.compile(r"\bAsk for (?:their|the|his|her) (?:phone number|email(?: address)?|name)\b", re.IGNORECASE),
    re.compile(r"\bAsk (?:the caller|them|him|her) for\b", re.IGNORECASE),
    re.compile(r"\bConfirm it back\b", re.IGNORECASE),
    # Meta-coaching leaked from system/node prompts (call 107)
    # e.g. 'If they sound like they're in pain… don't — ask them: "What's going on?"'
    re.compile(
        r"\bIf they\b[^.?!]{0,220}?(?:don'?t|do not)\s*[—\-–,]?\s*ask them\b[^.?!]*[.?!]?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bIf they sound like\b[^.?!]*[.?!]?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdon'?t\s*[—\-–]\s*ask them\b[^.?!]*[.?!]?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bask them:\s*[\"'][^\"']*[\"']",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:classify|mark)\s+(?:it|them|this)\s+as\s+(?:an?\s+)?emergency\b[^.?!]*[.?!]?",
        re.IGNORECASE,
    ),
    # Extraction directives
    re.compile(r"\bextract all .*?variables?\b", re.IGNORECASE),
    re.compile(r"\bvariables? to extract\b", re.IGNORECASE),
    re.compile(r"\bmark \w+ as\s+['\"]?\w+['\"]?\b", re.IGNORECASE),
]


def _is_coaching_sentence(sentence: str) -> bool:
    """Return True if a prompt sentence is author coaching, not a caller-facing ask."""
    s = (sentence or "").strip()
    if not s:
        return True
    if re.match(
        r"(?i)^(?:if they|if the caller|when they|when the caller)\b",
        s,
    ):
        return True
    if re.search(
        r"(?i)\b(?:don'?t\s*[—\-–]\s*ask|ask them:|classify it as|"
        r"mark \w+ as|only if the situation|immediately)\b",
        s,
    ):
        return True
    return False

# Markdown patterns that TTS engines read literally as symbols
_MARKDOWN_PATTERNS = [
    re.compile(r"\*\*(.+?)\*\*"),       # **bold** → bold
    re.compile(r"__(.+?)__"),           # __bold__ → bold
    re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)"),  # *italic* → italic
    re.compile(r"(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)"),      # _italic_ → italic
    re.compile(r"^#{1,6}\s+", re.MULTILINE),  # # Heading → Heading
    re.compile(r"^---+\s*$", re.MULTILINE),   # --- (horizontal rule) → remove
    re.compile(r"^\*\s+", re.MULTILINE),      # * bullet → bullet
    re.compile(r"^-\s+", re.MULTILINE),       # - bullet → bullet
    re.compile(r"^\d+\.\s+", re.MULTILINE),   # 1. numbered → text
    re.compile(r"`([^`]+)`"),                 # `code` → code
]


def _sanitize_token(text: str) -> str:
    """Strip internal instruction markers, unresolved templates, and markdown from LLM output."""
    if not text:
        return text
    cleaned = text
    for pattern in _INTERNAL_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    for pattern in _MARKDOWN_PATTERNS:
        if pattern.groups:
            cleaned = pattern.sub(r"\1", cleaned)
        else:
            cleaned = pattern.sub("", cleaned)
    # H-10: Strip common spoken instruction blocklist phrases that leak from prompts
    for pattern in _SPOKEN_BLOCKLIST:
        cleaned = pattern.sub("", cleaned)
    # Drop orphan quotes / punctuation left after coaching removal
    cleaned = re.sub(r"(?<!\w)[\"']+(?!\w)", "", cleaned)
    cleaned = re.sub(r"\s+([,.!?])", r"\1", cleaned)
    # Collapse extra whitespace left behind by removals
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


class StreamSanitizer:
    """Buffered sanitizer that handles internal patterns split across chunk boundaries.

    Accumulates text and only emits characters that cannot possibly be part of
    an incomplete internal pattern match.
    """
    # Longest opening prefix we need to buffer against (e.g. "[KNOWLEDGE BASE")
    _MAX_PATTERN_PREFIX = 30

    def __init__(self):
        # Keep the full raw stream and track how many *sanitized* characters we
        # have already emitted. Re-sanitizing the whole raw buffer each feed and
        # slicing the sanitized string by index avoids the lossy raw↔sanitized
        # remapping that previously dropped characters (e.g. "So,"→"o,") once
        # whitespace collapse shifted the offsets.
        self._raw = ""
        self._emitted = 0

    def feed(self, chunk: str) -> str:
        """Feed a new chunk and return the safe-to-emit portion."""
        if not chunk:
            return ""
        self._raw += chunk
        sanitized = _sanitize_token(self._raw)
        # Hold back the trailing window that might contain an incomplete pattern.
        hold_back = self._MAX_PATTERN_PREFIX
        safe_len = max(self._emitted, len(sanitized) - hold_back)
        # Never split a word mid-token: back off the emit boundary to the last
        # whitespace so TTS never receives half a word (e.g. "t|oday").
        if self._emitted < safe_len < len(sanitized):
            candidate = sanitized[:safe_len]
            if not candidate[-1:].isspace():
                last_space = candidate.rfind(" ", self._emitted)
                safe_len = last_space + 1 if last_space > self._emitted else self._emitted
        emittable = sanitized[self._emitted:safe_len]
        self._emitted = safe_len
        return emittable

    def flush(self) -> str:
        """Flush remaining buffer (call at end of stream)."""
        sanitized = _sanitize_token(self._raw)
        result = sanitized[self._emitted:]
        self._raw = ""
        self._emitted = 0
        return result
