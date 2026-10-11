"""
Voice Platform — Shared utilities.
"""

import json
import re
from typing import Any, List


def normalize_trigger_phrases(value: Any) -> List[str]:
    """
    Normalize a trigger_phrases input into a deduplicated list of strings.

    Accepts:
        - list of strings
        - JSON string representing a list
        - plain string (treated as one phrase unless it contains commas/newlines)
        - comma or newline delimited string

    Returns:
        A list of unique phrases (preserving first-seen order, case-insensitive dedup).
    """
    if isinstance(value, list):
        phrases = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            phrases = []
        else:
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    phrases = [str(item).strip() for item in parsed if str(item).strip()]
                else:
                    phrases = [stripped]
            except json.JSONDecodeError:
                phrases = [part.strip() for part in re.split(r"[,\n]", stripped) if part.strip()]
                if not phrases:
                    phrases = [stripped]
    else:
        phrases = []

    deduped: List[str] = []
    seen = set()
    for phrase in phrases:
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(phrase)
    return deduped
