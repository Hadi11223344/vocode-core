import pytest

from voice_platform.flow.slots import (
    SLOT_DEFINITIONS,
    SlotDefinition,
    SlotEngine,
    SlotStatus,
    _validate_date,
    get_slot_definition,
    mirror_aliases,
    normalize_variable,
)


def test_slot_engine_next_and_fill():
    engine = SlotEngine(
        variables=["patient_name", "caller_email"],
        extracted_vars={},
    )
    assert engine.next_slot().name == "patient_name"
    engine.ask("patient_name")
    engine.fill("patient_name", "Alice", normalize_variable("patient_name", "Alice"))
    engine.confirm("patient_name")
    assert engine.next_slot().name == "caller_email"
    assert engine.missing_required() == ["caller_email"]


def test_prefilled_required_slots_remain_pending_until_confirmed():
    engine = SlotEngine(
        variables=["patient_name", "caller_phone", "caller_email"],
        extracted_vars={
            "patient_name": "Alex Patient",
            "caller_phone": "+15555550100",
            "caller_email": "patient1@example.com",
        },
    )
    engine.confirm("patient_name")

    assert engine.missing_required() == ["caller_phone", "caller_email"]

    engine.confirm("caller_phone")
    engine.confirm("caller_email")
    assert engine.missing_required() == []


def test_slot_engine_history_tracks_asked_slots():
    engine = SlotEngine(variables=["service_requested"], extracted_vars={})
    engine.ask("service_requested")
    engine.fill("service_requested", "cleaning", "cleaning")
    engine.confirm("service_requested")
    assert engine.get_history() == ["service_requested"]


def test_mirror_aliases_patient_to_caller():
    result = mirror_aliases({"patient_name": "Alice"})
    assert result["patient_name"] == "Alice"
    assert result["caller_name"] == "Alice"


def test_normalize_phone_strips_non_digits():
    assert normalize_variable("caller_phone", "+1 (555) 123-4567") == "+15551234567"


def test_normalize_email_lowercases():
    assert normalize_variable("caller_email", "Alice@Example.COM") == "alice@example.com"


@pytest.mark.parametrize(
    "value",
    [
        "any dentist",
        "no preference",
        "I'm not sure, please recommend",
        "recommend one",
        "whoever is available",
        "No. I don't.",
        "No I don't have any preference",
    ],
)
def test_normalize_dentist_recommendation_intent(value):
    assert normalize_variable("preferred_dentist", value) == "any available dentist"


def test_normalize_time_session_words():
    assert normalize_variable("preferred_time", "morning") == "10:00"
    assert normalize_variable("preferred_time", "afternoon") == "14:00"
    assert normalize_variable("preferred_time", "evening") == "18:00"


@pytest.mark.parametrize("value", ["24:00", "12:60", "99:99", "13 PM"])
def test_impossible_times_are_invalid(value):
    from voice_platform.flow.slots import _validate_time

    assert _validate_time(value) == SlotStatus.INVALID


@pytest.mark.parametrize("value", ["2026-02-30", "2026-13-01", "2026-00-10"])
def test_impossible_dates_are_invalid(value):
    assert _validate_date(value) == SlotStatus.INVALID


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("new", "new"),
        ("yes", "new"),
        ("existing", "existing"),
        ("old patient", "existing"),
        ("no", "existing"),
    ],
)
def test_new_patient_status_uses_business_vocabulary(raw_value, expected):
    assert normalize_variable("is_new_patient", raw_value) == expected


def test_slot_engine_respects_max_asks_per_slot():
    engine = SlotEngine(
        variables=["patient_name"],
        extracted_vars={},
        max_asks_per_slot=3,
    )
    assert engine.can_ask("patient_name")
    engine.ask("patient_name")
    engine.ask("patient_name")
    engine.ask("patient_name")
    assert not engine.can_ask("patient_name")


# ── SlotDefinition registry tests ──────────────────────────────────────


def test_slot_definitions_registry_has_common_slots():
    expected = [
        "caller_name", "patient_name", "caller_phone", "caller_email",
        "is_new_patient", "is_emergency", "service_requested",
        "preferred_date", "preferred_time", "preferred_dentist",
        "insurance_provider", "confirm_booking",
    ]
    for name in expected:
        assert name in SLOT_DEFINITIONS, f"Missing slot definition: {name}"


def test_get_slot_definition_returns_permissive_default():
    defn = get_slot_definition("unknown_slot_xyz")
    assert defn.name == "unknown_slot_xyz"
    assert defn.required is True
    assert defn.validator is not None


def test_slot_definition_has_no_prompt_field():
    defn = SLOT_DEFINITIONS["caller_email"]
    assert not hasattr(defn, "prompt")


# ── next_missing_slot tests ────────────────────────────────────────────


def test_next_missing_slot_returns_first_missing():
    engine = SlotEngine(
        variables=["patient_name", "caller_phone", "caller_email"],
        extracted_vars={"patient_name": "Alice"},
    )
    result = engine.next_missing_slot(["patient_name", "caller_phone", "caller_email"])
    assert result == "caller_phone"


def test_next_missing_slot_returns_none_when_all_present():
    engine = SlotEngine(
        variables=["patient_name", "caller_phone"],
        extracted_vars={"patient_name": "Alice", "caller_phone": "5551234567"},
    )
    result = engine.next_missing_slot(["patient_name", "caller_phone"])
    assert result is None


def test_next_missing_slot_returns_invalid_slot_for_recollection():
    engine = SlotEngine(
        variables=["caller_email"],
        extracted_vars={"caller_email": "not-an-email"},
    )
    result = engine.next_missing_slot(["caller_email"])
    assert result == "caller_email"


# ── record_attempt tests ───────────────────────────────────────────────


def test_record_attempt_valid_value():
    engine = SlotEngine(variables=["caller_email"], extracted_vars={})
    status = engine.record_attempt("caller_email", "alice@example.com")
    assert status == SlotStatus.VALID
    assert engine._slots["caller_email"].status == "filled"


def test_record_attempt_invalid_email():
    engine = SlotEngine(variables=["caller_email"], extracted_vars={})
    status = engine.record_attempt("caller_email", "not-an-email")
    assert status == SlotStatus.INVALID
    assert engine._slots["caller_email"].status == "invalid"


def test_record_attempt_missing_value():
    engine = SlotEngine(variables=["caller_email"], extracted_vars={})
    status = engine.record_attempt("caller_email", "")
    assert status == SlotStatus.MISSING


def test_record_attempt_emits_telemetry():
    engine = SlotEngine(variables=["caller_email"], extracted_vars={})
    engine.record_attempt("caller_email", "alice@example.com")
    assert len(engine._telemetry) == 1
    event = engine._telemetry[0]
    assert event["slot"] == "caller_email"
    assert event["validation_result"] == "valid"
    assert event["attempt"] == 1
    assert "duration_ms" in event


# ── is_exhausted tests ─────────────────────────────────────────────────


def test_is_exhausted_after_max_attempts():
    engine = SlotEngine(variables=["caller_email"], extracted_vars={})
    # Record 3 invalid attempts (default max_attempts=3)
    engine.record_attempt("caller_email", "bad1")
    engine.record_attempt("caller_email", "bad2")
    assert not engine.is_exhausted("caller_email")
    engine.record_attempt("caller_email", "bad3")
    assert engine.is_exhausted("caller_email")


def test_is_exhausted_false_when_valid():
    engine = SlotEngine(variables=["caller_email"], extracted_vars={})
    engine.record_attempt("caller_email", "alice@example.com")
    assert not engine.is_exhausted("caller_email")


def test_exhausted_slots_returns_all_exhausted():
    engine = SlotEngine(
        variables=["caller_email", "caller_phone"],
        extracted_vars={},
    )
    # Exhaust caller_email
    for _ in range(3):
        engine.record_attempt("caller_email", "bad")
    exhausted = engine.exhausted_slots(["caller_email", "caller_phone"])
    assert "caller_email" in exhausted
    assert "caller_phone" not in exhausted


# ── to_engine_dict / from_dict round-trip ──────────────────────────────


def test_engine_dict_round_trip_preserves_state():
    engine = SlotEngine(
        variables=["patient_name", "caller_email"],
        extracted_vars={"patient_name": "Alice"},
        max_asks_per_slot=3,
    )
    engine.record_attempt("caller_email", "alice@example.com")
    serialized = engine.to_engine_dict()

    restored = SlotEngine.from_dict(serialized, extracted_vars={"patient_name": "Alice"})
    assert restored._order == engine._order
    assert restored._max_asks_per_slot == engine._max_asks_per_slot
    assert restored._history == engine._history
    assert len(restored._telemetry) == len(engine._telemetry)
    assert restored._slots["caller_email"].value == "alice@example.com"
    assert restored._slots["caller_email"].ask_count == 1


def test_from_dict_empty_returns_fresh_engine():
    engine = SlotEngine.from_dict({})
    assert engine._order == []
    assert engine._slots == {}


def test_from_dict_preserves_telemetry():
    engine = SlotEngine(variables=["caller_email"], extracted_vars={})
    engine.record_attempt("caller_email", "alice@example.com")
    engine.record_attempt("caller_email", "bob@example.com")
    serialized = engine.to_engine_dict()

    restored = SlotEngine.from_dict(serialized)
    assert len(restored._telemetry) == 2
    assert restored._telemetry[0]["slot"] == "caller_email"
    assert restored._telemetry[1]["attempt"] == 2
