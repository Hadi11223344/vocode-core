import os
from typing import List

import requests
from langchain.agents import tool


@tool("word_of_the_day")
def word_of_the_day(placeholder: str) -> List[dict]:
    """Gets today's word of the day"""
    api_key = os.getenv("WORDNIK_API_KEY", "").strip()
    if not api_key:
        return [{"error": "WORDNIK_API_KEY is not configured"}]
    url = f"https://api.wordnik.com/v4/words.json/wordOfTheDay?api_key={api_key}"
    response = requests.get(url, timeout=15).json()
    return response
