"""Pure leaf module for email extraction, validation, and speech formatting.

No imports from nodes, slots, extraction, integrations, database, or application services.
This is the single source of truth for ASCII email validation.
"""

import re
from typing import Optional

# Single source of truth for ASCII email validation
_ASCII_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

# Standard email regex (for finding in transcript)
_STANDARD_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Known domain aliases for spoken email normalization
_DOMAIN_ALIASES = {
    "g mail": "gmail",
    "google mail": "gmail",  # "google mail dot com" → "gmail.com"
    "proton mail": "protonmail",
    "out look": "outlook",
    "hot mail": "hotmail",
}

# Token-to-symbol mapping for candidate normalization
_TOKEN_MAP = {
    "dot": ".",
    "period": ".",
    "underscore": "_",
    "plus": "+",
    "dash": "-",
    "hyphen": "-",
}

# Number word → digit (only within candidate local part)
_NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

# Prose boundary phrases that precede email candidates
_PROSE_PREFIXES = [
    "my email is",
    "email is",
    "my email address is",
    "you can reach me at",
    "reach me at",
    "contact me at",
    "my address is",
    "it is",
    "that's",
    "that is",
]

# Trailing prose to strip
_PROSE_SUFFIXES = [
    "please",
    "thank you",
    "thanks",
    "thankyou",
    "that's it",
    "that is it",
]

# Valid local-part tokens (letters, number words, token symbols)
_LOCAL_PART_TOKENS = set(_TOKEN_MAP.keys()) | set(_NUMBER_WORDS.keys()) | {
    chr(c) for c in range(ord("a"), ord("z") + 1)
} | {chr(c) for c in range(ord("0"), ord("9") + 1)}

# Valid TLD patterns (2+ alpha chars)
_TLD_RE = re.compile(r"^[a-zA-Z]{2,}$")


def normalize_stt_email_artifacts(text: str) -> str:
    """Normalize common STT artifacts around spoken email addresses.

    Handles:
    - letter-spelling commas: ``pa,ti,ent1@…`` → ``patient1@…``
    - spoken ``at the rate`` / ``at therate`` → ``@``
    - glued domain prefix: ``@therateprotonmail.com`` → ``@protonmail.com``
    """
    if not text:
        return text

    cleaned = text
    # Spoken "@" variants before a domain word
    cleaned = re.sub(r"\bat\s+the\s+rate\b", "@", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bat\s+therate\b", "@", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\battherate\b", "@", cleaned, flags=re.IGNORECASE)
    # Deepgram often glues "the rate" into the domain after @
    cleaned = re.sub(r"@therate(?=[a-zA-Z])", "@", cleaned, flags=re.IGNORECASE)
    # Collapse whitespace around the inserted @ so regex can match
    cleaned = re.sub(r"\s*@\s*", "@", cleaned)

    cleaned = collapse_stt_comma_spelling(cleaned)
    return cleaned


def collapse_stt_comma_spelling(text: str) -> str:
    """Collapse STT letter-spelling commas in email-like spans.

    Deepgram often inserts commas between spelled letter groups, e.g.
    ``pa,ti,ent1@example.com`` → ``patient1@example.com``.
    Only commas between alphanumeric characters are removed; other commas
    in surrounding prose are left alone.
    """
    if not text or ("@" not in text and "," not in text):
        return text

    def _collapse_local(match: re.Match[str]) -> str:
        local, domain = match.group(1), match.group(2)
        collapsed = re.sub(r"(?<=[a-zA-Z0-9]),(?=[a-zA-Z0-9])", "", local)
        domain = re.sub(r"^therate", "", domain, flags=re.IGNORECASE)
        return f"{collapsed}@{domain}"

    # Allow commas inside the local part so we can find and collapse them.
    return re.sub(
        r"([a-zA-Z0-9._%+,-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
        _collapse_local,
        text,
    )


def find_standard_email(transcript: str) -> Optional[str]:
    """Find a standard format email (user@domain.tld) in transcript."""
    if not transcript:
        return None
    cleaned = normalize_stt_email_artifacts(transcript)
    match = _STANDARD_EMAIL_RE.search(cleaned)
    return match.group(0) if match else None


def extract_email_candidate_span(transcript: str) -> Optional[str]:
    """Detect and return only the spoken email candidate span from prose.

    Strategy:
    1. Try standard email regex first — return directly if found.
    2. For spoken email: find domain-ending structure (<tokens> dot <TLD>),
       locate the nearest preceding email-separator "at",
       scan backward for valid local-part tokens,
       stop at prose boundaries.
    3. Strip trailing/leading prose.
    """
    if not transcript:
        return None

    lower = normalize_stt_email_artifacts(transcript.lower().strip())

    # 1. Try standard email first
    standard = find_standard_email(lower)
    if standard:
        return standard

    # Strip trailing prose suffixes first
    # Also handle cases like "com, thank you" where comma is attached
    lower = re.sub(r"[,;!?]+\s*(thank you|thanks|thankyou|please|that's it|that is it)\s*$", "", lower)

    tokens = lower.split()
    if not tokens:
        return None

    # Strip trailing prose
    while tokens:
        last = tokens[-1].rstrip(".,;!?")
        if last in _PROSE_SUFFIXES:
            tokens.pop()
        else:
            break

    if not tokens:
        return None

    # 2. Find domain-ending structure: <tokens> dot <TLD>
    # The TLD must be the last token (after stripping prose)
    if len(tokens) < 2:
        return None

    tld_word = tokens[-1].rstrip(".,;!?")
    dot_word = tokens[-2].rstrip(".,;!?") if len(tokens) >= 2 else ""

    if dot_word not in ("dot", "period") or not _TLD_RE.match(tld_word):
        return None

    tld_idx = len(tokens) - 2  # index of "dot"/"period"

    # 3. Find the nearest preceding "at" that is the email separator
    # Scan backward from tld_idx - 1 to find "at"
    at_idx = -1
    for i in range(tld_idx - 1, -1, -1):
        if tokens[i].rstrip(".,;!?") == "at":
            at_idx = i
            break

    if at_idx == -1:
        return None

    # 4. Scan backward from at_idx for valid local-part tokens
    # Valid local-part tokens: single letters, number words, dot/underscore/plus/dash/hyphen, alphanumeric
    start_idx = at_idx
    for i in range(at_idx - 1, -1, -1):
        tok = tokens[i].rstrip(".,;!?")
        if _is_valid_local_part_token(tok):
            start_idx = i
        else:
            break

    # 5. Build the candidate span from start_idx to end
    candidate_tokens = tokens[start_idx:]

    # 6. Strip leading prose by checking for known prose prefixes
    # Join and check against prose prefix patterns
    candidate_str = " ".join(candidate_tokens)
    for prefix in sorted(_PROSE_PREFIXES, key=len, reverse=True):
        if candidate_str.startswith(prefix + " "):
            candidate_str = candidate_str[len(prefix) + 1:]
            break

    candidate_tokens = candidate_str.split()

    # 7. Strip any remaining leading non-local-part tokens
    while candidate_tokens:
        first = candidate_tokens[0].rstrip(".,;!?")
        if _is_valid_local_part_token(first):
            break
        candidate_tokens.pop(0)

    if len(candidate_tokens) < 5:
        # Minimum: local "at" domain "dot" tld = 5 tokens
        return None

    result = " ".join(candidate_tokens)
    result = result.rstrip(".,;!?")
    return result if result else None


def _is_valid_local_part_token(tok: str) -> bool:
    """Check if a token is valid in an email local part."""
    if not tok:
        return False
    if tok in _TOKEN_MAP:
        return True
    if tok in _NUMBER_WORDS:
        return True
    if _is_spelled_letters(tok):
        return True
    if re.match(r"^[a-zA-Z0-9]+$", tok):
        return True
    return False


def _is_spelled_letters(token: str) -> bool:
    """Check if a token is a single spelled letter (a-z)."""
    return len(token) == 1 and token.isalpha()


def normalize_spoken_email_candidate(span: str) -> Optional[str]:
    """Tokenize and normalize a spoken email candidate span.

    - Preserves dots, underscores, plus, hyphens in local part
    - Converts number words to digits only within candidate
    - Applies conservative domain aliases
    - Rejects malformed dot structures
    - Returns None if result is invalid
    """
    if not span:
        return None

    tokens = span.lower().strip().split()
    if not tokens:
        return None

    # Find the "at" separator
    at_idx = -1
    for i, tok in enumerate(tokens):
        if tok == "at":
            at_idx = i
            break

    if at_idx == -1:
        return None

    local_tokens = tokens[:at_idx]
    domain_tokens = tokens[at_idx + 1 :]

    if not local_tokens or not domain_tokens:
        return None

    # Normalize local part
    local_parts = []
    for tok in local_tokens:
        tok = tok.rstrip(".,;!?")
        if tok in _TOKEN_MAP:
            local_parts.append(_TOKEN_MAP[tok])
        elif tok in _NUMBER_WORDS:
            local_parts.append(_NUMBER_WORDS[tok])
        elif _is_spelled_letters(tok):
            local_parts.append(tok)
        elif re.match(r"^[a-zA-Z0-9]+$", tok):
            local_parts.append(tok)
        else:
            return None

    local_part = "".join(local_parts)

    # Validate local part structure
    if not local_part:
        return None
    if local_part.startswith("."):
        return None
    if local_part.endswith("."):
        return None
    if ".." in local_part:
        return None

    # Normalize domain
    domain_str = " ".join(t.rstrip(".,;!?") for t in domain_tokens)

    # Apply domain aliases (replace alias substring within domain)
    for alias, canonical in sorted(_DOMAIN_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in domain_str:
            domain_str = domain_str.replace(alias, canonical)
            break

    # Convert remaining domain tokens
    domain_parts = []
    for tok in domain_str.split():
        if tok in ("dot", "period"):
            domain_parts.append(".")
        elif re.match(r"^[a-zA-Z0-9-]+$", tok):
            domain_parts.append(tok)
        else:
            return None

    domain = "".join(domain_parts)

    # Validate domain structure
    if not domain:
        return None
    if domain.startswith("."):
        return None
    if domain.endswith("."):
        return None
    if ".." in domain:
        return None
    if "." not in domain:
        return None

    # Full email
    email = f"{local_part}@{domain}"

    # Lowercase for MVP casing policy
    email = email.lower()

    # Final validation
    if not validate_email(email):
        return None

    return email


def validate_email(value: str) -> bool:
    """ASCII-only email validation. Single source of truth."""
    if not value or not str(value).strip():
        return False
    return bool(_ASCII_EMAIL_RE.match(str(value).strip()))


def email_to_speech(email: str) -> str:
    """Convert stored email to speech-safe spoken form.

    Supports: . → dot, _ → underscore, + → plus, - → dash, @ → at
    Never modifies stored value.
    """
    if not email:
        return ""

    email = str(email).lower()
    local_part, _, domain = email.partition("@")

    def _convert_part(part: str) -> str:
        result = []
        for ch in part:
            if ch == ".":
                result.append(" dot ")
            elif ch == "_":
                result.append(" underscore ")
            elif ch == "+":
                result.append(" plus ")
            elif ch == "-":
                result.append(" dash ")
            else:
                result.append(ch)
        return "".join(result)

    local_spoken = _convert_part(local_part).strip()
    domain_spoken = _convert_part(domain).strip()

    # Clean up multiple spaces
    local_spoken = " ".join(local_spoken.split())
    domain_spoken = " ".join(domain_spoken.split())

    return f"{local_spoken} at {domain_spoken}"
