import re
from typing import List, Optional

_GOODBYE_PHRASES = [
    "goodbye",
    "talk to you later",
    "have a good day",
    "end the call",
]


def is_goodbye_simple(message: str, phrases: Optional[List[str]]):
    if not phrases:
        phrases = _GOODBYE_PHRASES
    cleaned = re.sub(r"[^\w\s]", "", message.lower())
    return any(re.search(r"\b" + re.escape(phrase) + r"\b", cleaned) for phrase in phrases)
