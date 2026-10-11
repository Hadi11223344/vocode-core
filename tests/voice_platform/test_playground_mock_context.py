"""Playground mock context must not poison SmileCare identity collection."""

from voice_platform.flow.executor import (
    LangGraphFlowExecutor,
    _sanitize_playground_context,
    _strip_placeholder_identity,
)


def test_sanitize_drops_test_caller_and_fake_ani():
    cleaned = _sanitize_playground_context(
        {
            "caller_name": "Test Caller",
            "caller_phone": "+10000000000",
            "transcript": "",
            "visit_type": "booking",
        }
    )
    assert "caller_name" not in cleaned
    assert "caller_phone" not in cleaned
    assert cleaned.get("visit_type") == "booking"


def test_sanitize_keeps_real_identity():
    cleaned = _sanitize_playground_context(
        {
            "caller_name": "Alex Patient",
            "caller_phone": "+15555550100",
        }
    )
    assert cleaned["caller_name"] == "Alex Patient"
    assert cleaned["caller_phone"] == "+15555550100"


def test_update_context_does_not_seed_patient_name_from_placeholder():
    executor = LangGraphFlowExecutor.__new__(LangGraphFlowExecutor)
    executor._state = {"extracted_vars": {}}
    executor.update_context(
        {
            "caller_name": "Test Caller",
            "caller_phone": "+10000000000",
            "visit_type": "booking",
        }
    )
    extracted = executor._state["extracted_vars"]
    assert "caller_name" not in extracted
    assert "patient_name" not in extracted
    assert "caller_phone" not in extracted
    assert extracted.get("visit_type") == "booking"


def test_strip_placeholder_identity_clears_mirrored_patient_name():
    cleaned = _strip_placeholder_identity(
        {
            "caller_name": "Test Caller",
            "patient_name": "Test Caller",
            "caller_phone": "+10000000000",
            "service_requested": "cleaning",
        }
    )
    assert "caller_name" not in cleaned
    assert "patient_name" not in cleaned
    assert "caller_phone" not in cleaned
    assert cleaned["service_requested"] == "cleaning"
