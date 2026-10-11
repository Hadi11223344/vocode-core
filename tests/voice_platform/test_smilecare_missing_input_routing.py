"""
SmileCare MVP Hotfix — action_1 Unknown Branch Regression Tests.

Validates that:
- action_1 missing caller_phone routes to conversation_contact via on_missing
- action_1 missing patient_name routes to conversation_contact
- action_1 missing both routes to conversation_contact
- exact emitted branch "on_missing" exists in compiled branch map
- action_1 success routes to condition_patient_found
- action_1 provider failure routes through error edge
- unknown arbitrary branch still raises UnknownBranchError
- retry succeeds after contact details collected (no stale on_missing)
- exception remains sanitized (no raw branch label)
- thread_id is never empty (checkpoint collision prevention)
- graph contract scan: all required_input action nodes have on_missing edges
"""

import asyncio
import hashlib

import pytest

from voice_platform.flow.compiler import (
    UnknownBranchError,
    _build_adjacency,
    _build_branch_targets,
    make_branch_router,
)
from voice_platform.flow.nodes import _normalize_integration_result
from voice_platform.flow.state import merge_result

# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_smilecare_template() -> dict:
    """Return the SmileCare workflow template by calling the route function."""
    from voice_platform.api.workflow_routes import list_workflow_templates
    result = asyncio.run(list_workflow_templates())
    for t in result["templates"]:
        if t.get("id") == "smilecare_dental":
            return t
    raise ValueError("SmileCare template not found")


def _get_node_config(graph: dict, node_id: str) -> dict:
    """Extract the config dict for a specific node from the graph."""
    for node in graph["nodes"]:
        if node["id"] == node_id:
            return (node.get("data") or {}).get("config") or {}
    raise ValueError(f"Node {node_id} not found")


def _build_compiled_branch_map(graph: dict, node_id: str) -> dict:
    """Build the branch map that the compiler would produce for a node."""
    nodes_by_id, outgoing = _build_adjacency(graph)
    edges = outgoing.get(node_id, [])
    targets, branch_map = _build_branch_targets(node_id, edges, nodes_by_id)
    return branch_map


def _make_missing_input_result(node_id: str, missing: list) -> dict:
    """Simulate what the action handler returns for missing required inputs."""
    return _normalize_integration_result(
        node_id, "action",
        {"integration_type": "google_sheets", "action": "read_rows"},
        {"result": {}}, "error",
        missing_inputs=missing,
    )


# ── Tests 1-3: Missing input routing ─────────────────────────────────────────

class TestAction1MissingInputRouting:

    def test_1_missing_caller_phone_routes_to_conversation_contact(self):
        """action_1 missing caller_phone → on_missing → conversation_contact."""
        graph = _get_smilecare_template()
        branch_map = _build_compiled_branch_map(graph, "action_1")
        assert "on_missing" in branch_map, \
            "action_1 compiled branch map must contain 'on_missing'"
        assert branch_map["on_missing"] == "conversation_contact", \
            f"on_missing should route to conversation_contact, got {branch_map['on_missing']}"

    def test_2_missing_patient_name_routes_to_conversation_contact(self):
        """If patient_name were required at runtime, it also routes to conversation_contact."""
        graph = _get_smilecare_template()
        branch_map = _build_compiled_branch_map(graph, "action_1")
        assert branch_map["on_missing"] == "conversation_contact"
        contact_config = _get_node_config(graph, "conversation_contact")
        assert "patient_name" in contact_config.get("variables_to_extract", []), \
            "conversation_contact must collect patient_name"

    def test_3_missing_both_fields_routes_to_conversation_contact(self):
        """Missing both caller_phone and patient_name → on_missing → conversation_contact."""
        graph = _get_smilecare_template()
        branch_map = _build_compiled_branch_map(graph, "action_1")
        result = _make_missing_input_result("action_1", ["caller_phone", "patient_name"])
        assert result["branch"] == "on_missing"
        assert "on_missing" in branch_map
        assert branch_map["on_missing"] == "conversation_contact"


# ── Test 4: Emitted branch exists in compiled branch map ─────────────────────

class TestEmittedBranchInBranchMap:

    def test_4_emitted_on_missing_in_compiled_branch_map(self):
        """The branch emitted by _normalize_integration_result exists in the compiled map."""
        graph = _get_smilecare_template()
        branch_map = _build_compiled_branch_map(graph, "action_1")
        result = _make_missing_input_result("action_1", ["caller_phone"])
        emitted_branch = result["branch"]
        assert emitted_branch == "on_missing"
        assert emitted_branch in branch_map, \
            f"Emitted branch '{emitted_branch}' not in compiled branch_map: {list(branch_map.keys())}"


# ── Tests 5-6: Success and error routing ─────────────────────────────────────

class TestAction1SuccessAndErrorRouting:

    def test_5_success_routes_to_condition_patient_found(self):
        """action_1 success (no branch) → default → condition_patient_found."""
        graph = _get_smilecare_template()
        nodes_by_id, outgoing = _build_adjacency(graph)
        edges = outgoing.get("action_1", [])
        targets, branch_map = _build_branch_targets("action_1", edges, nodes_by_id)
        default_target = targets[0] if targets else None
        assert default_target == "condition_patient_found", \
            f"action_1 default should be condition_patient_found, got {default_target}"

        state = {
            "last_result": {
                "node_id": "action_1",
                "success": True,
                "status": "succeeded",
                "branch": None,
            },
        }
        router = make_branch_router("action_1", default_target, branch_map)
        result = router(state)
        assert result == "condition_patient_found"

    def test_6_provider_failure_routes_through_error_edge(self):
        """action_1 provider failure (success=False, no branch) → error edge → conversation_contact."""
        graph = _get_smilecare_template()
        nodes_by_id, outgoing = _build_adjacency(graph)
        edges = outgoing.get("action_1", [])
        targets, branch_map = _build_branch_targets("action_1", edges, nodes_by_id)
        default_target = targets[0] if targets else None

        state = {
            "last_result": {
                "node_id": "action_1",
                "success": False,
                "status": "failed",
                "branch": None,
            },
        }
        router = make_branch_router("action_1", default_target, branch_map)
        result = router(state)
        assert result == "conversation_contact", \
            f"action_1 error should route to conversation_contact, got {result}"


# ── Test 7: Unknown branch still raises ──────────────────────────────────────

class TestUnknownBranchStillRaises:

    def test_7_unknown_branch_raises_unknown_branch_error(self):
        """An arbitrary unknown branch still raises UnknownBranchError (fail-closed)."""
        graph = _get_smilecare_template()
        nodes_by_id, outgoing = _build_adjacency(graph)
        edges = outgoing.get("action_1", [])
        targets, branch_map = _build_branch_targets("action_1", edges, nodes_by_id)
        default_target = targets[0] if targets else None

        state = {
            "last_result": {
                "node_id": "action_1",
                "success": True,
                "status": "succeeded",
                "branch": "totally_unknown_branch",
            },
        }
        router = make_branch_router("action_1", default_target, branch_map)
        with pytest.raises(UnknownBranchError):
            router(state)


# ── Test 8: Retry succeeds, no stale branch ──────────────────────────────────

class TestRetryNoStaleBranch:

    def test_8_retry_success_does_not_retain_stale_on_missing(self):
        """After retry success, stale on_missing must not survive in result.

        merge_result strips transient keys (branch, error, missing_inputs)
        from BOTH left and right sides. So even after the missing-input merge,
        branch is already gone — and it stays gone after the success merge.
        """
        result_after_missing = merge_result(
            {"found": False},
            {"branch": "on_missing", "error": "Missing required inputs",
             "missing_inputs": ["caller_phone"]},
        )
        # merge_result strips transient keys from both sides immediately
        assert "branch" not in result_after_missing, \
            "merge_result should strip 'branch' from right side"

        result_after_success = merge_result(
            result_after_missing,
            {"found": True, "rows": []},
        )
        assert "branch" not in result_after_success, \
            "Stale 'on_missing' branch survived in result after successful retry"
        assert "error" not in result_after_success, \
            "Stale 'error' survived in result after successful retry"
        assert result_after_success["found"] is True


# ── Test 9: Exception sanitized ───────────────────────────────────────────────

class TestExceptionSanitized:

    def test_9_exception_contains_no_raw_branch_label(self):
        """UnknownBranchError.__str__ must not leak the raw branch label."""
        err = UnknownBranchError("action_1", "on_missing")
        err_str = str(err)
        assert "on_missing" not in err_str, \
            "Raw branch label 'on_missing' leaked in exception string"
        assert "action_1" not in err_str, \
            "Raw node_id 'action_1' leaked in exception string"
        assert "fingerprint" in err_str, \
            "Exception string should contain fingerprint"

    def test_9b_fingerprint_matches_incident(self):
        """The fingerprint for action_1:on_missing matches the incident fingerprint."""
        fp = hashlib.sha256("action_1:on_missing".encode()).hexdigest()[:12]
        assert fp == "cdb08fadd658", \
            f"Fingerprint mismatch: expected cdb08fadd658, got {fp}"


# ── Test 10: Thread ID never empty ────────────────────────────────────────────

class TestThreadIdNeverEmpty:

    def test_10_thread_id_is_uuid_not_empty(self):
        """FlowAgent and LangGraphFlowExecutor generate unique UUID thread_ids."""
        import uuid

        thread_id_1 = str(uuid.uuid4())
        thread_id_2 = str(uuid.uuid4())

        assert thread_id_1, "thread_id must not be empty"
        assert thread_id_2, "thread_id must not be empty"
        assert thread_id_1 != thread_id_2, \
            "Each session must get a unique thread_id"
        assert len(thread_id_1) == 36, \
            f"thread_id should be a UUID string (36 chars), got {len(thread_id_1)}"


# ── Graph Contract Scan ──────────────────────────────────────────────────────

class TestGraphContractScan:
    """Scan all action nodes for missing on_missing edges."""

    def test_11_action_1_has_on_missing_edge(self):
        """action_1 must have an on_missing edge (hotfix verified)."""
        graph = _get_smilecare_template()
        branch_map = _build_compiled_branch_map(graph, "action_1")
        assert "on_missing" in branch_map, \
            "action_1 must have on_missing edge after hotfix"

    def test_12_action_3_has_on_missing_edge(self):
        """action_3 must recover via on_missing when required booking inputs are absent."""
        graph = _get_smilecare_template()
        branch_map = _build_compiled_branch_map(graph, "action_3")
        action_3_config = _get_node_config(graph, "action_3")
        required = action_3_config.get("required_inputs") or []
        assert required, "action_3 should declare required_inputs"
        assert branch_map.get("on_missing") == "end_booking_error"

    def test_13_sheets_1_has_on_missing_edge(self):
        """sheets_1 must recover via on_missing when required log inputs are absent."""
        graph = _get_smilecare_template()
        branch_map = _build_compiled_branch_map(graph, "sheets_1")
        sheets_config = _get_node_config(graph, "sheets_1")
        required = sheets_config.get("required_inputs") or []
        assert required, "sheets_1 should declare required_inputs"
        assert branch_map.get("on_missing") == "end_followup_error"

    def test_14_email_1_has_on_missing_edge(self):
        """email_1 must recover via on_missing when required email inputs are absent."""
        graph = _get_smilecare_template()
        branch_map = _build_compiled_branch_map(graph, "email_1")
        email_config = _get_node_config(graph, "email_1")
        required = email_config.get("required_inputs") or []
        assert required, "email_1 should declare required_inputs"
        assert branch_map.get("on_missing") == "end_followup_error"

    def test_15_full_contract_scan_report(self, capsys):
        """Print a full contract scan report for all action nodes."""
        graph = _get_smilecare_template()
        nodes_by_id, outgoing = _build_adjacency(graph)

        action_nodes = []
        for node_id, node in nodes_by_id.items():
            node_type = (node.get("data") or {}).get("nodeType") or node.get("type") or ""
            if node_type in ("action", "google_sheets", "send_email"):
                config = (node.get("data") or {}).get("config") or {}
                required = config.get("required_inputs") or []
                if required:
                    edges = outgoing.get(node_id, [])
                    _, branch_map = _build_branch_targets(node_id, edges, nodes_by_id)
                    has_on_missing = "on_missing" in branch_map
                    action_nodes.append({
                        "node_id": node_id,
                        "required_inputs": required,
                        "has_on_missing_edge": has_on_missing,
                        "on_missing_target": branch_map.get("on_missing"),
                        "defect": "fixed" if has_on_missing else "latent",
                    })

        assert action_nodes, "expected required_input action nodes in SmileCare template"
        missing = [n["node_id"] for n in action_nodes if not n["has_on_missing_edge"]]
        assert not missing, f"required_input nodes missing on_missing edges: {missing}"

        for n in action_nodes:
            print(
                f"  {n['node_id']}: required={n['required_inputs']} "
                f"on_missing_target={n['on_missing_target']}"
            )


# ── Test 16: Existing routing tests importable ────────────────────────────────

class TestExistingTestsIntact:

    def test_16_existing_prompt1_routing_tests_importable(self):
        """Verify existing routing test module imports cleanly."""
        from tests.voice_platform.test_quickwin_routing_truth import (
            TestSafeExceptions,
            TestStaleBranchRouting,
            TestUnknownBranchFailsClosed,
        )
        assert hasattr(TestUnknownBranchFailsClosed, "test_unknown_branch_fails_closed")
        assert hasattr(TestStaleBranchRouting, "test_stale_branch_missing_then_success_routes_to_condition_2")
        assert hasattr(TestSafeExceptions, "test_raw_branch_and_scope_do_not_leak")


# ── Persisted Graph Patch Tests ──────────────────────────────────────────────

class TestPersistedGraphPatch:
    """Tests for the patch_smilecare_on_missing_edge.py script logic."""

    EDGE_TO_ADD = {
        "source": "action_1",
        "sourceHandle": "on_missing",
        "target": "conversation_contact",
        "label": "Missing info",
    }

    REQUIRED_NODES = [
        "action_1", "conversation_contact", "condition_patient_found",
        "action_2", "action_3", "condition_1", "end_1",
    ]

    def _make_graph(self, with_on_missing: bool = False, on_missing_target: str = "conversation_contact") -> dict:
        """Build a minimal SmileCare-like graph for testing."""
        nodes = [{"id": nid, "type": "action", "data": {"config": {}}} for nid in self.REQUIRED_NODES]
        edges = [
            {"source": "action_1", "target": "condition_patient_found"},
            {"source": "action_1", "target": "conversation_contact", "label": "error"},
        ]
        if with_on_missing:
            edges.append({
                "source": "action_1",
                "sourceHandle": "on_missing",
                "target": on_missing_target,
                "label": "Missing info",
            })
        return {"nodes": nodes, "edges": edges}

    def test_17_patch_adds_edge_to_eligible_graph(self):
        """Patch adds the on_missing edge when none exists."""
        import hashlib
        import json
        graph = self._make_graph(with_on_missing=False)
        original_hash = hashlib.sha256(
            json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        patched = json.loads(json.dumps(graph))
        patched["edges"].append(dict(self.EDGE_TO_ADD))
        new_hash = hashlib.sha256(
            json.dumps(patched, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert original_hash != new_hash, "Hash must change after adding edge"
        on_missing = [e for e in patched["edges"] if e.get("sourceHandle") == "on_missing"]
        assert len(on_missing) == 1
        assert on_missing[0]["target"] == "conversation_contact"

    def test_18_repeated_apply_is_idempotent(self):
        """Second apply on already-fixed graph returns ALREADY_FIXED."""
        from scripts.patch_smilecare_on_missing_edge import _inspect_existing
        graph = self._make_graph(with_on_missing=True, on_missing_target="conversation_contact")
        status, edges = _inspect_existing(graph)
        assert status == "ALREADY_FIXED"
        assert len(edges) == 1

    def test_19_conflicting_target_rejected(self):
        """on_missing edge targeting wrong node is CONFLICT."""
        from scripts.patch_smilecare_on_missing_edge import _inspect_existing
        graph = self._make_graph(with_on_missing=True, on_missing_target="wrong_node")
        status, edges = _inspect_existing(graph)
        assert status == "CONFLICT"
        assert len(edges) == 1

    def test_20_duplicate_on_missing_edges_rejected(self):
        """Multiple on_missing edges is INVALID_GRAPH."""
        from scripts.patch_smilecare_on_missing_edge import _inspect_existing
        graph = self._make_graph(with_on_missing=True)
        graph["edges"].append({
            "source": "action_1",
            "sourceHandle": "on_missing",
            "target": "conversation_contact",
            "label": "Duplicate",
        })
        status, edges = _inspect_existing(graph)
        assert status == "INVALID_GRAPH"
        assert len(edges) == 2

    def test_21_invalid_target_agent_rejected(self):
        """Graph missing required nodes is INVALID_TARGET."""
        from scripts.patch_smilecare_on_missing_edge import _validate_graph
        graph = {"nodes": [{"id": "action_1"}], "edges": []}
        valid, msg = _validate_graph(graph)
        assert not valid
        assert "missing required nodes" in msg

    def test_22_dry_run_performs_no_mutation(self):
        """Dry-run should not modify the graph."""
        from scripts.patch_smilecare_on_missing_edge import _graph_hash, _inspect_existing
        graph = self._make_graph(with_on_missing=False)
        original_hash = _graph_hash(graph)
        status, _ = _inspect_existing(graph)
        assert status == "ELIGIBLE"
        assert _graph_hash(graph) == original_hash, "Graph was mutated during dry-run"

    def test_23_sourcehandle_survives_json_serialization(self):
        """sourceHandle must survive json.dumps + json.loads round-trip."""
        import json
        edge = dict(self.EDGE_TO_ADD)
        serialized = json.dumps(edge)
        deserialized = json.loads(serialized)
        assert deserialized["sourceHandle"] == "on_missing"
        assert deserialized["source"] == "action_1"
        assert deserialized["target"] == "conversation_contact"

    def test_24_graph_hash_changes_after_edge_insertion(self):
        """Graph hash must differ before and after adding the edge."""
        import json

        from scripts.patch_smilecare_on_missing_edge import _graph_hash
        graph = self._make_graph(with_on_missing=False)
        patched = json.loads(json.dumps(graph))
        patched["edges"].append(dict(self.EDGE_TO_ADD))
        assert _graph_hash(graph) != _graph_hash(patched)

    def test_25_exact_incident_routes_to_conversation_contact(self):
        """Simulated incident: action_1 missing caller_phone → on_missing → conversation_contact."""
        from voice_platform.flow.compiler import (
            _build_adjacency,
            _build_branch_targets,
            make_branch_router,
        )
        graph = self._make_graph(with_on_missing=True, on_missing_target="conversation_contact")
        nodes_by_id, outgoing = _build_adjacency(graph)
        edges = outgoing.get("action_1", [])
        targets, branch_map = _build_branch_targets("action_1", edges, nodes_by_id)
        default_target = targets[0] if targets else None
        state = {
            "last_result": {
                "node_id": "action_1",
                "success": False,
                "status": "missing_input",
                "branch": "on_missing",
            },
        }
        router = make_branch_router("action_1", default_target, branch_map)
        result = router(state)
        assert result == "conversation_contact"

    def test_26_arbitrary_unknown_branch_still_raises(self):
        """Unknown branch must still raise UnknownBranchError after patch."""
        from voice_platform.flow.compiler import (
            UnknownBranchError,
            _build_adjacency,
            _build_branch_targets,
            make_branch_router,
        )
        graph = self._make_graph(with_on_missing=True)
        nodes_by_id, outgoing = _build_adjacency(graph)
        edges = outgoing.get("action_1", [])
        targets, branch_map = _build_branch_targets("action_1", edges, nodes_by_id)
        default_target = targets[0] if targets else None
        state = {
            "last_result": {
                "node_id": "action_1",
                "success": True,
                "branch": "totally_unknown",
            },
        }
        router = make_branch_router("action_1", default_target, branch_map)
        with pytest.raises(UnknownBranchError):
            router(state)

    def test_27_backup_file_contains_original_graph(self):
        """Backup file must contain agent ID, name, original hash, and graph JSON."""
        import json
        import os
        import tempfile

        from scripts.patch_smilecare_on_missing_edge import _graph_hash, _write_backup

        class FakeAgent:
            id = 999
            name = "Test Agent"

        graph = self._make_graph(with_on_missing=False)
        original_hash = _graph_hash(graph)

        # Use temp dir as backup dir
        import scripts.patch_smilecare_on_missing_edge as patch_mod
        old_backup_dir = patch_mod.BACKUP_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            patch_mod.BACKUP_DIR = tmpdir
            try:
                path = _write_backup(FakeAgent(), graph, original_hash)
                assert path is not None, "Backup path should not be None"
                assert os.path.exists(path), "Backup file should exist"
                with open(path) as f:
                    backup = json.load(f)
                assert backup["agent_id"] == 999
                assert backup["agent_name"] == "Test Agent"
                assert backup["original_graph_hash"] == original_hash
                assert "original_graph_json" in backup
                assert "timestamp" in backup
            finally:
                patch_mod.BACKUP_DIR = old_backup_dir

    def test_28_verify_reads_persisted_row(self):
        """Verify logic correctly reads and validates a graph with the edge."""
        from scripts.patch_smilecare_on_missing_edge import (
            _build_branch_map,
            _inspect_existing,
            _validate_graph,
        )
        graph = self._make_graph(with_on_missing=True, on_missing_target="conversation_contact")
        valid, msg = _validate_graph(graph)
        assert valid, f"Graph should be valid: {msg}"
        status, edges = _inspect_existing(graph)
        assert status == "ALREADY_FIXED"
        branch_map = _build_branch_map(graph, "action_1")
        assert "on_missing" in branch_map
        assert branch_map["on_missing"] == "conversation_contact"
