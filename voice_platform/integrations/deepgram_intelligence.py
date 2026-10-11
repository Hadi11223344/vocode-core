"""
Deepgram Audio Intelligence client for post-call analysis.

Uses Deepgram's pre-recorded API to analyze call recordings with:
- Sentiment Analysis (positive/negative/neutral at segment level)
- Summarization (concise call summary)
- Topic Detection (key topics with confidence scores)
- Intent Recognition (speaker intent with confidence scores)

This is cheaper, faster, and more accurate than using a generic LLM
for the same analysis, as the models are purpose-built for conversational audio.
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEEPGRAM_API_BASE = "https://api.deepgram.com/v1/listen"


async def analyze_call_recording(
    recording_url: str,
    api_key: Optional[str] = None,
    features: Optional[list[str]] = None,
) -> Optional[dict]:
    """Send a call recording URL to Deepgram for Audio Intelligence analysis.

    Args:
        recording_url: Publicly accessible URL to the call recording (e.g. Twilio MP3).
        api_key: Deepgram API key. Falls back to DEEPGRAM_API_KEY env var.
        features: List of features to enable. Defaults to all four:
                  ["sentiment", "summarize", "topics", "intents"]

    Returns:
        Normalized analysis dict matching the existing analysis_json schema,
        or None if the request fails.
    """
    if not recording_url:
        return None

    key = api_key or os.environ.get("DEEPGRAM_API_KEY")
    if not key:
        logger.warning("Deepgram Audio Intelligence: no API key available")
        return None

    if features is None:
        features = ["sentiment", "summarize", "topics", "intents"]

    params: dict = {
        "model": "nova-3",
        "smart_format": True,
        "diarize": True,
        "punctuate": True,
    }

    if "sentiment" in features:
        params["sentiment"] = True
    if "summarize" in features:
        params["summarize"] = "v2"
    if "topics" in features:
        params["topics"] = True
    if "intents" in features:
        params["intents"] = True

    payload = {"url": recording_url}

    try:
        async with httpx.AsyncClient(timeout=120, verify=True) as client:
            response = await client.post(
                DEEPGRAM_API_BASE,
                params=params,
                json=payload,
                headers={
                    "Authorization": f"Token {key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()
            return _normalize_deepgram_response(data)
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Deepgram Audio Intelligence HTTP error: {e.response.status_code} - "
            f"{e.response.text[:500]}"
        )
        return None
    except Exception as e:
        logger.error(f"Deepgram Audio Intelligence error: {type(e).__name__}: {e}")
        return None


def _normalize_deepgram_response(data: dict) -> dict:
    """Convert Deepgram's response schema to our analysis_json format.

    Deepgram returns:
    - results.channels[].alternatives[].transcript
    - metadata.sentiment_info / summary_info / topics_info / intents_info
    - results.channels[].alternatives[].sentiments / topics / intents (segments)

    We normalize to:
    - summary, sentiment, sentiment_score, topics, action_items,
      customer_satisfaction, talk_ratio, key_phrases, resolution_status,
      intents (new field), deepgram_raw (for advanced dashboards)
    """
    results = data.get("results", {})
    channels = results.get("channels", [])
    metadata = data.get("metadata", {})

    # Extract transcript for talk ratio calculation
    transcript_text = ""
    if channels:
        alternatives = channels[0].get("alternatives", [])
        if alternatives:
            transcript_text = alternatives[0].get("transcript", "")

    # ── Summarization ──
    summary_text = ""
    summary_obj = results.get("summary", {})
    if isinstance(summary_obj, dict):
        summary_text = summary_obj.get("short", "") or summary_obj.get("default", "")

    # ── Sentiment Analysis ──
    sentiment_label = "neutral"
    sentiment_score_normalized = 0.5  # our 0-1 scale
    sentiment_segments = []

    sentiment_info = metadata.get("sentiment_info", {})
    if sentiment_info and channels:
        alternatives = channels[0].get("alternatives", [])
        if alternatives:
            sentiments_data = alternatives[0].get("sentiments", {})
            segments = sentiments_data.get("segments", [])
            for seg in segments:
                sentiment_segments.append({
                    "text": seg.get("text", ""),
                    "sentiment": seg.get("sentiment", "neutral"),
                    "sentiment_score": seg.get("sentiment_score", 0),
                    "start": seg.get("start", 0),
                    "end": seg.get("end", 0),
                })

            avg = sentiments_data.get("average", 0)
            # Deepgram uses -1 to 1; we normalize to 0 to 1
            sentiment_score_normalized = round((avg + 1) / 2, 2)

            if avg > 0.15:
                sentiment_label = "positive"
            elif avg < -0.15:
                sentiment_label = "negative"
            else:
                sentiment_label = "neutral"

    # ── Topic Detection ──
    topics_list = []
    if channels:
        alternatives = channels[0].get("alternatives", [])
        if alternatives:
            topics_data = alternatives[0].get("topics", {})
            for seg in topics_data.get("segments", []):
                for topic in seg.get("topics", []):
                    topics_list.append(topic.get("topic", ""))

    # Deduplicate topics
    topics_list = list(dict.fromkeys(topics_list))

    # ── Intent Recognition ──
    intents_list = []
    if channels:
        alternatives = channels[0].get("alternatives", [])
        if alternatives:
            intents_data = alternatives[0].get("intents", {})
            for seg in intents_data.get("segments", []):
                for intent in seg.get("intents", []):
                    intents_list.append({
                        "intent": intent.get("intent", ""),
                        "confidence_score": intent.get("confidence_score", 0),
                        "text": seg.get("text", ""),
                    })

    # ── Derive customer_satisfaction from sentiment ──
    satisfaction_map = {
        "positive": "satisfied",
        "negative": "dissatisfied",
        "neutral": "neutral",
    }
    customer_satisfaction = satisfaction_map.get(sentiment_label, "unknown")

    # ── Derive resolution_status from intents ──
    resolution_status = "unknown"
    if intents_list:
        intent_strs = [i["intent"].lower() for i in intents_list]
        if any(w in " ".join(intent_strs) for w in ["cancel", "complain", "escalate", "refund"]):
            resolution_status = "unresolved"
        elif any(w in " ".join(intent_strs) for w in ["confirm", "agree", "schedule", "order", "book"]):
            resolution_status = "resolved"
        elif any(w in " ".join(intent_strs) for w in ["transfer", "escalate", "manager"]):
            resolution_status = "escalated"

    # ── Talk ratio from diarization ──
    talk_ratio = {"agent": 50, "customer": 50}
    if channels:
        alternatives = channels[0].get("alternatives", [])
        if alternatives:
            words = alternatives[0].get("words", [])
            if words:
                speaker_durations = {}
                for w in words:
                    speaker = w.get("speaker", 0)
                    dur = (w.get("end", 0) - w.get("start", 0))
                    speaker_durations[speaker] = speaker_durations.get(speaker, 0) + dur

                total = sum(speaker_durations.values())
                if total > 0 and len(speaker_durations) >= 2:
                    speakers = sorted(speaker_durations.keys())
                    # Speaker 0 = agent (bot), Speaker 1 = customer (human)
                    agent_dur = speaker_durations.get(speakers[0], 0)
                    customer_dur = speaker_durations.get(speakers[1], 0)
                    total_dur = agent_dur + customer_dur
                    if total_dur > 0:
                        talk_ratio = {
                            "agent": round(agent_dur / total_dur * 100),
                            "customer": round(customer_dur / total_dur * 100),
                        }

    # ── Key phrases from topics ──
    key_phrases = topics_list[:5]

    return {
        "summary": summary_text or f"Call with {len(transcript_text.split())} words transcribed.",
        "sentiment": sentiment_label,
        "sentiment_score": sentiment_score_normalized,
        "topics": topics_list,
        "action_items": [],
        "customer_satisfaction": customer_satisfaction,
        "talk_ratio": talk_ratio,
        "key_phrases": key_phrases,
        "resolution_status": resolution_status,
        "intents": intents_list,
        "sentiment_segments": sentiment_segments,
        "deepgram_intelligence": True,
    }
