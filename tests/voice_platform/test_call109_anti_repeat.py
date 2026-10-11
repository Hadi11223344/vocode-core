"""Call 109: stop repeated email/dentist/date questions that blocked booking."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from voice_platform.flow import nodes as flow_nodes
from voice_platform.flow.nodes import _build_slot_aware_instruction, create_node_handlers
from voice_platform.flow.slots import SlotEngine, normalize_variable, _normalize_date
from voice_platform.flow.state import make_initial_state


class TestNodeScopedEmailReadback:
    def test_readback_only_when_node_owns_email(self):
        engine = SlotEngine(["caller_email", "preferred_date"], {})
        engine.fill_candidate("caller_email", "alex@example.com", "alex@example.com")
        engine.set_awaiting_confirmation("caller_email")

        contact = _build_slot_aware_instruction(
            "Collect contact.",
            "Contact Details",
            engine,
            node_variables=["caller_email"],
        )
        assert "I heard" in contact
        assert "correct" in contact.lower()

        schedule = _build_slot_aware_instruction(
            "Ask for date and time.",
            "Date and Time",
            engine,
            node_variables=["preferred_date", "preferred_time"],
        )
        assert "I heard" not in schedule
        assert "email" not in schedule.lower()

    def test_force_promote_clears_awaiting(self):
        engine = SlotEngine(["caller_email"], {})
        engine.fill_candidate("caller_email", "a@b.com", "a@b.com")
        engine.set_awaiting_confirmation("caller_email")
        promoted = engine.force_promote_candidate("caller_email")
        assert promoted is not None
        assert promoted.status == "confirmed"
        assert engine.get_awaiting_confirmation() == ""
        assert engine._slots["caller_email"].normalized_value == "a@b.com"

    def test_force_promote_confirms_filled_without_candidate(self):
        engine = SlotEngine(["caller_email"], {"caller_email": "a@b.com"})
        engine._slots["caller_email"].status = "filled"
        engine.set_awaiting_confirmation("caller_email")
        promoted = engine.force_promote_candidate("caller_email")
        assert promoted is not None
        assert promoted.status == "confirmed"
        assert engine.get_awaiting_confirmation() == ""

    def test_resolve_pending_rejects_foreign_contact_vars(self):
        from voice_platform.flow.nodes import _resolve_node_pending_vars

        visit_cfg = {"variables_to_extract": ["service_requested", "is_new_patient"]}
        pending = _resolve_node_pending_vars(
            visit_cfg,
            ["patient_name", "caller_phone", "caller_email"],
        )
        assert pending == ["service_requested", "is_new_patient"]

    def test_exact_spoken_readback_skips_llm(self):
        from voice_platform.flow.nodes import _exact_spoken_readback

        spoken = _exact_spoken_readback(
            '[INSTRUCTION]\nQUESTION:\n- Say exactly: I heard patient1 at example dot com. '
            'Is that correct? Say nothing else.'
        )
        assert spoken == (
            "I heard patient1 at example dot com. Is that correct?"
        )

class TestDentistNoPreference:
    @pytest.mark.parametrize(
        "value",
        [
            "No. I don't.",
            "No I don't",
            "No. I don't have any preference",
            "No. I don't have a preferred dentist.",
            "I don't have a preference",
            "no",
        ],
    )
    def test_normalize_short_no_to_any_dentist(self, value):
        assert normalize_variable("preferred_dentist", value) == "any available dentist"


class TestThursdayOnePmDateParse:
    def test_weekday_inside_datetime_phrase(self):
        result = _normalize_date("Thursday, 1PM")
        assert result is not None
        parsed = datetime.strptime(result, "%Y-%m-%d")
        assert parsed.weekday() == 3  # Thursday

    def test_weekday_at_time_phrase(self):
        result = _normalize_date("book it for Thursday at 1")
        assert result is not None
        assert datetime.strptime(result, "%Y-%m-%d").weekday() == 3


class TestStableMissingInputRetryScope:
    @pytest.mark.asyncio
    async def test_scope_key_stable_when_missing_fields_change(self, monkeypatch):
        """date+time miss then date-only miss must share one retry counter."""
        handlers = create_node_handlers()
        action_handler = handlers["action"]
        monkeypatch.setattr(
            "voice_platform.flow.nodes._extract_variables",
            AsyncMock(side_effect=RuntimeError("should not extract")),
        )

        def _state(missing_via_vars: dict, prior_counts=None):
            return {
                "current_node": "action_2",
                "nodes_by_id": {
                    "action_2": {
                        "id": "action_2",
                        "data": {
                            "label": "Check Availability",
                            "config": {
                                "integration_type": "google_calendar",
                                "action": "check_availability",
                                "required_inputs": [
                                    "preferred_date",
                                    "preferred_time",
                                    "patient_name",
                                ],
                                "params": {
                                    "date": "{{preferred_date}}",
                                    "time": "{{preferred_time}}",
                                },
                            },
                        },
                    }
                },
                "extracted_vars": missing_via_vars,
                "result": {},
                "last_result": {},
                "transcript": [],
                "_slot_retry_counts": prior_counts or {},
            }

        config = {
            "configurable": {
                "agent": SimpleNamespace(id=14),
                "user_id": 1,
            }
        }

        # First miss: both date and time
        r1 = await action_handler(
            _state({"patient_name": "Alex"}),
            config,
        )
        assert r1["_active_retry_scope"] == "action_2:missing_input"
        assert "preferred_date" in r1["_slot_retry_counts"]["action_2:missing_input"]["missing_inputs"]
        assert "preferred_time" in r1["_slot_retry_counts"]["action_2:missing_input"]["missing_inputs"]

        # Simulate condition bumping count to 1, then second miss with only date
        prior = {
            "action_2:missing_input": {
                "count": 1,
                "owner": "action_2",
                "mode": "active_action",
                "missing_inputs": ["preferred_date", "preferred_time"],
            }
        }
        r2 = await action_handler(
            _state(
                {"patient_name": "Alex", "preferred_time": "13:00"},
                prior_counts=prior,
            ),
            config,
        )
        assert r2["_active_retry_scope"] == "action_2:missing_input"
        # Count must NOT reset to 0 when missing set shrinks
        assert r2["_slot_retry_counts"]["action_2:missing_input"]["count"] == 1
        assert r2["_slot_retry_counts"]["action_2:missing_input"]["missing_inputs"] == [
            "preferred_date"
        ]
        # Old field-suffixed keys must not be created
        assert not any(
            k.startswith("action_2:missing_input:")
            for k in r2["_slot_retry_counts"]
        )


class TestNegativeDoesNotDiscardForeignEmail:
    @pytest.mark.asyncio
    async def test_dentist_no_does_not_wipe_email_candidate(self, monkeypatch):
        """Dentist short-no must not wipe email; enter-promote or scoped discard."""
        node = {
            "id": "conversation_dentist",
            "type": "conversation",
            "data": {
                "label": "Dentist Preference",
                "config": {
                    "prompt": "Ask preferred dentist.",
                    "variables_to_extract": ["preferred_dentist"],
                },
            },
        }
        state = make_initial_state(
            user_id=1,
            agent_id=14,
            nodes_by_id={"conversation_dentist": node},
            outgoing={"conversation_dentist": []},
        )
        engine = SlotEngine(["preferred_dentist", "caller_email"], {})
        engine.fill_candidate(
            "caller_email", "alex@example.com", "alex@example.com"
        )
        engine.set_awaiting_confirmation("caller_email")
        state.update({
            "current_node": "conversation_dentist",
            "extracted_vars": {},
            "pending_variables_to_extract": ["preferred_dentist"],
            "_conversation_phase": "wait",
            "_slots": engine.to_dict(),
            "_slot_engine": engine.to_engine_dict(),
            "last_result": {"response": "Do you have a preferred dentist?"},
            "result": {"response": "Do you have a preferred dentist?"},
            "transcript": "Agent: Do you have a preferred dentist?",
        })

        monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "No. I don't.")
        monkeypatch.setattr(
            flow_nodes, "_extract_variables", AsyncMock(return_value={})
        )

        result = await create_node_handlers()["conversation"](
            state,
            {
                "configurable": {
                    "event_callback": AsyncMock(),
                    "user_id": 1,
                    "agent": SimpleNamespace(id=14, prompt="You are a receptionist."),
                }
            },
        )

        slots = result.get("_slots") or {}
        email_slot = slots.get("caller_email") or {}
        still_has_email = bool(
            email_slot.get("candidate_value")
            or email_slot.get("value")
            or email_slot.get("normalized_value")
        )
        assert still_has_email, "dentist short-no must not wipe pending email"

        dentist = (result.get("extracted_vars") or {}).get("preferred_dentist")
        if not dentist:
            dslot = slots.get("preferred_dentist") or {}
            dentist = dslot.get("normalized_value")
        assert dentist == "any available dentist"
