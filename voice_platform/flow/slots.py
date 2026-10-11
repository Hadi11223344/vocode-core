"""Schema-driven slot engine and variable normalization for flow conversations.

This module introduces a lightweight, backward-compatible slot layer on top of
the existing `extracted_vars` dict. It tracks which slots are filled/confirmed,
decides the next slot to ask, normalizes values, and maps variable aliases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from voice_platform.validation.email import email_to_speech as _email_to_speech
from voice_platform.validation.email import validate_email as _shared_validate_email

# Variable aliases: ensure collected values resolve under multiple names.
# For example, `patient_name` and `caller_name` should both hold the same value.
_VARIABLE_ALIASES: dict[str, str] = {
    "patient_name": "caller_name",
    "caller_name": "patient_name",
    "caller_email": "email",
    "email": "caller_email",
    "phone": "caller_phone",
    "caller_phone": "phone",
    "mobile": "caller_phone",
}


def _canonical_name(name: str) -> str:
    """Return a canonical variable name for alias grouping."""
    # Group patient_name and caller_name under caller_name
    if name in ("patient_name", "caller_name"):
        return "caller_name"
    if name in ("caller_email", "email"):
        return "caller_email"
    if name in ("caller_phone", "phone", "mobile"):
        return "caller_phone"
    return name


# ── Slot Status ────────────────────────────────────────────────────────

class SlotStatus(str, Enum):
    """Three-state validation result for a slot."""
    MISSING = "missing"
    VALID = "valid"
    INVALID = "invalid"
    # Future extensions:
    # CONFIRMED = "confirmed"
    # INFERRED = "inferred"
    # PREFILLED = "prefilled"


# ── Built-in validators ────────────────────────────────────────────────

def _validate_phone(value: str) -> SlotStatus:
    if not value or not str(value).strip():
        return SlotStatus.MISSING
    digits = re.sub(r"\D", "", str(value))
    if len(digits) >= 7:
        return SlotStatus.VALID
    return SlotStatus.INVALID


def _validate_email(value: str) -> SlotStatus:
    """Validate email using shared validator, adapted to SlotStatus."""
    if not value or not str(value).strip():
        return SlotStatus.MISSING
    if _shared_validate_email(str(value).strip()):
        return SlotStatus.VALID
    return SlotStatus.INVALID


def _validate_date(value: str) -> SlotStatus:
    if not value or not str(value).strip():
        return SlotStatus.MISSING
    val = str(value).strip()
    norm = _normalize_date(val)
    if norm:
        try:
            from datetime import datetime
            datetime.strptime(norm, "%Y-%m-%d")
            return SlotStatus.VALID
        except ValueError:
            pass
    return SlotStatus.INVALID


def _validate_time(value: str) -> SlotStatus:
    if not value or not str(value).strip():
        return SlotStatus.MISSING
    val = str(value).strip()
    norm = _normalize_time(val)
    if norm:
        try:
            from datetime import datetime
            datetime.strptime(norm, "%H:%M")
            return SlotStatus.VALID
        except ValueError:
            pass
    return SlotStatus.INVALID


def _validate_non_empty(value: str) -> SlotStatus:
    if not value or not str(value).strip():
        return SlotStatus.MISSING
    return SlotStatus.VALID


# ── Slot Definition ────────────────────────────────────────────────────

@dataclass
class SlotDefinition:
    """Typed definition for a conversational slot.

    Defines validation, normalization, retry limits, and aliases for a slot.
    Prompts are NOT defined here — they live in collector/conversation nodes
    so the same slot can have different wording in different workflows.
    """
    name: str
    required: bool = True
    validator: Callable[[str], SlotStatus] | None = None
    normalizer: Callable[[str], str] | None = None
    max_attempts: int = 3
    default: str = ""
    aliases: list[str] = field(default_factory=list)
    requires_confirmation: bool = False


# ── Global Slot Definitions Registry ───────────────────────────────────

SLOT_DEFINITIONS: dict[str, SlotDefinition] = {
    "caller_name": SlotDefinition(
        name="caller_name",
        validator=_validate_non_empty,
        normalizer=lambda v: normalize_variable("caller_name", v),
        aliases=["patient_name"],
    ),
    "patient_name": SlotDefinition(
        name="patient_name",
        validator=_validate_non_empty,
        normalizer=lambda v: normalize_variable("patient_name", v),
        aliases=["caller_name"],
    ),
    "caller_phone": SlotDefinition(
        name="caller_phone",
        validator=_validate_phone,
        normalizer=lambda v: normalize_variable("caller_phone", v),
        aliases=["phone", "mobile"],
    ),
    "caller_email": SlotDefinition(
        name="caller_email",
        validator=_validate_email,
        normalizer=lambda v: normalize_variable("caller_email", v),
        aliases=["email"],
        requires_confirmation=True,
    ),
    "is_new_patient": SlotDefinition(
        name="is_new_patient",
        validator=_validate_non_empty,
        normalizer=lambda v: normalize_variable("is_new_patient", v),
    ),
    "is_emergency": SlotDefinition(
        name="is_emergency",
        validator=_validate_non_empty,
        normalizer=lambda v: normalize_variable("is_emergency", v),
    ),
    "service_requested": SlotDefinition(
        name="service_requested",
        validator=_validate_non_empty,
        normalizer=lambda v: normalize_variable("service_requested", v),
    ),
    "preferred_date": SlotDefinition(
        name="preferred_date",
        validator=_validate_date,
        normalizer=lambda v: normalize_variable("preferred_date", v),
    ),
    "preferred_time": SlotDefinition(
        name="preferred_time",
        validator=_validate_time,
        normalizer=lambda v: normalize_variable("preferred_time", v),
    ),
    "preferred_dentist": SlotDefinition(
        name="preferred_dentist",
        validator=_validate_non_empty,
        normalizer=lambda v: normalize_variable("preferred_dentist", v),
    ),
    "insurance_provider": SlotDefinition(
        name="insurance_provider",
        required=False,
        validator=_validate_non_empty,
        normalizer=lambda v: normalize_variable("insurance_provider", v),
    ),
    "confirm_booking": SlotDefinition(
        name="confirm_booking",
        validator=_validate_non_empty,
        normalizer=lambda v: normalize_variable("confirm_booking", v),
    ),
    "emergency_type": SlotDefinition(
        name="emergency_type",
        required=False,
        validator=_validate_non_empty,
        normalizer=lambda v: normalize_variable("emergency_type", v),
    ),
    "understood_instructions": SlotDefinition(
        name="understood_instructions",
        required=False,
        validator=_validate_non_empty,
        normalizer=lambda v: normalize_variable("understood_instructions", v),
    ),
    "has_companion": SlotDefinition(
        name="has_companion",
        required=False,
        validator=_validate_non_empty,
        normalizer=lambda v: normalize_variable("has_companion", v),
    ),
    "visit_type": SlotDefinition(
        name="visit_type",
        required=False,
        validator=_validate_non_empty,
        normalizer=lambda v: normalize_variable("visit_type", v),
    ),
}


def get_slot_definition(name: str) -> SlotDefinition:
    """Look up a SlotDefinition by name, falling back to a permissive default."""
    defn = SLOT_DEFINITIONS.get(name)
    if defn:
        return defn
    return SlotDefinition(name=name, validator=_validate_non_empty)


@dataclass
class Slot:
    """A single conversational slot."""

    name: str
    value: str = ""
    normalized_value: str = ""
    status: str = "empty"  # empty, filled, confirmed, invalid
    required: bool = True
    slot_type: str = "string"
    validation_error: str = ""
    ask_count: int = 0
    # Candidate fields — separate from confirmed primary state
    candidate_value: str = ""
    candidate_normalized: str = ""
    candidate_status: str = ""  # "", "filled", "invalid"


# ── Confirmation State Constants ─────────────────────────────────────
CONFIRMATION_NONE = "none"
CONFIRMATION_PENDING_READBACK = "candidate_pending_readback"
CONFIRMATION_AWAITING_USER = "awaiting_user_confirmation"
CONFIRMATION_CANDIDATE_INVALID = "candidate_invalid"


class SlotEngine:
    """Track slot state for a conversation node.

    The engine is initialized from the node's `variables_to_extract` list and the
    current `extracted_vars` / `slots` state. It returns the next slot to ask,
    marks slots filled/confirmed, and reports missing required slots.
    """

    # Human-readable question templates for common slots
    _DEFAULT_QUESTIONS: dict[str, str] = {
        "caller_name": "May I have your name, please?",
        "patient_name": "May I have your name, please?",
        "caller_phone": "What's the best phone number to reach you?",
        "phone": "What's the best phone number to reach you?",
        "mobile": "What's your mobile number?",
        "caller_email": "Could I get your email address?",
        "email": "Could I get your email address?",
        "is_new_patient": "Are you a new patient, or have you visited us before?",
        "service_requested": "What service do you need? For example, a cleaning, filling, or consultation.",
        "preferred_date": "What date works best for you?",
        "preferred_time": "What time would you prefer?",
        "preferred_dentist": "Do you have a preferred dentist?",
        "preferred_provider": "Do you have a preferred provider?",
        "insurance_provider": "Do you have dental insurance you'd like us to verify?",
        "is_emergency": "Is this an emergency?",
        "emergency_type": "Can you briefly tell me what happened?",
        "has_companion": "Is someone with you right now?",
        "understood_instructions": "Did you understand the instructions I gave?",
        "alternative_choice": "Which of those options would you prefer?",
        "new_preferred_date": "What other date works for you?",
        "new_preferred_time": "What other time would work?",
    }

    def __init__(
        self,
        variables: list[str],
        extracted_vars: dict[str, Any],
        slots: dict[str, dict] | None = None,
        slot_history: list[str] | None = None,
        max_asks_per_slot: int = 2,
        optional_inputs: list[str] | None = None,
    ):
        self._order = list(dict.fromkeys(variables))
        self._max_asks_per_slot = max_asks_per_slot
        self._extracted = dict(extracted_vars or {})
        self._history: list[str] = list(slot_history or [])
        self._optional = set(optional_inputs or [])
        self._telemetry: list[dict] = []

        # Confirmation state machine
        self._awaiting_confirmation_for: str = ""
        self._confirmation_readback_value: str = ""
        self._confirmation_state: str = CONFIRMATION_NONE

        # Restore persisted slot objects, or build from extracted_vars
        self._slots: dict[str, Slot] = {}
        if slots:
            _valid_fields = set(Slot.__dataclass_fields__.keys())
            for name, data in slots.items():
                if isinstance(data, dict):
                    # Backward-compatible: only pass keys that are valid Slot fields
                    filtered = {k: v for k, v in data.items() if k in _valid_fields}
                    self._slots[name] = Slot(**filtered)
        for name in self._order:
            if name not in self._slots:
                self._slots[name] = Slot(name=name, required=(name not in self._optional))
            else:
                self._slots[name].required = name not in self._optional
            self._sync_from_extracted(name)

    def _sync_from_extracted(self, name: str) -> None:
        """Update a slot's value/status from extracted_vars (and aliases).

        Does NOT overwrite slot state if the slot has a pending candidate
        (candidate_status == "filled") or is already confirmed.
        """
        slot = self._slots[name]
        # Don't clobber candidate or confirmed state
        if slot.candidate_status == "filled" or slot.status == "confirmed":
            return
        value = self._resolve_value(name)
        if value:
            if slot.value != value:
                slot.value = value
                slot.normalized_value = normalize_variable(name, value)
                slot.status = "filled"

    def _resolve_value(self, name: str) -> str:
        """Resolve a variable value, checking aliases."""
        canonical = _canonical_name(name)
        for key, val in self._extracted.items():
            if _canonical_name(key) == canonical and val:
                return str(val).strip()
        return ""

    def next_slot(self) -> Optional[Slot]:
        """Return the next slot that still needs to be asked/confirmed.

        Walks the declared variable order and returns the first slot that is
        not confirmed and still has ask-budget remaining. This implements a
        one-slot-at-a-time policy: the same slot is re-asked until it is
        filled/confirmed or its per-slot ask limit is exhausted, then the
        engine moves to the next slot in order.
        """
        for name in self._order:
            slot = self._slots[name]
            if slot.status == "confirmed":
                continue
            if not slot.value:
                if slot.ask_count < self._max_asks_per_slot:
                    return slot
            elif slot.ask_count < self._max_asks_per_slot:
                # Value exists but not confirmed; still may need confirmation
                return slot
        return None

    def can_ask(self, name: str) -> bool:
        """Return True if the named slot still has ask-budget remaining."""
        slot = self._slots.get(name)
        if not slot:
            return False
        return slot.status != "confirmed" and slot.ask_count < self._max_asks_per_slot

    def confirm(self, name: str) -> Slot:
        """Mark a slot as confirmed."""
        slot = self._slots.setdefault(name, Slot(name=name))
        slot.status = "confirmed"
        return slot

    def fill(self, name: str, value: Any, normalized: str = "") -> Slot:
        """Fill and normalize a slot value."""
        slot = self._slots.setdefault(name, Slot(name=name))
        if value is None:
            value = ""
        slot.value = str(value).strip()
        slot.normalized_value = normalized or normalize_variable(name, slot.value)
        slot.status = "filled" if slot.value else "empty"
        return slot

    def ask(self, name: str) -> Slot:
        """Record that a slot was asked."""
        slot = self._slots.setdefault(name, Slot(name=name))
        slot.ask_count += 1
        if name not in self._history:
            self._history.append(name)
        return slot

    def mark_invalid(self, name: str, error: str) -> Slot:
        """Mark a slot as invalid with an error message."""
        slot = self._slots.setdefault(name, Slot(name=name))
        slot.status = "invalid"
        slot.validation_error = error
        return slot

    # ── Candidate / Confirmation methods ───────────────────────────────

    def validate_candidate(
        self, name: str, value: str, source: str = "user"
    ) -> tuple[SlotStatus, str, str]:
        """Validate a candidate value without mutating primary slot state.

        Returns (status, normalized_value, validation_error).
        Increments ask_count and appends to history (attempt tracking only).
        Does NOT modify: slot.value, slot.normalized_value, slot.status, slot.validation_error.
        """
        name = _canonical_name(name)
        defn = get_slot_definition(name)
        slot = self._slots.setdefault(name, Slot(name=name, required=defn.required))

        # Step 1: normalize raw value
        normalized = ""
        if value:
            normalized = (
                defn.normalizer(value) if defn.normalizer else normalize_variable(name, value)
            )

        if not value or not str(value).strip():
            return SlotStatus.MISSING, "", "Value is required"

        # Step 2: validate the NORMALIZED value (not raw)
        if defn.validator:
            status = defn.validator(normalized)
        else:
            status = SlotStatus.VALID
        error = "" if status == SlotStatus.VALID else f"Invalid value for {name}"

        # Track attempt count and history only — no primary state mutation
        slot.ask_count += 1
        if name not in self._history:
            self._history.append(name)

        # Redacted telemetry — no raw values for email slots
        self._telemetry.append({
            "slot": name,
            "attempt": slot.ask_count,
            "source": source,
            "validation_result": status.value,
            "duration_ms": 0.0,
            "value_present": bool(value),
            "value_length": len(str(value)),
            "value_preview": "[REDACTED]" if "email" in name.lower() else str(value)[:50],
        })

        return status, normalized, error

    def fill_candidate(self, name: str, value: Any, normalized: str = "") -> Slot:
        """Store a candidate value without destroying the confirmed value."""
        name = _canonical_name(name)
        slot = self._slots.setdefault(name, Slot(name=name))
        slot.candidate_value = str(value).strip()
        slot.candidate_normalized = normalized or normalize_variable(name, str(value))
        slot.candidate_status = "filled"
        has_prior_confirmed = slot.status == "confirmed" and bool(slot.value)
        if not has_prior_confirmed:
            slot.value = slot.candidate_value
            slot.normalized_value = slot.candidate_normalized
            slot.status = "filled"
        return slot

    def promote_candidate(self, name: str) -> Slot | None:
        """Promote candidate to confirmed value. Called on 'yes'.

        Returns None if no filled candidate exists or confirmation state mismatch.
        """
        name = _canonical_name(name)
        slot = self._slots.get(name)
        if not slot or not slot.candidate_value or slot.candidate_status != "filled":
            return None
        if self._confirmation_state != CONFIRMATION_AWAITING_USER:
            return None
        if (
            self._confirmation_readback_value
            and slot.candidate_normalized != self._confirmation_readback_value
        ):
            return None
        slot.value = slot.candidate_value
        slot.normalized_value = slot.candidate_normalized
        slot.candidate_value = ""
        slot.candidate_normalized = ""
        slot.candidate_status = ""
        slot.status = "confirmed"
        self._awaiting_confirmation_for = ""
        self._confirmation_readback_value = ""
        self._confirmation_state = CONFIRMATION_NONE
        return slot

    def force_promote_candidate(self, name: str) -> Slot | None:
        """Promote a filled candidate without requiring an explicit Yes.

        Used when the flow leaves the owning node (retries exhausted / advanced)
        so a valid email is not lost and later nodes do not re-ask it forever.

        Also confirms a primary ``filled`` value when no candidate remains — that
        happens after readback state is partially persisted across node hops.
        """
        name = _canonical_name(name)
        slot = self._slots.get(name)
        if not slot:
            return None
        if slot.candidate_value and slot.candidate_status == "filled":
            slot.value = slot.candidate_value
            slot.normalized_value = slot.candidate_normalized or normalize_variable(
                name, slot.candidate_value
            )
            slot.candidate_value = ""
            slot.candidate_normalized = ""
            slot.candidate_status = ""
            slot.status = "confirmed"
        elif slot.value and slot.status == "filled":
            if not slot.normalized_value:
                slot.normalized_value = normalize_variable(name, slot.value)
            slot.status = "confirmed"
        else:
            return None
        if self._awaiting_confirmation_for == name:
            self._awaiting_confirmation_for = ""
            self._confirmation_readback_value = ""
            self._confirmation_state = CONFIRMATION_NONE
        return slot

    def discard_candidate(self, name: str) -> Slot:
        """Discard a candidate. Called on explicit 'no'.

        If slot was previously confirmed, preserves the confirmed value.
        If slot had no prior confirmed value, clears to empty.
        """
        name = _canonical_name(name)
        slot = self._slots.get(name)
        if not slot:
            return Slot(name=name)
        was_confirmed = slot.status == "confirmed" and bool(slot.value)
        slot.candidate_value = ""
        slot.candidate_normalized = ""
        slot.candidate_status = ""
        if not was_confirmed:
            slot.value = ""
            slot.normalized_value = ""
            slot.status = "empty"
        self._awaiting_confirmation_for = ""
        self._confirmation_readback_value = ""
        self._confirmation_state = CONFIRMATION_NONE
        return slot

    def mark_candidate_invalid(self, name: str, error: str) -> None:
        """Mark candidate as invalid without mutating primary slot state.

        Clears candidate fields and confirmation readback to prevent stale promotion.
        """
        name = _canonical_name(name)
        slot = self._slots.get(name)
        if slot:
            slot.candidate_value = ""
            slot.candidate_normalized = ""
            slot.candidate_status = "invalid"
            slot.validation_error = error
        self._confirmation_readback_value = ""
        self._confirmation_state = CONFIRMATION_CANDIDATE_INVALID

    def get_awaiting_confirmation(self) -> str:
        """Return the slot name awaiting confirmation, or empty string."""
        return self._awaiting_confirmation_for

    def set_awaiting_confirmation(self, name: str) -> None:
        """Set the slot awaiting confirmation."""
        self._awaiting_confirmation_for = _canonical_name(name) if name else ""

    def get_confirmation_readback_value(self) -> str:
        """Return the frozen readback value for delayed-response safety."""
        return self._confirmation_readback_value

    def get_confirmation_state(self) -> str:
        """Return the current confirmation state."""
        return self._confirmation_state

    def missing_required(self) -> list[str]:
        """Return required slots that are empty, invalid, or not yet confirmed.

        Values restored from a patient record enter as ``filled`` and must be
        confirmed by the caller. Values extracted from the current reply are
        explicitly confirmed by the conversation handler before this check.
        """
        result = []
        for name in self._order:
            slot = self._slots[name]
            if not slot.required:
                continue
            if not slot.value or slot.status in ("invalid", "filled"):
                result.append(name)
        return result

    def is_complete(self) -> bool:
        """Return True when all required slots are confirmed or filled."""
        for name in self._order:
            slot = self._slots[name]
            if slot.required and not slot.value:
                return False
            if slot.value and slot.status not in ("confirmed", "filled"):
                # Optional slots can remain empty; filled slots are acceptable
                if slot.status == "invalid":
                    return False
        return True

    def to_dict(self) -> dict[str, dict]:
        """Serialize slots to a plain dict for FlowState."""
        return {name: {
            "name": s.name,
            "value": s.value,
            "normalized_value": s.normalized_value,
            "status": s.status,
            "required": s.required,
            "slot_type": s.slot_type,
            "validation_error": s.validation_error,
            "ask_count": s.ask_count,
            "candidate_value": s.candidate_value,
            "candidate_normalized": s.candidate_normalized,
            "candidate_status": s.candidate_status,
        } for name, s in self._slots.items()}

    def get_history(self) -> list[str]:
        """Return the ordered list of slots that have been asked."""
        return list(self._history)

    def get_question(self, name: str) -> str:
        """Return a default or caller-facing question for a slot."""
        return self._DEFAULT_QUESTIONS.get(name, f"Could you tell me your {name.replace('_', ' ')}?")

    # ── Slot validator / collector support ─────────────────────────────

    def next_missing_slot(self, slot_names: list[str]) -> str | None:
        """Return the name of the first missing or invalid slot, or None if all valid.

        Iterates slot_names in order. For each:
        - Resolves the value (with alias support).
        - If value is empty → returns the slot name (needs collection).
        - If a validator is registered and returns INVALID → returns the slot name (re-collect).
        - If ask_count >= max_attempts and still missing/invalid → skip (exhausted).
        """
        for name in slot_names:
            defn = get_slot_definition(name)
            slot = self._slots.get(name)
            if not slot:
                slot = Slot(name=name, required=defn.required)
                self._slots[name] = slot
                self._sync_from_extracted(name)

            value = self._resolve_value(name)
            if not value:
                if self.is_exhausted(name):
                    continue
                return name

            if defn.validator:
                status = defn.validator(value)
                if status == SlotStatus.INVALID:
                    if self.is_exhausted(name):
                        continue
                    return name
        return None

    def slot_status(self, name: str) -> SlotStatus:
        """Return the current SlotStatus for a named slot."""
        defn = get_slot_definition(name)
        slot = self._slots.get(name)
        if not slot or not slot.value:
            return SlotStatus.MISSING
        if defn.validator:
            return defn.validator(slot.value)
        return SlotStatus.VALID

    def record_attempt(self, name: str, value: str, source: str = "user") -> SlotStatus:
        """Record a collection attempt for a slot.

        Fills the slot, runs normalizer, runs validator, increments ask_count,
        emits a telemetry event, and returns the resulting SlotStatus.
        """
        import time as _time

        defn = get_slot_definition(name)
        slot = self._slots.setdefault(name, Slot(name=name, required=defn.required))

        t0 = _time.time()
        normalized = ""
        if value:
            if defn.normalizer:
                normalized = defn.normalizer(value)
            else:
                normalized = normalize_variable(name, value)

        slot.value = str(value).strip() if value else ""
        slot.normalized_value = normalized
        slot.ask_count += 1

        if not slot.value:
            status = SlotStatus.MISSING
            slot.status = "empty"
        elif defn.validator:
            status = defn.validator(slot.value)
            slot.status = "filled" if status == SlotStatus.VALID else "invalid"
            slot.validation_error = "" if status == SlotStatus.VALID else f"Invalid value for {name}"
        else:
            status = SlotStatus.VALID
            slot.status = "filled"

        if name not in self._history:
            self._history.append(name)

        duration_ms = round((_time.time() - t0) * 1000, 1)
        self._telemetry.append({
            "slot": name,
            "attempt": slot.ask_count,
            "source": source,
            "validation_result": status.value,
            "duration_ms": duration_ms,
            "value_preview": slot.value[:50] if slot.value else "",
        })

        return status

    def is_exhausted(self, name: str) -> bool:
        """Return True if the slot has used all attempts and is still not valid."""
        defn = get_slot_definition(name)
        slot = self._slots.get(name)
        if not slot:
            return False
        max_attempts = defn.max_attempts or self._max_asks_per_slot
        if slot.ask_count >= max_attempts:
            status = self.slot_status(name)
            return status != SlotStatus.VALID
        return False

    def exhausted_slots(self, slot_names: list[str]) -> list[str]:
        """Return names of slots that are exhausted (max attempts hit, still invalid/missing)."""
        return [name for name in slot_names if self.is_exhausted(name)]

    @classmethod
    def from_dict(cls, data: dict, extracted_vars: dict[str, Any] | None = None) -> "SlotEngine":
        """Reconstruct a SlotEngine from a serialized dict (for FlowState persistence)."""
        if not data:
            return cls(variables=[], extracted_vars=extracted_vars or {})
        engine = cls(
            variables=data.get("_order", []),
            extracted_vars=extracted_vars or data.get("_extracted", {}),
            slots=data.get("_slots", {}),
            slot_history=data.get("_history", []),
            max_asks_per_slot=data.get("_max_asks_per_slot", 2),
            optional_inputs=data.get("_optional", []),
        )
        engine._telemetry = data.get("_telemetry", [])
        engine._awaiting_confirmation_for = data.get("_awaiting_confirmation_for", "")
        engine._confirmation_readback_value = data.get("_confirmation_readback_value", "")
        engine._confirmation_state = data.get("_confirmation_state", CONFIRMATION_NONE)
        return engine

    def to_engine_dict(self) -> dict:
        """Serialize the full engine state (not just slots) for FlowState persistence."""
        return {
            "_order": self._order,
            "_max_asks_per_slot": self._max_asks_per_slot,
            "_extracted": self._extracted,
            "_history": self._history,
            "_optional": list(self._optional),
            "_slots": self.to_dict(),
            "_telemetry": self._telemetry,
            "_awaiting_confirmation_for": self._awaiting_confirmation_for,
            "_confirmation_readback_value": self._confirmation_readback_value,
            "_confirmation_state": self._confirmation_state,
        }


def normalize_variable(name: str, value: str) -> str:
    """Normalize a single extracted variable value by name/type heuristics.

    Keep this function in sync with `_normalize_extracted_values` in
    `integrations/executor.py`.
    """
    if not value:
        return value

    lname = name.lower()
    val = str(value).strip()

    # Phone / mobile
    if "phone" in lname or "mobile" in lname:
        digits = re.sub(r"\D", "", val)
        if digits:
            return "+" + digits if val.startswith("+") else digits
        return val

    # Email
    if "email" in lname:
        from voice_platform.validation.email import find_standard_email, normalize_stt_email_artifacts

        collapsed = normalize_stt_email_artifacts(val.lower().replace(" ", ""))
        found = find_standard_email(collapsed)
        return (found or collapsed).lower()

    # Date
    if lname in ("preferred_date", "new_preferred_date") or "date" in lname:
        norm = _normalize_date(val)
        if norm:
            return norm
        return val

    # Time
    if lname in ("preferred_time", "new_preferred_time") or "time" in lname:
        norm = _normalize_time(val)
        if norm:
            return norm
        return val

    # Name
    if "name" in lname and "insurance" not in lname:
        # Strip "Dr." / "Doctor" prefix if caller repeats it
        val = re.sub(r"^(?:Dr\.?|Doctor)\s+", "", val, flags=re.IGNORECASE)
        return " ".join(val.split())

    # Boolean-ish
    if lname in ("is_emergency", "is_new_patient", "understood_instructions", "has_companion", "confirm_booking"):
        lowered = val.lower().strip()
        is_true = lowered in (
            "yes", "true", "1", "y", "new", "new patient", "yeah", "yep", "sure",
            "ok", "okay", "go ahead", "please", "please do", "book it", "sounds good",
        ) or bool(re.match(r"^(yes|yeah|yep|yup|sure|ok|okay)([,\s!].*)?$", lowered))
        is_false = lowered in (
            "no", "false", "0", "n", "existing", "existing patient",
            "old patient", "returning patient", "visited before", "nope", "nah",
        ) or bool(re.match(r"^(no|nope|nah)([,\s!].*)?$", lowered))
        if lname == "is_emergency":
            if is_true:
                return "true"
            if is_false:
                return "false"
            return val
        if lname == "is_new_patient":
            if is_true:
                return "new"
            if is_false:
                return "existing"
            return val
        if is_true:
            return "yes"
        if is_false:
            return "no"
        return val

    # Dentist/Provider
    if "dentist" in lname or "provider" in lname:
        no_preference_patterns = (
            r"\bany\s+(?:dentist|doctor|provider)\b",
            r"\bno\s+preference\b",
            r"\b(?:please\s+)?recommend(?:\s+(?:one|someone|a\s+dentist))?\b",
            r"\bwhoever\s+is\s+available\b",
            r"\banyone\s+available\b",
            r"\bnot\s+sure\b",
            # Call 109: "No. I don't." / "No I don't have any preference"
            r"\bno\.?\s*i\s+don'?t\b",
            r"\bi\s+don'?t\s+(?:have\s+)?(?:any\s+)?(?:preference|prefer)?\b",
            r"\bdon'?t\s+(?:have\s+)?(?:a\s+|any\s+)?preference\b",
            r"^(?:no|nope|nah|none)[.!\s]*$",
        )
        if any(re.search(pattern, val, re.IGNORECASE) for pattern in no_preference_patterns):
            return "any available dentist"
        return re.sub(r"^(?:Dr\.?|Doctor)\s+", "", val, flags=re.IGNORECASE).strip()

    return val


def _normalize_date(value: str) -> str | None:
    """Best-effort normalize a date to YYYY-MM-DD."""
    import re
    from datetime import datetime, timedelta

    value = value.strip().strip("'\"")
    # Already normalized
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return value

    # Common formats
    patterns = [
        (r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", "mdy"),
        (r"(\d{1,2})[/-](\d{1,2})[/-](\d{2})", "mdy_short"),
        (r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", "ymd"),
    ]
    for pattern, fmt in patterns:
        m = re.match(pattern, value)
        if m:
            try:
                if fmt == "mdy":
                    month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
                elif fmt == "mdy_short":
                    month, day, year = int(m.group(1)), int(m.group(2)), int("20" + m.group(3))
                else:
                    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return datetime(year, month, day).strftime("%Y-%m-%d")
            except ValueError:
                pass

    # Relative words
    lowered = value.lower()
    if lowered in ("today", "now"):
        return datetime.now().strftime("%Y-%m-%d")
    if lowered == "tomorrow":
        return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    if lowered == "day after tomorrow":
        return (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")

    # Weekday names: "sunday", "next monday", "this friday", or embedded
    # in longer phrases like "Thursday, 1PM" / "book it for Thursday at 1"
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    m = re.match(r'^(next|this)?\s*(' + '|'.join(weekdays) + r')$', lowered)
    if not m:
        m = re.search(
            r'\b(next|this)?\s*(' + '|'.join(weekdays) + r')\b',
            lowered,
        )
    if m:
        today = datetime.now().date()
        modifier = (m.group(1) or "").strip()
        target_day = weekdays.index(m.group(2))
        current_day = today.weekday()
        if modifier == "next":
            days_ahead = (target_day - current_day) % 7 or 7
        else:
            days_ahead = (target_day - current_day) % 7
            if days_ahead == 0:
                days_ahead = 7  # "sunday" when today is sunday means next sunday
        return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    return None


def _normalize_time(value: str) -> str | None:
    """Best-effort normalize a time to HH:MM (24h)."""
    import re

    value = value.strip().strip("'\"")
    if not value:
        return None

    # Common session-of-day descriptors used by callers
    session_map = {
        "morning": "10:00",
        "afternoon": "14:00",
        "evening": "18:00",
        "night": "20:00",
        "mornings": "10:00",
        "afternoons": "14:00",
        "evenings": "18:00",
    }
    lowered = value.lower().rstrip(".")
    if lowered in session_map:
        return session_map[lowered]

    # Already normalized
    if re.match(r"^\d{1,2}:\d{2}$", value):
        hour, minute = (int(part) for part in value.split(":"))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
        return None

    # 12h with AM/PM
    m = re.match(r"^(\d{1,2}):?(\d{2})?\s*(AM|PM|am|pm)$", value)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3).upper()
        if not 1 <= hour <= 12 or not 0 <= minute <= 59:
            return None
        if ampm == "PM" and hour != 12:
            hour += 12
        if ampm == "AM" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    # Plain hour:minute (24h)
    m = re.match(r"^(\d{1,2}):(\d{2})$", value)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
        return None

    # Hour only
    m = re.match(r"^(\d{1,2})\s*(?:o'?clock)?$", value, re.IGNORECASE)
    if m:
        hour = int(m.group(1))
        if 0 <= hour <= 23:
            return f"{hour:02d}:00"
        return None

    return None


def mirror_aliases(extracted_vars: dict[str, Any]) -> dict[str, Any]:
    """Write alias values back into extracted_vars so templates resolve.

    For example, if `patient_name` is collected but `caller_name` is used in a
    template, copy `patient_name` to `caller_name` and vice versa.
    """
    out = dict(extracted_vars)
    for key, val in list(out.items()):
        if val and key in _VARIABLE_ALIASES:
            alias = _VARIABLE_ALIASES[key]
            if alias not in out or not out[alias]:
                out[alias] = val
    return out
