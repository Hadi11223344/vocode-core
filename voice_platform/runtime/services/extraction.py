"""ExtractionService — LLM-based extraction using LLMGenerationService.

Extraction is prompting, not transport. This service depends on LLMGenerationService
for LLM calls, not on LLMClient directly. Future services: ClassificationService,
SummarizationService, RoutingService, JSONExtractionService, ModerationService.

Dependency chain:
    AgentLLMFactory → LLMGenerationService → ExtractionService
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import Agent
from voice_platform.runtime.services.llm import LLMGenerationService
from voice_platform.validation.email import (
    extract_email_candidate_span,
    find_standard_email,
    normalize_spoken_email_candidate,
)
from voice_platform.validation.email import validate_email as _shared_validate_email


@dataclass(frozen=True)
class ExtractionPrompts:
    """Immutable container for agent-specific extraction prompts.

    Evolvable — later add version, loaded_at, checksum.
    """

    prompts: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


class ExtractionService:
    """LLM-based extraction. Depends on LLMGenerationService, not LLMClient.

    Internal method groups:
        Prompt management:  ensure_prompts_loaded, _get_prompt, _build_batch_prompt
        Extraction:         extract_variable, extract_batch, _per_slot_extraction
        Parsing:            _parse_json
        Normalization:      _normalize_values
    """

    _DEFAULT_EXTRACTION_PROMPTS: Dict[str, str] = {
        "is_emergency": "whether this is an emergency (answer yes or no)",
        "visit_type": "the reason for the call (e.g. booking, emergency, question)",
        "patient_name": "the caller's name",
        "caller_name": "the caller's name",
        "caller_phone": "the caller's phone number",
        "caller_email": "the caller's email address",
        "is_new_patient": "whether the caller is a new or existing customer (answer new or existing)",
        "service_requested": "the service the caller wants",
        "preferred_date": "the caller's preferred appointment date",
        "preferred_time": "the caller's preferred appointment time",
        "preferred_provider": "the caller's preferred provider name",
        "preferred_dentist": "the caller's preferred provider name",
        "insurance_provider": "the caller's insurance provider name",
        "emergency_type": "the type of emergency",
        "understood_instructions": "whether the caller understood the instructions (yes or no)",
        "has_companion": "whether the caller has someone with them (yes or no)",
        "alternative_choice": "the caller's chosen alternative option",
        "new_preferred_date": "the caller's new preferred date",
        "new_preferred_time": "the caller's new preferred time",
        "student_name": "the prospective student's full name",
        "prospect_name": "the prospective student's full name",
        "query_type": "the inquiry category; return admission_inquiry for application, eligibility, or admission guidance, otherwise general_question",
        "program_interest": "the UMT degree program the caller is interested in",
        "intermediate_marks": "the caller's Intermediate marks or percentage",
        "prospect_city": "the city the prospective student is from",
        "scholarship_tier": "the UMT scholarship tier stated by the agent after applying knowledge-base rules",
        "wants_campus_visit": "whether the caller wants a UMT campus visit (answer yes or no)",
        "wants_more_info": "whether the caller wants admission follow-up information (answer yes or no)",
        "is_interested": "whether the prospect agrees to continue the UMT outreach call (answer yes or no)",
        "budget_concern": "whether the prospect says cost or budget is a concern (answer yes or no)",
        "wants_visit": "whether the prospect wants a UMT campus visit (answer yes or no)",
        "contact_preference": "the requested follow-up channel, such as email or SMS",
        "callback_requested": "whether the prospect requests a later callback (answer yes or no)",
        "payment_preference": "the installment, scholarship, or payment option the prospect wants to discuss",
        "board": "the prospect's Intermediate examination board",
    }

    _REDACTION_PLACEHOLDER_RE = re.compile(
        r"^\[(?:email|phone|card|ssn|redacted(?:_[a-z]+)?)\]$",
        re.IGNORECASE,
    )
    _EMAIL_RE = re.compile(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    )
    _PHONE_CANDIDATE_RE = re.compile(
        r"(?<!\w)(?:\+?\d[\d\s().-]{5,}\d)(?!\w)"
    )
    _ANY_PROVIDER_RE = re.compile(
        r"\b(?:any\s+(?:dentist|doctor|provider)|no\s+preference|"
        r"recommend\s+(?:one|someone|a\s+dentist)|please\s+recommend|"
        r"whoever\s+is\s+available|anyone\s+available|not\s+sure)\b",
        re.IGNORECASE,
    )

    def __init__(self, generation_service: LLMGenerationService) -> None:
        self._generation = generation_service
        self._agent_id: int | None = None
        self._user_id: int = 0
        self._agent_timezone: str | None = None
        self._prompt_cache: dict[int, ExtractionPrompts] = {}

    def configure(
        self,
        *,
        agent_id: int | None = None,
        user_id: int = 0,
        agent_timezone: str | None = None,
    ) -> None:
        """Set agent context for subsequent extraction calls."""
        self._agent_id = agent_id
        self._user_id = user_id
        self._agent_timezone = agent_timezone

    # ── Prompt Management ──────────────────────────────────────────

    async def ensure_prompts_loaded(self, session: AsyncSession, agent_id: int) -> None:
        """Load agent-specific extraction prompts from the DB, with caching.

        Merges agent overrides over defaults. Cached per agent_id to avoid
        repeated DB reads.
        """
        if agent_id in self._prompt_cache:
            return
        prompts: dict[str, str] = {}
        try:
            result = await session.execute(
                select(Agent.extraction_prompts).where(Agent.id == agent_id)
            )
            raw = result.scalar_one_or_none()
            if raw:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    prompts = {str(k): str(v) for k, v in loaded.items()}
        except Exception as e:
            logger.warning(f"Failed to load agent extraction prompts: {e}")
        self._prompt_cache[agent_id] = ExtractionPrompts(
            prompts=MappingProxyType(prompts) if prompts else MappingProxyType({})
        )

    def _get_prompt(self, variable_name: str) -> str:
        """Get the description for a variable, checking agent overrides first, then defaults."""
        cached = self._prompt_cache.get(self._agent_id or 0)
        if cached:
            override = cached.prompts.get(variable_name)
            if override:
                return override
        return (
            self._DEFAULT_EXTRACTION_PROMPTS.get(variable_name)
            or variable_name.replace("_", " ")
        )

    # ── Public Extraction API ──────────────────────────────────────

    async def extract_variable(
        self, transcript: str, prompt: str, variable_name: str
    ) -> str | None:
        """Use the platform LLM to extract a structured value from text.

        Returns the extracted value string, or None if not found.
        """
        system = (
            "You are a precise extraction assistant. "
            "Extract ONLY the requested value from the text. "
            "Return ONLY the value — no explanation, no quotes, no markdown. "
            "If the value is not present, respond with exactly: NOT_FOUND"
        )
        user = f"Extract '{variable_name}': {prompt}\n\nText:\n{transcript}"

        raw = await self._generation.generate(
            agent_id=self._agent_id,
            user_id=self._user_id,
            system_prompt=system,
            user_prompt=user,
            max_tokens=60,
            temperature=0.0,
        )
        if raw is None:
            logger.warning("LLM extraction unavailable, using regex fallback")
            if "email" in variable_name.lower():
                m = re.search(
                    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                    transcript,
                )
                return m.group(0) if m else None
            return None

        if raw == "NOT_FOUND" or not raw:
            return None
        return raw

    async def extract_batch(
        self,
        *,
        agent_id: int | None,
        user_id: int,
        transcript: str,
        variable_names: list[str],
        last_agent_question: str = "",
        agent_timezone: str | None = None,
    ) -> Dict[str, str]:
        """Extract multiple variables from a transcript in a single LLM call.

        Returns a dict mapping variable names to extracted values.
        Variables not found in the transcript are omitted from the result.
        """
        if not variable_names:
            return {}

        self.configure(agent_id=agent_id, user_id=user_id, agent_timezone=agent_timezone)

        # Contact values must remain usable inside workflow state while the LLM
        # transport redacts them before provider calls. Extract deterministic PII
        # locally from the raw transcript, then merge it over the LLM response.
        local_values = self._extract_local_values(variable_names, transcript)

        descriptions = self._build_batch_prompt_descriptions(variable_names)
        system = self._build_batch_system_prompt()
        user = self._build_batch_user_prompt(
            descriptions, transcript, last_agent_question, agent_timezone
        )

        raw = await self._generation.generate(
            agent_id=agent_id,
            user_id=user_id,
            system_prompt=system,
            user_prompt=user,
            max_tokens=500,
            temperature=0.0,
        )

        if raw is None or not raw.strip():
            logger.warning(
                f"Batch LLM extraction returned empty response "
                f"(len={len(raw or '')}); falling back to per-slot extraction"
            )
            fallback = await self._per_slot_extraction(
                [name for name in variable_names if name not in local_values],
                transcript,
                {},
            )
            return self._normalize_values({**fallback, **local_values})

        parsed = self._parse_json(raw)
        if isinstance(parsed, dict) and parsed:
            extracted = {
                str(k): str(v)
                for k, v in parsed.items()
                if str(k) in variable_names
                if v is not None
                and str(v).strip()
                and str(v).strip().lower() not in ("not_found", "null", "none", "n/a", "")
                and not self._is_redaction_placeholder(v)
            }
            return self._normalize_values({**extracted, **local_values})

        logger.warning("Batch extraction failed, falling back to per-slot extraction")
        fallback = await self._per_slot_extraction(
            [name for name in variable_names if name not in local_values],
            transcript,
            {},
        )
        return self._normalize_values({**fallback, **local_values})

    @classmethod
    def _is_redaction_placeholder(cls, value: Any) -> bool:
        """Return whether an extracted value is a display/log redaction token."""
        return bool(cls._REDACTION_PLACEHOLDER_RE.fullmatch(str(value).strip()))

    @classmethod
    def _extract_local_values(
        cls,
        variable_names: list[str],
        transcript: str,
    ) -> Dict[str, str]:
        """Extract values that must not depend on an LLM seeing raw PII."""
        values: Dict[str, str] = {}
        requested = set(variable_names)

        email_targets = [name for name in variable_names if "email" in name.lower()]
        if email_targets:
            # Try standard email first
            standard = find_standard_email(transcript)
            if standard:
                for name in email_targets:
                    values[name] = standard.lower()
            else:
                # Try spoken email extraction
                span = extract_email_candidate_span(transcript)
                if span:
                    normalized = normalize_spoken_email_candidate(span)
                    if normalized:
                        for name in email_targets:
                            values[name] = normalized

        phone_targets = [
            name for name in variable_names
            if "phone" in name.lower() or "mobile" in name.lower()
        ]
        if phone_targets:
            candidates = []
            for match in cls._PHONE_CANDIDATE_RE.findall(transcript):
                digits = re.sub(r"\D", "", match)
                if 7 <= len(digits) <= 15:
                    candidates.append((match, digits))
            if candidates:
                raw_phone, digits = candidates[-1]
                phone = "+" + digits if raw_phone.strip().startswith("+") else digits
                for name in phone_targets:
                    values[name] = phone

        if "preferred_dentist" in requested:
            latest_caller_text = transcript.rsplit("Caller:", 1)[-1]
            if cls._ANY_PROVIDER_RE.search(latest_caller_text):
                values["preferred_dentist"] = "any available dentist"

        return values

    # ── Internal: Prompt Building ──────────────────────────────────

    def _build_batch_prompt_descriptions(self, variable_names: list[str]) -> list[str]:
        descriptions = []
        for name in variable_names:
            desc = self._get_prompt(name)
            if name in ("preferred_date", "new_preferred_date"):
                desc += " (return as YYYY-MM-DD, e.g. 2024-07-15)"
            elif name in ("preferred_time", "new_preferred_time"):
                desc += " (return as HH:MM in 24h format, e.g. 14:30)"
            elif name == "is_emergency":
                desc += " (return yes or no)"
            elif name == "is_new_patient":
                desc += " (return new or existing)"
            elif "email" in name.lower():
                desc += (" (return as a valid email address like user@domain.com. "
                         "Convert spoken words: 'at' or 'at the rate' → '@', "
                         "'dot' → '.', remove spaces and commas. "
                         "If the caller did not provide an email, return null.)")
            descriptions.append(f'- "{name}": {desc}')
        return descriptions

    @staticmethod
    def _build_batch_system_prompt() -> str:
        return (
            "You are a precise extraction assistant. "
            "Extract the requested values from the conversation transcript. "
            "Return a JSON object mapping each variable name to its extracted value. "
            "Use the exact variable names as keys. "
            "If a value is not present in the transcript, use null for that key. "
            "Return ONLY the JSON object — no explanation, no markdown formatting."
        )

    @staticmethod
    def _build_batch_user_prompt(
        descriptions: list[str],
        transcript: str,
        last_agent_question: str,
        agent_timezone: str | None,
    ) -> str:
        tz_name = agent_timezone or "UTC"
        try:
            now = datetime.now(ZoneInfo(tz_name))
            today_str = f"Today's date is {now.strftime('%Y-%m-%d')} ({now.strftime('%A')}). "
        except Exception:
            today_str = ""

        return (
            f"{today_str}"
            f"Extract the following variables from the caller's response. "
            f"The agent asked: {last_agent_question or '(unknown question)'}\n"
            f"Variables:\n{chr(10).join(descriptions)}\n\n"
            f"Transcript:\n{transcript}\n\n"
            f"Return a JSON object like: {{\"variable_name\": \"value\", ...}}"
        )

    # ── Internal: Per-Slot Extraction ──────────────────────────────

    async def _per_slot_extraction(
        self,
        variable_names: list[str],
        transcript: str,
        already_extracted: Dict[str, str],
    ) -> Dict[str, str]:
        """Extract only the variables that are still missing, one at a time."""
        results: Dict[str, str] = dict(already_extracted)
        for name in variable_names:
            if name in results and str(results[name]).strip():
                continue
            desc = self._get_prompt(name)
            val = await self.extract_variable(transcript, desc, name)
            if val:
                results[name] = val
        return self._normalize_values(results)

    # ── Internal: JSON Parsing ─────────────────────────────────────

    @staticmethod
    def _parse_json(raw: str) -> Any:
        """Parse the LLM extraction response, tolerating markdown fences and partial JSON."""
        cleaned = raw.strip()

        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            pass

        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except (json.JSONDecodeError, ValueError):
                pass

        return None

    # ── Internal: Normalization ────────────────────────────────────

    def _normalize_values(self, extracted: Dict[str, str]) -> Dict[str, str]:
        """Normalize extracted values for downstream actions.

        Uses both name-based and heuristic-based normalization.
        Name-based checks take priority; heuristics catch custom variable names.
        """
        normalized: Dict[str, str] = {}
        _DATE_RE = re.compile(r'\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}')
        _TIME_RE = re.compile(r'\d{1,2}:\d{2}')
        _PHONE_RE = re.compile(r'^\+?[\d\s\-\(\)]{7,}$')
        _EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
        for name, value in extracted.items():
            if self._is_redaction_placeholder(value):
                continue
            lname = name.lower()
            if name in ("preferred_date", "new_preferred_date") or ("date" in lname and _DATE_RE.search(value)):
                from voice_platform.integrations.plugins.calendar import (
                    _normalize_date as _norm_date,
                )
                date = _norm_date(value, self._agent_timezone)
                if date:
                    normalized[name] = date
                else:
                    normalized[name] = value
            elif name in ("preferred_time", "new_preferred_time") or ("time" in lname and _TIME_RE.search(value)):
                from voice_platform.integrations.plugins.calendar import (
                    _normalize_time as _norm_time,
                )
                time = _norm_time(value)
                if time:
                    normalized[name] = time
                else:
                    normalized[name] = value
                    logger.warning(
                        f"_normalize_values: could not parse time '{value}' "
                        f"for '{name}' — keeping raw value"
                    )
            elif "phone" in lname or "mobile" in lname or _PHONE_RE.match(value.strip()):
                digits = re.sub(r'\D', '', value)
                if digits:
                    if value.strip().startswith('+'):
                        normalized[name] = '+' + digits
                    else:
                        normalized[name] = digits
                else:
                    normalized[name] = value
            elif "email" in lname or _EMAIL_RE.match(value.strip()):
                normalized[name] = value.strip().lower().replace(' ', '')
                # Validate using shared validator
                if not _shared_validate_email(normalized[name]):
                    normalized[name] = value
            elif "name" in lname:
                normalized[name] = ' '.join(value.strip().split())
            else:
                normalized[name] = value
        return normalized
