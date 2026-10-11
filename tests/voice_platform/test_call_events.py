"""Tests for call event workflow trigger matching helpers."""

from types import SimpleNamespace

from voice_platform.events.call_events import PersistentEventsManager


class TestCallEventTriggerHelpers:
    def test_parse_trigger_phrases_handles_multiple_storage_formats(self):
        assert PersistentEventsManager._parse_trigger_phrases('["hello", " hi ", "hello"]') == [
            "hello",
            "hi",
        ]
        assert PersistentEventsManager._parse_trigger_phrases("billing issue, schedule callback") == [
            "billing issue",
            "schedule callback",
        ]
        assert PersistentEventsManager._parse_trigger_phrases(["A", "a", " B "]) == ["A", "B"]

    def test_workflow_trigger_matches_with_punctuation_normalization(self):
        transcript = "Hello! I'd like to schedule, an appointment please."
        triggers = ["schedule appointment"]
        assert PersistentEventsManager._workflow_trigger_matches(transcript, triggers) is True

    def test_workflow_trigger_match_requires_phrase_boundary(self):
        transcript = "I need support for catfood subscriptions"
        triggers = ["cat"]
        assert PersistentEventsManager._workflow_trigger_matches(transcript, triggers) is False

    def test_in_call_graph_is_not_replayed_after_transcript_completion(self):
        graph = '{"nodes":[{"id":"trigger"}],"edges":[]}'
        workflow = SimpleNamespace(graph_json=graph, agent_id=7)
        call_log = SimpleNamespace(agent_id=7)
        agent = SimpleNamespace(
            mode="conversational_flow",
            graph_json='{"edges": [], "nodes": [{"id": "trigger"}]}',
        )

        assert PersistentEventsManager._executes_inside_call(workflow, call_log, agent) is True

    def test_different_workflow_graph_is_still_eligible_for_post_call_execution(self):
        workflow = SimpleNamespace(
            graph_json='{"nodes":[{"id":"workflow-graph"}],"edges":[]}',
            agent_id=7,
        )
        call_log = SimpleNamespace(agent_id=7)
        agent = SimpleNamespace(
            mode="conversational_flow",
            graph_json='{"nodes":[{"id":"agent-graph"}],"edges":[]}',
        )

        assert PersistentEventsManager._executes_inside_call(workflow, call_log, agent) is False
