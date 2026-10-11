"""PII redaction utilities for pre-LLM message sanitization.

Redacts sensitive data from user messages before they are sent to the LLM provider,
preventing PII from leaking into provider logs. Redaction is applied only to user
messages, not to system prompts or assistant messages.
"""

import re
from typing import List, Dict, Any

from loguru import logger

# Patterns ordered by specificity (most specific first to avoid partial matches)
_PII_PATTERNS = [
    # SSN: XXX-XX-XXXX or XXXXXXXXX
    (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), '[SSN]'),
    (re.compile(r'\b\d{9}\b'), '[SSN]'),
    # Credit card: 13-19 digit numbers (with optional spaces/dashes)
    (re.compile(r'\b(?:\d[ -]*?){13,19}\b'), '[CARD]'),
    # E.164 phone numbers: +1XXXXXXXXXX or +XXXXXXXXXX
    (re.compile(r'\+\d{10,15}\b'), '[PHONE]'),
    # US phone: (XXX) XXX-XXXX or XXX-XXX-XXXX
    (re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'), '[PHONE]'),
    # Email addresses
    (re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'), '[EMAIL]'),
]

# Track redaction counts for observability
_redaction_counts: Dict[str, int] = {}


def redact_pii(text: str) -> str:
    """Redact PII from a text string.

    Replaces phone numbers, SSNs, credit card numbers, and emails
    with bracketed placeholders. Returns the redacted text.
    """
    if not text:
        return text
    redacted = text
    for pattern, replacement in _PII_PATTERNS:
        matches = pattern.findall(redacted)
        if matches:
            count_key = replacement.strip('[]')
            _redaction_counts[count_key] = _redaction_counts.get(count_key, 0) + len(matches)
            redacted = pattern.sub(replacement, redacted)
    if redacted != text:
        logger.debug(f"PII redacted from message ({len(text) - len(redacted)} chars changed)")
    return redacted


def redact_pii_from_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Redact PII from user messages in an OpenAI chat messages list.

    Only messages with role='user' are redacted. System prompts and
    assistant messages are left untouched.
    """
    redacted_messages = []
    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), str):
            redacted = redact_pii(msg["content"])
            redacted_messages.append({**msg, "content": redacted})
        else:
            redacted_messages.append(msg)
    return redacted_messages


def get_redaction_stats() -> Dict[str, int]:
    """Return cumulative PII redaction counts for observability."""
    return dict(_redaction_counts)


def reset_redaction_stats() -> None:
    """Reset cumulative redaction counts (e.g. at start of a new call)."""
    _redaction_counts.clear()
