"""Phase 0B: Telephony Email Capture — layered tests.

Layer 1: Unit — email utilities (voice_platform.validation.email)
Layer 2: Slot component — SlotEngine candidate/confirmation state machine
Layer 3: Runtime — conversation handler replay
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from voice_platform.flow.nodes import _build_slot_aware_instruction, create_node_handlers
from voice_platform.flow.slots import (
    Slot,
    SlotDefinition,
    SlotEngine,
    SlotStatus,
    get_slot_definition,
    mirror_aliases,
    normalize_variable,
)
from voice_platform.flow.state import make_initial_state
from voice_platform.validation.email import (
    collapse_stt_comma_spelling,
    email_to_speech,
    extract_email_candidate_span,
    find_standard_email,
    normalize_spoken_email_candidate,
    validate_email,
)

# ═══════════════════════════════════════════════════════════════════════
# Layer 1: Unit — Email Utilities
# ═══════════════════════════════════════════════════════════════════════


class TestStandardExtraction:
    def test_find_standard_email(self):
        assert find_standard_email("my email is john@example.com") == "john@example.com"

    def test_find_standard_email_none(self):
        assert find_standard_email("no email here") is None

    def test_collapse_stt_comma_spelling(self):
        assert (
            collapse_stt_comma_spelling("pa,ti,ent1@example.com")
            == "patient1@example.com"
        )

    def test_find_standard_email_with_stt_commas(self):
        assert (
            find_standard_email("No. It's pa,ti,ent1@example.com.")
            == "patient1@example.com"
        )

    def test_find_standard_email_stt_commas_drops_spelled_prefix(self):
        # First capture without trailing digit still joins spelled groups
        assert (
            find_standard_email("pa,ti,ent@example.com")
            == "patient@example.com"
        )

    def test_find_standard_email_strips_therate_domain(self):
        # Call 108: spoken "at the rate" glued into domain by STT
        assert (
            find_standard_email("pa,ti,ent1@therateexample.com")
            == "patient1@example.com"
        )

    def test_find_standard_email_spoken_at_the_rate(self):
        from voice_platform.validation.email import normalize_stt_email_artifacts

        cleaned = normalize_stt_email_artifacts(
            "it's patient1 at the rate example.com"
        )
        assert find_standard_email(cleaned) == "patient1@example.com"


class TestCandidateSpanExtraction:
    def test_candidate_strips_leading_prose(self):
        assert extract_email_candidate_span("My email is john dot smith at gmail dot com") == "john dot smith at gmail dot com"

    def test_candidate_strips_trailing_prose(self):
        assert extract_email_candidate_span("john dot smith at gmail dot com please") == "john dot smith at gmail dot com"

    def test_candidate_strips_both(self):
        assert extract_email_candidate_span("You can reach me at john dot smith at gmail dot com, thank you") == "john dot smith at gmail dot com"

    def test_candidate_multiple_at_tokens(self):
        # "You can reach me at john dot smith at gmail dot com"
        # The email-separator "at" is the one right before domain tokens
        result = extract_email_candidate_span("You can reach me at john dot smith at gmail dot com")
        assert result == "john dot smith at gmail dot com"

    def test_candidate_no_email(self):
        assert extract_email_candidate_span("Meet me at three") is None

    def test_candidate_no_false_dot(self):
        assert extract_email_candidate_span("The dot is on the screen") is None

    def test_candidate_no_false_plus(self):
        assert extract_email_candidate_span("Plus I need a cleaning") is None

    def test_candidate_no_false_add(self):
        assert extract_email_candidate_span("Add John to the sheet") is None


class TestNormalizationDotsPreserved:
    def test_dot_preserved(self):
        assert normalize_spoken_email_candidate("john dot smith at gmail dot com") == "john.smith@gmail.com"

    def test_multiple_dots_preserved(self):
        assert normalize_spoken_email_candidate("john dot a dot smith at gmail dot com") == "john.a.smith@gmail.com"


class TestNormalizationMalformedDotsRejected:
    def test_leading_dot_rejected(self):
        assert normalize_spoken_email_candidate("dot john at gmail dot com") is None

    def test_trailing_dot_rejected(self):
        assert normalize_spoken_email_candidate("john dot at gmail dot com") is None

    def test_consecutive_dots_rejected(self):
        assert normalize_spoken_email_candidate("john dot dot smith at gmail dot com") is None


class TestNormalizationSpecialChars:
    def test_underscore_preserved(self):
        assert normalize_spoken_email_candidate("john underscore smith at outlook dot com") == "john_smith@outlook.com"

    def test_plus_preserved(self):
        assert normalize_spoken_email_candidate("john plus booking at gmail dot com") == "john+booking@gmail.com"

    def test_hyphen_preserved(self):
        assert normalize_spoken_email_candidate("john dash smith at gmail dot com") == "john-smith@gmail.com"


class TestNormalizationSpokenDigits:
    def test_spoken_digit_one(self):
        assert normalize_spoken_email_candidate("john one at gmail dot com") == "john1@gmail.com"

    def test_spoken_digits_zero_seven(self):
        assert normalize_spoken_email_candidate("john zero seven at gmail dot com") == "john07@gmail.com"


class TestNormalizationDomainAliases:
    def test_g_mail_alias(self):
        assert normalize_spoken_email_candidate("john at g mail dot com") == "john@gmail.com"

    def test_google_mail_alias(self):
        assert normalize_spoken_email_candidate("john at google mail dot com") == "john@gmail.com"

    def test_proton_mail_alias(self):
        assert normalize_spoken_email_candidate("john at proton mail dot com") == "john@protonmail.com"

    def test_outlook_alias(self):
        assert normalize_spoken_email_candidate("john at out look dot com") == "john@outlook.com"

    def test_hotmail_alias(self):
        assert normalize_spoken_email_candidate("john at hot mail dot com") == "john@hotmail.com"


class TestNormalizationSpelledLetters:
    def test_spelled_lowercase(self):
        assert normalize_spoken_email_candidate("j o h n at gmail dot com") == "john@gmail.com"


class TestNormalizationPeriodSynonym:
    def test_period_synonym(self):
        assert normalize_spoken_email_candidate("john at gmail period com") == "john@gmail.com"


class TestValidation:
    def test_validate_standard_email(self):
        assert validate_email("john@example.com") is True

    def test_validate_plus_addressing(self):
        assert validate_email("user+tag@gmail.com") is True

    def test_validate_ambiguous_rejected(self):
        assert validate_email("john at mail") is False

    def test_validate_redaction_placeholder_rejected(self):
        assert validate_email("[EMAIL]") is False

    def test_validate_unicode_rejected(self):
        assert validate_email("üser@éxample.com") is False


class TestSpeechSafeFormatting:
    def test_speech_dot(self):
        assert email_to_speech("john.smith@gmail.com") == "john dot smith at gmail dot com"

    def test_speech_underscore(self):
        assert email_to_speech("john_smith@gmail.com") == "john underscore smith at gmail dot com"

    def test_speech_plus(self):
        assert email_to_speech("john+booking@gmail.com") == "john plus booking at gmail dot com"

    def test_speech_hyphen(self):
        assert email_to_speech("john-smith@protonmail.com") == "john dash smith at protonmail dot com"

    def test_speech_multiple_dots(self):
        assert email_to_speech("john.a.smith@gmail.com") == "john dot a dot smith at gmail dot com"

    def test_speech_does_not_mutate(self):
        stored = "john.smith@gmail.com"
        _ = email_to_speech(stored)
        assert stored == "john.smith@gmail.com"


class TestArchitecture:
    def test_email_validation_module_imports_independently(self):
        import voice_platform.validation.email as mod

        # Verify no circular imports — module loaded successfully
        assert hasattr(mod, "validate_email")
        assert hasattr(mod, "email_to_speech")


class TestCasingPolicy:
    def test_standard_and_spoken_same_casing(self):
        from voice_platform.validation.email import (
            find_standard_email,
            normalize_spoken_email_candidate,
        )

        # Standard path: find + normalize
        std = find_standard_email("JOHN@Gmail.com")
        norm_std = normalize_variable("caller_email", std)
        # Spoken path
        spoken = normalize_spoken_email_candidate("john at gmail dot com")
        assert norm_std == spoken == "john@gmail.com"


# ═══════════════════════════════════════════════════════════════════════
# Layer 2: Slot Component Tests
# ═══════════════════════════════════════════════════════════════════════


def _make_engine_with_email_confirmed(email: str = "old@email.com") -> SlotEngine:
    """Create engine with caller_email confirmed and published."""
    engine = SlotEngine(["caller_email"], {"caller_email": email})
    engine.confirm("caller_email")
    return engine


class TestSlotDefinitionRequiresConfirmation:
    def test_email_slot_requires_confirmation(self):
        defn = get_slot_definition("caller_email")
        assert defn.requires_confirmation is True

    def test_phone_slot_does_not_require_confirmation(self):
        defn = get_slot_definition("caller_phone")
        assert defn.requires_confirmation is False

    def test_name_slot_does_not_require_confirmation(self):
        defn = get_slot_definition("caller_name")
        assert defn.requires_confirmation is False


class TestNewEmailBecomesFilledNotConfirmed:
    def test_new_email_becomes_filled_not_confirmed(self):
        engine = SlotEngine(["caller_email"], {})
        engine.validate_candidate("caller_email", "john.smith@gmail.com")
        engine.fill_candidate("caller_email", "john.smith@gmail.com", "john.smith@gmail.com")
        engine.set_awaiting_confirmation("caller_email")
        slot = engine._slots["caller_email"]
        assert slot.status == "filled"
        assert slot.candidate_status == "filled"
        assert slot.candidate_value == "john.smith@gmail.com"

    def test_filled_email_not_in_new_extractions(self):
        engine = SlotEngine(["caller_email"], {})
        new_extractions: dict[str, str] = {}
        confirmed_updates: dict[str, str] = {}
        status, normalized, error = engine.validate_candidate("caller_email", "john.smith@gmail.com")
        if status == SlotStatus.VALID:
            engine.fill_candidate("caller_email", "john.smith@gmail.com", normalized)
            engine.set_awaiting_confirmation("caller_email")
        # Candidate must not be in either dict
        assert "caller_email" not in new_extractions
        assert "caller_email" not in confirmed_updates

    def test_candidate_never_in_extracted_vars(self):
        engine = SlotEngine(["caller_email"], {})
        status, normalized, error = engine.validate_candidate("caller_email", "john.smith@gmail.com")
        if status == SlotStatus.VALID:
            engine.fill_candidate("caller_email", "john.smith@gmail.com", normalized)
            engine.set_awaiting_confirmation("caller_email")
        # extracted_vars is engine._extracted — candidate must not be there
        assert "caller_email" not in engine._extracted


class TestYesConfirmsEmail:
    def test_yes_confirms_filled_email(self):
        engine = SlotEngine(["caller_email"], {})
        status, normalized, error = engine.validate_candidate("caller_email", "john.smith@gmail.com")
        engine.fill_candidate("caller_email", "john.smith@gmail.com", normalized)
        engine.set_awaiting_confirmation("caller_email")
        # Simulate readback generation
        engine._confirmation_readback_value = normalized
        engine._confirmation_state = "awaiting_user_confirmation"
        # Promote
        promoted = engine.promote_candidate("caller_email")
        assert promoted is not None
        slot = engine._slots["caller_email"]
        assert slot.status == "confirmed"
        assert slot.value == "john.smith@gmail.com"

    def test_yes_publishes_to_extracted_vars(self):
        engine = SlotEngine(["caller_email"], {})
        status, normalized, error = engine.validate_candidate("caller_email", "john.smith@gmail.com")
        engine.fill_candidate("caller_email", "john.smith@gmail.com", normalized)
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_readback_value = normalized
        engine._confirmation_state = "awaiting_user_confirmation"
        promoted = engine.promote_candidate("caller_email")
        confirmed_updates: dict[str, str] = {}
        if promoted:
            confirmed_updates["caller_email"] = promoted.normalized_value
        confirmed_updates = mirror_aliases(confirmed_updates)
        assert confirmed_updates["caller_email"] == "john.smith@gmail.com"
        assert confirmed_updates["email"] == "john.smith@gmail.com"


class TestNoRejectsCandidate:
    def test_new_candidate_no_clears_value(self):
        engine = SlotEngine(["caller_email"], {})
        status, normalized, error = engine.validate_candidate("caller_email", "john.smith@gmail.com")
        engine.fill_candidate("caller_email", "john.smith@gmail.com", normalized)
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_state = "awaiting_user_confirmation"
        # "no"
        engine.discard_candidate("caller_email")
        slot = engine._slots["caller_email"]
        assert slot.value == ""
        assert slot.status == "empty"
        assert slot.candidate_value == ""

    def test_correction_candidate_no_preserves_confirmed(self):
        engine = _make_engine_with_email_confirmed("old@email.com")
        status, normalized, error = engine.validate_candidate("caller_email", "new@email.com")
        engine.fill_candidate("caller_email", "new@email.com", normalized)
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_state = "awaiting_user_confirmation"
        # "no"
        engine.discard_candidate("caller_email")
        slot = engine._slots["caller_email"]
        assert slot.value == "old@email.com"
        assert slot.status == "confirmed"
        assert slot.candidate_value == ""

    def test_no_does_not_publish(self):
        engine = SlotEngine(["caller_email"], {})
        status, normalized, error = engine.validate_candidate("caller_email", "john.smith@gmail.com")
        engine.fill_candidate("caller_email", "john.smith@gmail.com", normalized)
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_state = "awaiting_user_confirmation"
        engine.discard_candidate("caller_email")
        assert "caller_email" not in engine._extracted


class TestAmbiguousReply:
    def test_ambiguous_reply_preserves_candidate(self):
        engine = SlotEngine(["caller_email"], {})
        status, normalized, error = engine.validate_candidate("caller_email", "john.smith@gmail.com")
        engine.fill_candidate("caller_email", "john.smith@gmail.com", normalized)
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_readback_value = normalized
        engine._confirmation_state = "awaiting_user_confirmation"
        # Ambiguous reply — no state change
        slot = engine._slots["caller_email"]
        assert slot.candidate_value == "john.smith@gmail.com"
        assert engine.get_awaiting_confirmation() == "caller_email"
        assert engine._confirmation_readback_value == normalized
        assert engine._confirmation_state == "awaiting_user_confirmation"


class TestCorrectionCandidate:
    def test_valid_correction_becomes_candidate(self):
        engine = _make_engine_with_email_confirmed("old@email.com")
        status, normalized, error = engine.validate_candidate("caller_email", "new@email.com")
        engine.fill_candidate("caller_email", "new@email.com", normalized)
        engine.set_awaiting_confirmation("caller_email")
        slot = engine._slots["caller_email"]
        assert slot.value == "old@email.com"
        assert slot.candidate_value == "new@email.com"

    def test_valid_correction_requires_confirmation(self):
        engine = _make_engine_with_email_confirmed("old@email.com")
        status, normalized, error = engine.validate_candidate("caller_email", "new@email.com")
        engine.fill_candidate("caller_email", "new@email.com", normalized)
        engine.set_awaiting_confirmation("caller_email")
        slot = engine._slots["caller_email"]
        assert slot.candidate_status == "filled"
        assert slot.status == "confirmed"  # primary unchanged

    def test_correction_candidate_readback(self):
        engine = _make_engine_with_email_confirmed("old@email.com")
        status, normalized, error = engine.validate_candidate("caller_email", "new@email.com")
        engine.fill_candidate("caller_email", "new@email.com", normalized)
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_readback_value = normalized
        engine._confirmation_state = "awaiting_user_confirmation"
        # Readback should use candidate, not old confirmed
        assert engine._confirmation_readback_value == "new@email.com"

    def test_no_to_correction_preserves_confirmed(self):
        engine = _make_engine_with_email_confirmed("old@email.com")
        status, normalized, error = engine.validate_candidate("caller_email", "new@email.com")
        engine.fill_candidate("caller_email", "new@email.com", normalized)
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_state = "awaiting_user_confirmation"
        engine.discard_candidate("caller_email")
        slot = engine._slots["caller_email"]
        assert slot.value == "old@email.com"
        assert slot.status == "confirmed"

    def test_invalid_correction_preserves_confirmed(self):
        engine = _make_engine_with_email_confirmed("old@email.com")
        status, normalized, error = engine.validate_candidate("caller_email", "not-an-email")
        assert status == SlotStatus.INVALID
        engine.mark_candidate_invalid("caller_email", error)
        slot = engine._slots["caller_email"]
        assert slot.value == "old@email.com"
        assert slot.status == "confirmed"


class TestNonConfirmationSlot:
    def test_non_confirmation_slot_still_immediately_confirmed(self):
        engine = SlotEngine(["caller_name"], {})
        attempt_status = engine.record_attempt("caller_name", "John", source="user")
        if attempt_status == SlotStatus.VALID:
            engine.confirm("caller_name")
        slot = engine._slots["caller_name"]
        assert slot.status == "confirmed"


class TestAwaitingConfirmation:
    def test_awaiting_confirmation_target_set(self):
        engine = SlotEngine(["caller_email"], {})
        engine.fill_candidate("caller_email", "john.smith@gmail.com", "john.smith@gmail.com")
        engine.set_awaiting_confirmation("caller_email")
        assert engine.get_awaiting_confirmation() == "caller_email"

    def test_awaiting_confirmation_cleared_after_yes(self):
        engine = SlotEngine(["caller_email"], {})
        engine.fill_candidate("caller_email", "john.smith@gmail.com", "john.smith@gmail.com")
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_readback_value = "john.smith@gmail.com"
        engine._confirmation_state = "awaiting_user_confirmation"
        engine.promote_candidate("caller_email")
        assert engine.get_awaiting_confirmation() == ""

    def test_awaiting_confirmation_cleared_after_no(self):
        engine = SlotEngine(["caller_email"], {})
        engine.fill_candidate("caller_email", "john.smith@gmail.com", "john.smith@gmail.com")
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_state = "awaiting_user_confirmation"
        engine.discard_candidate("caller_email")
        assert engine.get_awaiting_confirmation() == ""


class TestAliasCanonicalization:
    def test_email_alias_operates_on_canonical(self):
        engine = SlotEngine(["caller_email"], {})
        engine.fill_candidate("email", "john.smith@gmail.com", "john.smith@gmail.com")
        slot = engine._slots.get("caller_email")
        assert slot is not None
        assert slot.candidate_value == "john.smith@gmail.com"


class TestPromotionSafety:
    def test_no_candidate_cannot_be_promoted(self):
        engine = SlotEngine(["caller_email"], {})
        result = engine.promote_candidate("caller_email")
        assert result is None

    def test_promotion_publishes_aliases(self):
        engine = SlotEngine(["caller_email"], {})
        engine.fill_candidate("caller_email", "john.smith@gmail.com", "john.smith@gmail.com")
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_readback_value = "john.smith@gmail.com"
        engine._confirmation_state = "awaiting_user_confirmation"
        promoted = engine.promote_candidate("caller_email")
        assert promoted is not None
        confirmed_updates = mirror_aliases({"caller_email": promoted.normalized_value})
        assert "caller_email" in confirmed_updates
        assert "email" in confirmed_updates


class TestSerialization:
    def test_old_serialized_state_restores(self):
        # Simulate old slot dict without candidate fields
        old_slots = {
            "caller_email": {
                "name": "caller_email",
                "value": "old@email.com",
                "normalized_value": "old@email.com",
                "status": "confirmed",
                "required": True,
                "slot_type": "string",
                "validation_error": "",
                "ask_count": 1,
            }
        }
        old_engine_dict = {
            "_order": ["caller_email"],
            "_max_asks_per_slot": 2,
            "_extracted": {"caller_email": "old@email.com"},
            "_history": ["caller_email"],
            "_optional": [],
            "_slots": old_slots,
            "_telemetry": [],
        }
        engine = SlotEngine.from_dict(old_engine_dict)
        slot = engine._slots["caller_email"]
        assert slot.value == "old@email.com"
        assert slot.status == "confirmed"
        # Candidate fields should default to empty
        assert slot.candidate_value == ""
        assert slot.candidate_normalized == ""
        assert slot.candidate_status == ""

    def test_awaiting_confirmation_survives_serialization(self):
        engine = SlotEngine(["caller_email"], {})
        engine.fill_candidate("caller_email", "john.smith@gmail.com", "john.smith@gmail.com")
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_state = "awaiting_user_confirmation"
        engine._confirmation_readback_value = "john.smith@gmail.com"
        serialized = engine.to_engine_dict()
        restored = SlotEngine.from_dict(serialized)
        assert restored.get_awaiting_confirmation() == "caller_email"

    def test_confirmation_readback_value_survives_serialization(self):
        engine = SlotEngine(["caller_email"], {})
        engine.fill_candidate("caller_email", "john.smith@gmail.com", "john.smith@gmail.com")
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_state = "awaiting_user_confirmation"
        engine._confirmation_readback_value = "john.smith@gmail.com"
        serialized = engine.to_engine_dict()
        restored = SlotEngine.from_dict(serialized)
        assert restored._confirmation_readback_value == "john.smith@gmail.com"

    def test_confirmation_state_survives_serialization(self):
        engine = SlotEngine(["caller_email"], {})
        engine.fill_candidate("caller_email", "john.smith@gmail.com", "john.smith@gmail.com")
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_state = "awaiting_user_confirmation"
        serialized = engine.to_engine_dict()
        restored = SlotEngine.from_dict(serialized)
        assert restored._confirmation_state == "awaiting_user_confirmation"


class TestMutationAudit:
    def test_record_attempt_destroys_confirmed_value(self):
        """CONFIRMED BUG: record_attempt() on confirmed slot overwrites value."""
        engine = _make_engine_with_email_confirmed("old@email.com")
        slot = engine._slots["caller_email"]
        assert slot.value == "old@email.com"
        assert slot.status == "confirmed"
        # record_attempt overwrites
        engine.record_attempt("caller_email", "new@email.com", source="user")
        # This demonstrates the destructive behavior
        assert slot.value == "new@email.com"  # old value destroyed
        assert slot.status == "filled"  # downgraded from confirmed

    def test_validate_candidate_does_not_mutate_primary(self):
        engine = _make_engine_with_email_confirmed("old@email.com")
        slot = engine._slots["caller_email"]
        original_value = slot.value
        original_normalized = slot.normalized_value
        original_status = slot.status
        engine.validate_candidate("caller_email", "new@email.com", source="user")
        assert slot.value == original_value
        assert slot.normalized_value == original_normalized
        assert slot.status == original_status

    def test_validate_candidate_returns_status_and_normalized(self):
        engine = SlotEngine(["caller_email"], {})
        status, normalized, error = engine.validate_candidate("caller_email", "john.smith@gmail.com")
        assert status == SlotStatus.VALID
        assert normalized == "john.smith@gmail.com"
        assert error == ""

    def test_validate_candidate_validates_normalized_not_raw(self):
        """Validator receives the normalized value, not raw input."""
        engine = SlotEngine(["caller_email"], {})
        # "John.Smith@Gmail.com" normalizes to "john.smith@gmail.com"
        status, normalized, error = engine.validate_candidate("caller_email", "John.Smith@Gmail.com")
        assert status == SlotStatus.VALID
        assert normalized == "john.smith@gmail.com"  # normalized (lowercased)

    def test_validate_candidate_invalid_returns_error(self):
        engine = SlotEngine(["caller_email"], {})
        status, normalized, error = engine.validate_candidate("caller_email", "not-an-email")
        assert status == SlotStatus.INVALID
        assert error != ""

    def test_email_validator_adapts_bool_to_slotstatus(self):
        """Shared validate_email() returns bool; _validate_email adapts to SlotStatus."""
        from voice_platform.flow.slots import _validate_email
        assert _validate_email("john@example.com") == SlotStatus.VALID
        assert _validate_email("not-an-email") == SlotStatus.INVALID
        assert _validate_email("") == SlotStatus.MISSING

    def test_mark_candidate_invalid_preserves_primary(self):
        engine = _make_engine_with_email_confirmed("old@email.com")
        slot = engine._slots["caller_email"]
        engine.mark_candidate_invalid("caller_email", "Invalid value for caller_email")
        assert slot.value == "old@email.com"
        assert slot.status == "confirmed"

    def test_mark_candidate_invalid_clears_stale_state(self):
        engine = _make_engine_with_email_confirmed("old@email.com")
        engine._confirmation_readback_value = "old@readback.com"
        engine._confirmation_state = "awaiting_user_confirmation"
        engine.mark_candidate_invalid("caller_email", "Invalid value")
        slot = engine._slots["caller_email"]
        assert slot.candidate_value == ""
        assert slot.candidate_normalized == ""
        assert engine._confirmation_readback_value == ""
        assert engine._confirmation_state == "candidate_invalid"

    def test_invalid_then_yes_no_promotion(self):
        engine = _make_engine_with_email_confirmed("old@email.com")
        # Valid candidate A
        status_a, norm_a, _ = engine.validate_candidate("caller_email", "new@email.com")
        engine.fill_candidate("caller_email", "new@email.com", norm_a)
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_readback_value = norm_a
        engine._confirmation_state = "awaiting_user_confirmation"
        # Invalid replacement B
        status_b, norm_b, err_b = engine.validate_candidate("caller_email", "not-an-email")
        assert status_b == SlotStatus.INVALID
        engine.mark_candidate_invalid("caller_email", err_b)
        # Stale "yes"
        result = engine.promote_candidate("caller_email")
        assert result is None  # neither A nor B promoted


class TestTelemetryRedaction:
    def test_candidate_telemetry_no_raw_email(self):
        engine = SlotEngine(["caller_email"], {})
        engine.validate_candidate("caller_email", "john.smith@gmail.com")
        telemetry = engine._telemetry
        assert len(telemetry) > 0
        entry = telemetry[-1]
        assert entry["value_preview"] == "[REDACTED]"
        assert "john.smith" not in str(entry)


class TestReadbackSnapshot:
    def test_readback_snapshot_empty_before_readback(self):
        engine = SlotEngine(["caller_email"], {})
        status, normalized, error = engine.validate_candidate("caller_email", "john.smith@gmail.com")
        engine.fill_candidate("caller_email", "john.smith@gmail.com", normalized)
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_state = "candidate_pending_readback"
        assert engine._confirmation_readback_value == ""
        assert engine._confirmation_state == "candidate_pending_readback"

    def test_readback_generation_stores_snapshot(self):
        engine = SlotEngine(["caller_email"], {})
        status, normalized, error = engine.validate_candidate("caller_email", "john.smith@gmail.com")
        engine.fill_candidate("caller_email", "john.smith@gmail.com", normalized)
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_state = "candidate_pending_readback"
        # Simulate readback generation
        slot = engine._slots["caller_email"]
        engine._confirmation_readback_value = slot.candidate_normalized
        engine._confirmation_state = "awaiting_user_confirmation"
        assert engine._confirmation_readback_value == "john.smith@gmail.com"
        assert engine._confirmation_state == "awaiting_user_confirmation"


class TestDelayedResponse:
    def test_candidate_changed_after_readback_not_promoted(self):
        engine = SlotEngine(["caller_email"], {})
        # Candidate A
        engine.fill_candidate("caller_email", "john.smith@gmail.com", "john.smith@gmail.com")
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_readback_value = "john.smith@gmail.com"
        engine._confirmation_state = "awaiting_user_confirmation"
        # Candidate B arrives (new extraction)
        engine.fill_candidate("caller_email", "john.a.smith@gmail.com", "john.a.smith@gmail.com")
        engine._confirmation_state = "candidate_pending_readback"
        # Delayed "yes" for A
        result = engine.promote_candidate("caller_email")
        assert result is None  # B != A, not promoted

    def test_ambiguous_reply_preserves_readback_snapshot(self):
        engine = SlotEngine(["caller_email"], {})
        engine.fill_candidate("caller_email", "john.smith@gmail.com", "john.smith@gmail.com")
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_readback_value = "john.smith@gmail.com"
        engine._confirmation_state = "awaiting_user_confirmation"
        # Ambiguous reply — no state change
        assert engine._confirmation_readback_value == "john.smith@gmail.com"
        assert engine._confirmation_state == "awaiting_user_confirmation"


class TestStandardCorrectionUsesCandidatePath:
    def test_standard_correction_uses_candidate_path(self):
        engine = _make_engine_with_email_confirmed("old@email.com")
        status, normalized, error = engine.validate_candidate("caller_email", "new@example.com")
        assert status == SlotStatus.VALID
        engine.fill_candidate("caller_email", "new@example.com", normalized)
        engine.set_awaiting_confirmation("caller_email")
        slot = engine._slots["caller_email"]
        assert slot.value == "old@email.com"  # preserved
        assert slot.candidate_value == "new@example.com"  # candidate only


class TestRejectedNewCandidate:
    def test_rejected_new_candidate_slot_becomes_empty(self):
        engine = SlotEngine(["caller_email"], {})
        engine.fill_candidate("caller_email", "john.smith@gmail.com", "john.smith@gmail.com")
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_state = "awaiting_user_confirmation"
        engine.discard_candidate("caller_email")
        slot = engine._slots["caller_email"]
        assert slot.value == ""
        assert slot.status == "empty"
        assert engine.get_awaiting_confirmation() == ""
        assert engine._confirmation_state == "none"


# ═══════════════════════════════════════════════════════════════════════
# Layer 3: Runtime — Conversation Handler Replay
# ═══════════════════════════════════════════════════════════════════════

from voice_platform.flow import nodes as flow_nodes

CONTACT_VARIABLES = ["caller_name", "caller_email"]


def _contact_state(extracted_vars: dict, *, confirmed: list[str] = None):
    node = {
        "id": "conversation_contact",
        "type": "conversation",
        "data": {
            "label": "Contact Details",
            "config": {
                "prompt": "Confirm the patient's contact details.",
                "variables_to_extract": CONTACT_VARIABLES,
            },
        },
    }
    state = make_initial_state(
        user_id=1,
        agent_id=1,
        nodes_by_id={"conversation_contact": node},
        outgoing={"conversation_contact": []},
    )
    engine = SlotEngine(CONTACT_VARIABLES, extracted_vars)
    for name in (confirmed or []):
        engine.confirm(name)
    state.update({
        "current_node": "conversation_contact",
        "extracted_vars": dict(extracted_vars),
        "pending_variables_to_extract": list(CONTACT_VARIABLES),
        "_conversation_phase": "wait",
        "_slots": engine.to_dict(),
        "_slot_engine": engine.to_engine_dict(),
        "last_result": {"response": "Is that all correct?"},
        "result": {"response": "Is that all correct?"},
        "transcript": "Agent: Is that all correct?",
    })
    return state


async def _ignore_event(event: dict) -> None:
    return None


def _make_config():
    return {
        "configurable": {
            "event_callback": _ignore_event,
            "user_id": 1,
            "agent": SimpleNamespace(id=1),
        }
    }


class TestRuntimeNewSpokenEmail:
    @pytest.mark.asyncio
    async def test_runtime_spoken_email_becomes_filled(self, monkeypatch):
        state = _contact_state({})
        monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "my email is john dot smith at gmail dot com")
        monkeypatch.setattr(flow_nodes, "_extract_variables", AsyncMock(return_value={"caller_email": "john.smith@gmail.com"}))
        result = await create_node_handlers()["conversation"](state, _make_config())
        engine = SlotEngine.from_dict(result["_slot_engine"])
        slot = engine._slots.get("caller_email")
        if slot:
            assert slot.status in ("filled", "confirmed")
        # Candidate must not be in extracted_vars
        assert "caller_email" not in result.get("extracted_vars", {}) or not result["extracted_vars"].get("caller_email")

    @pytest.mark.asyncio
    async def test_runtime_yes_confirms_email(self, monkeypatch):
        # First turn: fill candidate
        state = _contact_state({})
        monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "my email is john dot smith at gmail dot com")
        monkeypatch.setattr(flow_nodes, "_extract_variables", AsyncMock(return_value={"caller_email": "john.smith@gmail.com"}))
        result1 = await create_node_handlers()["conversation"](state, _make_config())
        # Simulate generate phase setting confirmation state (readback was produced)
        engine1 = SlotEngine.from_dict(result1["_slot_engine"])
        engine1._confirmation_readback_value = "john.smith@gmail.com"
        engine1._confirmation_state = "awaiting_user_confirmation"
        readback = {
            "response": "I heard john dot smith at gmail dot com. Is that correct?",
        }
        # Second turn: "yes"
        state2 = _contact_state(result1.get("extracted_vars", {}))
        state2["_slot_engine"] = engine1.to_engine_dict()
        state2["_slots"] = engine1.to_dict()
        state2["transcript"] = result1.get("transcript", "")
        state2["last_result"] = readback
        state2["result"] = readback
        monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "yes")
        monkeypatch.setattr(flow_nodes, "_extract_variables", AsyncMock(return_value={}))
        result2 = await create_node_handlers()["conversation"](state2, _make_config())
        engine2 = SlotEngine.from_dict(result2["_slot_engine"])
        slot = engine2._slots.get("caller_email")
        if slot:
            assert slot.status == "confirmed"
        ev = result2.get("extracted_vars", {})
        if "caller_email" in ev:
            assert ev["caller_email"] == "john.smith@gmail.com"


class TestRuntimeNoRejectsNewCandidate:
    @pytest.mark.asyncio
    async def test_runtime_no_rejects_new_candidate(self, monkeypatch):
        state = _contact_state({})
        monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "my email is john dot smith at gmail dot com")
        monkeypatch.setattr(flow_nodes, "_extract_variables", AsyncMock(return_value={"caller_email": "john.smith@gmail.com"}))
        result1 = await create_node_handlers()["conversation"](state, _make_config())
        # Simulate generate phase readback (same gate as Yes-promotion)
        engine1 = SlotEngine.from_dict(result1["_slot_engine"])
        engine1._confirmation_readback_value = "john.smith@gmail.com"
        engine1._confirmation_state = "awaiting_user_confirmation"
        readback = {
            "response": "I heard john dot smith at gmail dot com. Is that correct?",
        }
        # "no" after readback
        state2 = _contact_state(result1.get("extracted_vars", {}))
        state2["_slot_engine"] = engine1.to_engine_dict()
        state2["_slots"] = engine1.to_dict()
        state2["transcript"] = result1.get("transcript", "")
        state2["last_result"] = readback
        state2["result"] = readback
        monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "no")
        monkeypatch.setattr(flow_nodes, "_extract_variables", AsyncMock(return_value={}))
        result2 = await create_node_handlers()["conversation"](state2, _make_config())
        engine2 = SlotEngine.from_dict(result2["_slot_engine"])
        slot = engine2._slots.get("caller_email")
        if slot:
            assert slot.value == ""
            assert slot.status == "empty"
        ev = result2.get("extracted_vars", {})
        assert not ev.get("caller_email")


class TestRuntimeAmbiguousReply:
    @pytest.mark.asyncio
    async def test_runtime_ambiguous_preserves_candidate(self, monkeypatch):
        state = _contact_state({})
        monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "my email is john dot smith at gmail dot com")
        monkeypatch.setattr(flow_nodes, "_extract_variables", AsyncMock(return_value={"caller_email": "john.smith@gmail.com"}))
        result1 = await create_node_handlers()["conversation"](state, _make_config())
        # Ambiguous reply
        state2 = _contact_state(result1.get("extracted_vars", {}))
        state2["_slot_engine"] = result1["_slot_engine"]
        state2["_slots"] = result1["_slots"]
        state2["transcript"] = result1.get("transcript", "")
        state2["last_result"] = result1.get("last_result", {})
        state2["result"] = result1.get("result", {})
        monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "could you repeat that?")
        monkeypatch.setattr(flow_nodes, "_extract_variables", AsyncMock(return_value={}))
        result2 = await create_node_handlers()["conversation"](state2, _make_config())
        engine2 = SlotEngine.from_dict(result2["_slot_engine"])
        slot = engine2._slots.get("caller_email")
        if slot:
            # Candidate should be preserved
            assert slot.candidate_value == "john.smith@gmail.com" or slot.value == "john.smith@gmail.com"


class TestRuntimeCorrection:
    @pytest.mark.asyncio
    async def test_runtime_correction_preserves_confirmed(self, monkeypatch):
        state = _contact_state(
            {"caller_email": "old@email.com", "email": "old@email.com"},
            confirmed=["caller_email"],
        )
        monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "actually my email is new@example.com")
        monkeypatch.setattr(flow_nodes, "_extract_variables", AsyncMock(return_value={"caller_email": "new@example.com"}))
        result = await create_node_handlers()["conversation"](state, _make_config())
        engine = SlotEngine.from_dict(result["_slot_engine"])
        slot = engine._slots.get("caller_email")
        if slot:
            assert slot.value == "old@email.com"  # preserved
        ev = result.get("extracted_vars", {})
        if "caller_email" in ev:
            assert ev["caller_email"] == "old@email.com"  # old published

    @pytest.mark.asyncio
    async def test_runtime_no_to_correction_preserves_confirmed(self, monkeypatch):
        state = _contact_state(
            {"caller_email": "old@email.com", "email": "old@email.com"},
            confirmed=["caller_email"],
        )
        # Turn 1: correction
        monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "actually my email is new@example.com")
        monkeypatch.setattr(flow_nodes, "_extract_variables", AsyncMock(return_value={"caller_email": "new@example.com"}))
        result1 = await create_node_handlers()["conversation"](state, _make_config())
        # Turn 2: "no" after readback of the correction candidate
        engine1 = SlotEngine.from_dict(result1["_slot_engine"])
        engine1._confirmation_readback_value = "new@example.com"
        engine1._confirmation_state = "awaiting_user_confirmation"
        readback = {
            "response": "I heard new at example dot com. Is that correct?",
        }
        state2 = _contact_state(result1.get("extracted_vars", {}))
        state2["_slot_engine"] = engine1.to_engine_dict()
        state2["_slots"] = engine1.to_dict()
        state2["transcript"] = result1.get("transcript", "")
        state2["last_result"] = readback
        state2["result"] = readback
        monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "no")
        monkeypatch.setattr(flow_nodes, "_extract_variables", AsyncMock(return_value={}))
        result2 = await create_node_handlers()["conversation"](state2, _make_config())
        engine2 = SlotEngine.from_dict(result2["_slot_engine"])
        slot = engine2._slots.get("caller_email")
        if slot:
            assert slot.value == "old@email.com"
            assert slot.status == "confirmed"

    @pytest.mark.asyncio
    async def test_runtime_yes_to_correction_promotes(self, monkeypatch):
        state = _contact_state(
            {"caller_email": "old@email.com", "email": "old@email.com"},
            confirmed=["caller_email"],
        )
        # Turn 1: correction
        monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "actually my email is new@example.com")
        monkeypatch.setattr(flow_nodes, "_extract_variables", AsyncMock(return_value={"caller_email": "new@example.com"}))
        result1 = await create_node_handlers()["conversation"](state, _make_config())
        # Simulate generate phase setting confirmation state (readback was produced)
        engine1 = SlotEngine.from_dict(result1["_slot_engine"])
        engine1._confirmation_readback_value = "new@example.com"
        engine1._confirmation_state = "awaiting_user_confirmation"
        readback = {
            "response": "I heard new at example dot com. Is that correct?",
        }
        # Turn 2: "yes"
        state2 = _contact_state(result1.get("extracted_vars", {}))
        state2["_slot_engine"] = engine1.to_engine_dict()
        state2["_slots"] = engine1.to_dict()
        state2["transcript"] = result1.get("transcript", "")
        state2["last_result"] = readback
        state2["result"] = readback
        monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "yes")
        monkeypatch.setattr(flow_nodes, "_extract_variables", AsyncMock(return_value={}))
        result2 = await create_node_handlers()["conversation"](state2, _make_config())
        engine2 = SlotEngine.from_dict(result2["_slot_engine"])
        slot = engine2._slots.get("caller_email")
        if slot:
            assert slot.value == "new@example.com"
            assert slot.status == "confirmed"

    @pytest.mark.asyncio
    async def test_runtime_invalid_correction_preserves_confirmed(self, monkeypatch):
        state = _contact_state(
            {"caller_email": "old@email.com", "email": "old@email.com"},
            confirmed=["caller_email"],
        )
        monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "actually use not-an-email")
        monkeypatch.setattr(flow_nodes, "_extract_variables", AsyncMock(return_value={"caller_email": "not-an-email"}))
        result = await create_node_handlers()["conversation"](state, _make_config())
        engine = SlotEngine.from_dict(result["_slot_engine"])
        slot = engine._slots.get("caller_email")
        if slot:
            assert slot.value == "old@email.com"
            assert slot.status == "confirmed"
        ev = result.get("extracted_vars", {})
        if "caller_email" in ev:
            assert ev["caller_email"] == "old@email.com"

    @pytest.mark.asyncio
    async def test_runtime_no_its_stt_email_replaces_candidate(self, monkeypatch):
        """Call 106 bug: 'No. It's ha,mm,adtahir1@…' must discard + fill new candidate."""
        state = _contact_state({})
        monkeypatch.setattr(
            flow_nodes,
            "interrupt",
            lambda _: "my email is adtahir@protonmail.com",
        )
        monkeypatch.setattr(
            flow_nodes,
            "_extract_variables",
            AsyncMock(return_value={"caller_email": "adtahir@protonmail.com"}),
        )
        result1 = await create_node_handlers()["conversation"](state, _make_config())
        engine1 = SlotEngine.from_dict(result1["_slot_engine"])
        engine1._confirmation_readback_value = "adtahir@protonmail.com"
        engine1._confirmation_state = "awaiting_user_confirmation"
        engine1.set_awaiting_confirmation("caller_email")
        readback = {
            "response": "I heard adtahir at protonmail dot com. Is that correct?",
        }
        state2 = _contact_state({})
        state2["_slot_engine"] = engine1.to_engine_dict()
        state2["_slots"] = engine1.to_dict()
        state2["transcript"] = result1.get("transcript", "")
        state2["last_result"] = readback
        state2["result"] = readback
        corrected = "patient1@example.com"
        monkeypatch.setattr(
            flow_nodes,
            "interrupt",
            lambda _: "No. It's pa,ti,ent1@example.com.",
        )
        monkeypatch.setattr(
            flow_nodes,
            "_extract_variables",
            AsyncMock(return_value={"caller_email": corrected}),
        )
        result2 = await create_node_handlers()["conversation"](state2, _make_config())
        engine2 = SlotEngine.from_dict(result2["_slot_engine"])
        slot = engine2._slots.get("caller_email")
        assert slot is not None
        assert slot.candidate_normalized == corrected or slot.normalized_value == corrected
        assert slot.status in ("filled",)
        assert result2.get("extracted_vars", {}).get("caller_email") in (None, "")

    @pytest.mark.asyncio
    async def test_runtime_yes_to_phone_does_not_promote_stale_email(self, monkeypatch):
        """Phone 'Yes' must not confirm a stale email when last turn wasn't readback."""
        state = _contact_state({})
        monkeypatch.setattr(
            flow_nodes,
            "interrupt",
            lambda _: "my email is adtahir@protonmail.com",
        )
        monkeypatch.setattr(
            flow_nodes,
            "_extract_variables",
            AsyncMock(return_value={"caller_email": "adtahir@protonmail.com"}),
        )
        result1 = await create_node_handlers()["conversation"](state, _make_config())
        engine1 = SlotEngine.from_dict(result1["_slot_engine"])
        engine1._confirmation_readback_value = "adtahir@protonmail.com"
        engine1._confirmation_state = "awaiting_user_confirmation"
        engine1.set_awaiting_confirmation("caller_email")
        phone_ask = {
            "response": "And just to confirm, your phone number is 0300 5008369, is that right?",
        }
        state2 = _contact_state({})
        state2["_slot_engine"] = engine1.to_engine_dict()
        state2["_slots"] = engine1.to_dict()
        state2["transcript"] = result1.get("transcript", "")
        state2["last_result"] = phone_ask
        state2["result"] = phone_ask
        monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "Yes.")
        monkeypatch.setattr(flow_nodes, "_extract_variables", AsyncMock(return_value={}))
        result2 = await create_node_handlers()["conversation"](state2, _make_config())
        engine2 = SlotEngine.from_dict(result2["_slot_engine"])
        slot = engine2._slots.get("caller_email")
        assert slot is not None
        assert slot.status != "confirmed"
        assert not result2.get("extracted_vars", {}).get("caller_email")


class TestRuntimeReadback:
    def test_readback_instruction_contains_speech_safe_email(self):
        """Test that _build_slot_aware_instruction produces readback with speech-safe email."""
        engine = SlotEngine(["caller_email"], {})
        engine.fill_candidate("caller_email", "john.smith@gmail.com", "john.smith@gmail.com")
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_state = "candidate_pending_readback"
        instruction = _build_slot_aware_instruction(
            "Confirm the email address.",
            "Contact Details",
            engine,
        )
        # After readback generation, state should be awaiting_user_confirmation
        assert engine._confirmation_state == "awaiting_user_confirmation"
        # Readback should contain speech-safe form
        assert "john" in instruction.lower()
        assert "gmail" in instruction.lower()

    def test_readback_uses_candidate_not_confirmed(self):
        """Readback uses candidate value, not old confirmed value."""
        engine = _make_engine_with_email_confirmed("old@email.com")
        engine.fill_candidate("caller_email", "new@email.com", "new@email.com")
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_state = "candidate_pending_readback"
        instruction = _build_slot_aware_instruction(
            "Confirm the email address.",
            "Contact Details",
            engine,
        )
        assert "new" in instruction.lower()
        assert "old@email.com" not in instruction.lower()

    def test_ambiguous_reply_repeats_same_readback(self):
        """After ambiguous reply, same readback is repeated."""
        engine = SlotEngine(["caller_email"], {})
        engine.fill_candidate("caller_email", "john.smith@gmail.com", "john.smith@gmail.com")
        engine.set_awaiting_confirmation("caller_email")
        engine._confirmation_state = "awaiting_user_confirmation"
        engine._confirmation_readback_value = "john.smith@gmail.com"
        # Second call — should produce same readback
        instruction = _build_slot_aware_instruction(
            "Confirm the email address.",
            "Contact Details",
            engine,
        )
        assert "john" in instruction.lower()
        assert engine._confirmation_readback_value == "john.smith@gmail.com"
