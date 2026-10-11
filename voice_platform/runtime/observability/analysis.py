"""Post-conversation analysis — transcript building, LLM analysis, and PII redaction.

Moved from api/analytics_routes.py to fix upward dependency (events → api).
Both api and events now import from here (downward dependency).

Public API:
    build_transcript_text(db, call_id) -> str
    run_llm_analysis(transcript_text, user_id) -> dict
    basic_analysis(transcript_text) -> dict
    redact_sensitive_text(text) -> str
    get_or_create_analysis(db, call_log) -> Optional[dict]
"""

import json
import re
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import CallLog, Transcript

# ── PII Redaction ──────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


def redact_sensitive_text(text: str) -> str:
    """Redact common PII patterns before external model calls."""
    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    redacted = _SSN_RE.sub("[REDACTED_SSN]", redacted)
    redacted = _CARD_RE.sub("[REDACTED_CARD]", redacted)
    redacted = _PHONE_RE.sub("[REDACTED_PHONE]", redacted)
    return redacted


# ── Cached analysis retrieval ──────────────────────────────────────────

async def get_or_create_analysis(db: AsyncSession, call_log: CallLog) -> Optional[dict]:
    """Get existing analysis from call_log.analysis_json if available."""
    if getattr(call_log, 'analysis_json', None):
        try:
            return json.loads(call_log.analysis_json)
        except json.JSONDecodeError:
            pass
    return None


# ── Transcript building ────────────────────────────────────────────────

async def build_transcript_text(db: AsyncSession, call_id: int) -> str:
    """Build formatted transcript text from DB."""
    result = await db.execute(
        select(Transcript)
        .where(Transcript.call_log_id == call_id)
        .order_by(Transcript.timestamp.asc())
    )
    transcripts = result.scalars().all()

    lines = []
    for t in transcripts:
        speaker = "Customer" if t.sender == "human" else "Agent" if t.sender == "bot" else t.sender.title()
        lines.append(f"{speaker}: {t.message}")

    return "\n".join(lines)


# ── LLM-based analysis ─────────────────────────────────────────────────

async def run_llm_analysis(transcript_text: str, user_id: int) -> dict:
    """Run LLM-based analysis on a call transcript.

    Uses the user's configured LLM provider to analyze the call
    for sentiment, summary, topics, action items, and quality metrics.
    """
    if not transcript_text or len(transcript_text.strip()) < 20:
        return {
            "summary": "Call too short for analysis.",
            "sentiment": "neutral",
            "sentiment_score": 0.5,
            "topics": [],
            "action_items": [],
            "customer_satisfaction": "unknown",
            "talk_ratio": {"agent": 50, "customer": 50},
            "key_phrases": [],
            "resolution_status": "unknown",
        }

    sanitized_transcript = redact_sensitive_text(transcript_text)

    analysis_prompt = f"""Analyze this phone call transcript and return a JSON object with the following fields:

{{
  "summary": "2-3 sentence summary of the call",
  "sentiment": "positive|negative|neutral|mixed",
  "sentiment_score": 0.0 to 1.0 (0=very negative, 1=very positive),
  "topics": ["topic1", "topic2"],
  "action_items": ["action1", "action2"],
  "customer_satisfaction": "satisfied|dissatisfied|neutral|unknown",
  "talk_ratio": {{"agent": 60, "customer": 40}},
  "key_phrases": ["phrase1", "phrase2", "phrase3"],
  "resolution_status": "resolved|unresolved|escalated|unknown"
}}

TRANSCRIPT:
{sanitized_transcript[:4000]}

Return ONLY the JSON object, no markdown or explanation."""

    try:
        from voice_platform.database import Setting, UserApiKey, async_session
        from voice_platform.encryption import decrypt

        api_key = None
        base_url = None
        model = "deepseek/deepseek-v4-flash"

        from voice_platform.config import settings

        async with async_session() as session:
            key_result = await session.execute(
                select(UserApiKey).where(
                    UserApiKey.user_id == user_id,
                    UserApiKey.service == "openrouter",
                    UserApiKey.is_active == True,
                )
            )
            user_key = key_result.scalar_one_or_none()

            if user_key:
                api_key = decrypt(user_key.api_key)
                base_url = "https://openrouter.ai/api/v1"
            else:
                if settings.openrouter_api_key:
                    api_key = settings.openrouter_api_key
                    base_url = "https://openrouter.ai/api/v1"
                elif settings.groq_api_key:
                    api_key = settings.groq_api_key
                    base_url = "https://api.groq.com/openai/v1"
                    model = "openai/gpt-oss-20b"
                elif settings.openai_api_key:
                    api_key = settings.openai_api_key
                    base_url = None

            if not api_key:
                if settings.ollama_base_url:
                    api_key = settings.ollama_api_key
                    base_url = settings.ollama_base_url
                    model = "qwen3:8b"

        if not api_key:
            return basic_analysis(transcript_text)

        import httpx

        url = f"{base_url}/chat/completions" if base_url else "https://api.openai.com/v1/chat/completions"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a call analytics AI. Return only valid JSON."},
                        {"role": "user", "content": analysis_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 800,
                },
            )
            response.raise_for_status()

            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()

            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            analysis = json.loads(content)
            return analysis

    except Exception as e:
        logger.warning(f"LLM analysis failed: {e}, using basic analysis")
        return basic_analysis(transcript_text)


def basic_analysis(transcript_text: str) -> dict:
    """Basic rule-based analysis when LLM is unavailable."""
    lines = transcript_text.strip().split("\n")
    agent_lines = [l for l in lines if l.startswith("Agent:")]
    customer_lines = [l for l in lines if l.startswith("Customer:")]

    total = len(agent_lines) + len(customer_lines) or 1
    agent_ratio = int(len(agent_lines) / total * 100)
    customer_ratio = 100 - agent_ratio

    positive_words = {"thank", "great", "perfect", "excellent", "happy", "appreciate", "wonderful", "good"}
    negative_words = {"angry", "frustrated", "terrible", "awful", "bad", "worse", "complaint", "issue", "problem"}

    text_lower = transcript_text.lower()
    pos_count = sum(1 for w in positive_words if w in text_lower)
    neg_count = sum(1 for w in negative_words if w in text_lower)

    if pos_count > neg_count:
        sentiment = "positive"
        score = min(0.5 + pos_count * 0.1, 0.9)
    elif neg_count > pos_count:
        sentiment = "negative"
        score = max(0.5 - neg_count * 0.1, 0.1)
    else:
        sentiment = "neutral"
        score = 0.5

    return {
        "summary": f"Call with {len(lines)} messages between agent and customer.",
        "sentiment": sentiment,
        "sentiment_score": round(score, 2),
        "topics": [],
        "action_items": [],
        "customer_satisfaction": "unknown",
        "talk_ratio": {"agent": agent_ratio, "customer": customer_ratio},
        "key_phrases": [],
        "resolution_status": "unknown",
    }
