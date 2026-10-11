import json
import re
from copy import deepcopy
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from voice_platform.agent_templates import get_template
from voice_platform.api.workflow_routes import _validate_graph, list_workflow_templates
from voice_platform.database import Agent
from voice_platform.flow.compiler import compile_flow, create_initial_state, get_cycle_warnings
from voice_platform.flow.nodes import create_node_handlers
from voice_platform.integrations.executor import WorkflowExecutor
from voice_platform.runtime.flow.conditions import ConditionEvaluator


DEMO_TEMPLATE_IDS = {
    "smilecare_dental": "smilecare",
    "umt_admission": "university",
    "umt_outreach": "umt_outreach",
}

SYSTEM_VARIABLES = {
    "caller_name",
    "caller_phone",
    "current_date",
    "current_time",
    "call_date",
    "call_time",
    "now",
    "transcript",
    "result",
    "last_result",
}


def _cyclic_components(node_ids, edges):
    adjacency = {node_id: [] for node_id in node_ids}
    for edge in edges:
        adjacency[edge["source"]].append(edge["target"])

    next_index = 0
    indices = {}
    low_links = {}
    stack = []
    on_stack = set()
    components = []

    def visit(node_id):
        nonlocal next_index
        indices[node_id] = next_index
        low_links[node_id] = next_index
        next_index += 1
        stack.append(node_id)
        on_stack.add(node_id)

        for target_id in adjacency[node_id]:
            if target_id not in indices:
                visit(target_id)
                low_links[node_id] = min(low_links[node_id], low_links[target_id])
            elif target_id in on_stack:
                low_links[node_id] = min(low_links[node_id], indices[target_id])

        if low_links[node_id] != indices[node_id]:
            return
        component = []
        while stack:
            member_id = stack.pop()
            on_stack.remove(member_id)
            component.append(member_id)
            if member_id == node_id:
                break
        if len(component) > 1 or node_id in adjacency[node_id]:
            components.append(component)

    for node_id in node_ids:
        if node_id not in indices:
            visit(node_id)
    return components


@pytest_asyncio.fixture(scope="module")
async def all_workflow_templates():
    payload = await list_workflow_templates()
    return {template["id"]: template for template in payload["templates"]}


@pytest.fixture(scope="module")
def demo_templates(all_workflow_templates):
    return {
        template_id: all_workflow_templates[template_id]
        for template_id in DEMO_TEMPLATE_IDS
    }


def test_catalog_templates_have_executable_branches_and_canvas_geometry(all_workflow_templates):
    assert len(all_workflow_templates) == 33
    for template_id, template in all_workflow_templates.items():
        graph = {"nodes": deepcopy(template["nodes"]), "edges": deepcopy(template["edges"])}
        nodes = {node["id"]: node for node in graph["nodes"]}
        outgoing = {node_id: [] for node_id in nodes}
        incoming = {node_id: [] for node_id in nodes}
        for edge in graph["edges"]:
            outgoing[edge["source"]].append(edge)
            incoming[edge["target"]].append(edge)

        triggers = [node for node in graph["nodes"] if node["type"] == "trigger"]
        assert len(triggers) == 1, template_id
        reachable = set()
        stack = [triggers[0]["id"]]
        while stack:
            node_id = stack.pop()
            if node_id in reachable:
                continue
            reachable.add(node_id)
            stack.extend(edge["target"] for edge in outgoing[node_id])
        assert reachable == set(nodes), template_id

        terminals = {
            node_id
            for node_id, node in nodes.items()
            if node["type"] in {"end", "end_call"}
            or (node["type"] == "transfer_call" and not outgoing[node_id])
        }
        assert terminals, template_id
        can_reach_terminal = set(terminals)
        stack = list(terminals)
        while stack:
            node_id = stack.pop()
            for edge in incoming[node_id]:
                if edge["source"] not in can_reach_terminal:
                    can_reach_terminal.add(edge["source"])
                    stack.append(edge["source"])
        assert reachable <= can_reach_terminal, template_id

        for node_id, node in nodes.items():
            if node["type"] == "condition":
                branches = outgoing[node_id]
                assert len(branches) == 2, (template_id, node_id)
                assert {edge.get("sourceHandle") for edge in branches} == {"yes", "no"}, (template_id, node_id)

        for component in _cyclic_components(nodes, graph["edges"]):
            is_bounded = any(nodes[node_id]["type"] == "slot_validator" for node_id in component)
            is_bounded = is_bounded or any(
                nodes[node_id]["type"] == "condition"
                and "_slot_retry_count" in str(nodes[node_id]["data"]["config"].get("expression", ""))
                for node_id in component
            )
            assert is_bounded, (template_id, component)

        for index, left in enumerate(graph["nodes"]):
            for right in graph["nodes"][index + 1:]:
                assert not (
                    abs(left["position"]["x"] - right["position"]["x"]) < 240
                    and abs(left["position"]["y"] - right["position"]["y"]) < 100
                ), (template_id, left["id"], right["id"])

        assert compile_flow(graph) is not None, template_id


def test_all_demo_templates_are_linked_to_existing_agent_templates(demo_templates):
    assert set(demo_templates) == set(DEMO_TEMPLATE_IDS)
    for workflow_id, agent_template_id in DEMO_TEMPLATE_IDS.items():
        workflow_template = demo_templates[workflow_id]
        agent_template = get_template(agent_template_id)
        assert workflow_template["agent_template_id"] == agent_template_id
        assert workflow_template["trigger_phrases"]
        assert agent_template is not None
        assert agent_template.mode == "single_prompt"


@pytest.mark.parametrize("template_id", list(DEMO_TEMPLATE_IDS))
def test_demo_graph_is_structurally_valid_and_compiles(demo_templates, template_id):
    template = demo_templates[template_id]
    graph = {"nodes": deepcopy(template["nodes"]), "edges": deepcopy(template["edges"])}
    node_ids = [node["id"] for node in graph["nodes"]]

    assert len(node_ids) == len(set(node_ids))
    assert _validate_graph(graph) == []
    assert get_cycle_warnings(graph)[0] == []
    assert compile_flow(graph) is not None


@pytest.mark.parametrize("template_id", list(DEMO_TEMPLATE_IDS))
def test_demo_graph_node_and_template_contracts(demo_templates, template_id):
    template = demo_templates[template_id]
    nodes = template["nodes"]
    node_ids = {node["id"] for node in nodes}
    produced_variables = set(SYSTEM_VARIABLES)

    for node in nodes:
        config = node.get("data", {}).get("config", {})
        if node["type"] == "conversation":
            assert str(config.get("prompt", "")).strip(), node["id"]
            variables = config.get("variables_to_extract")
            assert isinstance(variables, list) and variables, node["id"]
            produced_variables.update(variables)
        elif node["type"] == "action":
            for field in ("integration_type", "action", "params", "required_inputs"):
                assert field in config, f"{node['id']} is missing {field}"
        elif node["type"] == "condition":
            expression = str(config.get("expression", "")).strip()
            assert expression
            assert any(operator in expression for operator in ("==", "!=", ">=", "<=", ">", "<", " contains ", "not_empty"))

    for edge in template["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids

    referenced_variables = set()
    for node in nodes:
        config_text = json.dumps(node.get("data", {}).get("config", {}))
        referenced_variables.update(
            match.strip().split(".", 1)[0]
            for match in re.findall(r"\{\{([^}]+)\}\}", config_text)
        )
    assert referenced_variables <= produced_variables


def test_umt_prompts_require_knowledge_grounding_and_scholarship_extraction(demo_templates):
    for template_id in ("umt_admission", "umt_outreach"):
        conversations = [node for node in demo_templates[template_id]["nodes"] if node["type"] == "conversation"]
        prompts = " ".join(node["data"]["config"]["prompt"].lower() for node in conversations)
        extracted = {
            variable
            for node in conversations
            for variable in node["data"]["config"]["variables_to_extract"]
        }
        assert "knowledge base" in prompts
        assert "scholarship_tier" in extracted


def test_smilecare_uses_conversation_owned_slot_retries_without_collector_loops(demo_templates):
    template = demo_templates["smilecare_dental"]
    node_ids = {node["id"] for node in template["nodes"]}

    assert all(node["type"] != "slot_validator" for node in template["nodes"])
    assert not any(node_id.startswith("collect_") for node_id in node_ids)
    for node in template["nodes"]:
        if node["type"] == "conversation":
            variables = node["data"]["config"].get("variables_to_extract", [])
            assert len(variables) <= 3, node["id"]


def test_smilecare_canvas_has_distinct_condition_handles_and_no_overlaps(demo_templates):
    template = demo_templates["smilecare_dental"]
    node_types = {node["id"]: node["type"] for node in template["nodes"]}
    condition_edges = {}
    for edge in template["edges"]:
        if node_types.get(edge["source"]) == "condition":
            condition_edges.setdefault(edge["source"], []).append(edge)
    for node_id, branches in condition_edges.items():
        assert {edge.get("sourceHandle") for edge in branches} == {"yes", "no"}, node_id

    for index, left in enumerate(template["nodes"]):
        for right in template["nodes"][index + 1:]:
            assert not (
                abs(left["position"]["x"] - right["position"]["x"]) < 240
                and abs(left["position"]["y"] - right["position"]["y"]) < 100
            ), (left["id"], right["id"])


def test_smilecare_patient_sheet_read_and_write_use_the_same_schema(demo_templates):
    """Template-default schema check (list_workflow_templates smilecare_dental).

    Active persisted Agent.graph may use a different worksheet tab (e.g. Sheet1)
    — validate that separately against the demo agent record, not this template.
    """
    template = demo_templates["smilecare_dental"]
    nodes = {node["id"]: node for node in template["nodes"]}
    lookup = nodes["action_1"]["data"]["config"]
    append = nodes["sheets_1"]["data"]["config"]

    assert lookup["params"]["range"] == append["params"]["range"] == "Patients!A:K"
    # Production/template contract: lookup is keyed by patient_name (on_missing → contact).
    assert lookup["required_inputs"] == ["patient_name"]
    assert lookup["prefill_match_column"] == 1
    assert lookup["prefill_match_value"] == "{{patient_name}}"
    assert lookup["prefill_mapping"]["1"] == "patient_name"
    assert lookup["prefill_mapping"]["2"] == "caller_phone"
    assert lookup["prefill_mapping"]["3"] == "caller_email"
    assert len(append["params"]["values"]) == 11
    assert "@gmail.com" not in json.dumps(template).lower()


@pytest.mark.parametrize(
    ("patient_name", "expected_rows", "expected_phone"),
    [
        (
            "Ali Khan",
            [
                ["Date", "Name", "Phone", "Email"],
                ["2026-07-02", "Ali Khan", "+923001111111", "ali@example.com"],
            ],
            "+923001111111",
        ),
        ("Unknown Patient", [], None),
    ],
)
@pytest.mark.asyncio
async def test_sheets_prefill_matches_the_requested_patient_only(monkeypatch, patient_name, expected_rows, expected_phone):
    rows = [
        ["Date", "Name", "Phone", "Email"],
        ["2026-07-01", "Other Patient", "+923009999999", "other@example.com"],
        ["2026-07-02", "Ali Khan", "+923001111111", "ali@example.com"],
    ]

    async def fake_execute_graph_node(self, node, context, event_callback=None):
        return {"node_id": node["id"], "node_type": "google_sheets", "status": "success", "result": {"rows": deepcopy(rows), "count": 2}}

    monkeypatch.setattr(WorkflowExecutor, "_execute_graph_node", fake_execute_graph_node)
    node = {
        "id": "action_1",
        "type": "action",
        "data": {"label": "Check Existing Patient", "config": {
            "integration_type": "google_sheets",
            "action": "read_rows",
            "params": {"range": "Patients!A:K"},
            "required_inputs": ["patient_name"],
            "prefill": True,
            "has_header": True,
            "prefill_match_column": 1,
            "prefill_match_value": "{{patient_name}}",
            "prefill_mapping": {"1": "patient_name", "2": "caller_phone", "3": "caller_email"},
        }},
    }
    state = create_initial_state({"nodes": [node], "edges": []}, user_id=1, agent_id=1)
    state["current_node"] = node["id"]
    state["extracted_vars"] = {"patient_name": patient_name}
    config = {"configurable": {"db_session": object(), "agent": SimpleNamespace(id=1, integration_overrides_json=None), "user_id": 1}}

    result = await create_node_handlers()["action"](state, config)

    assert result["result"]["rows"] == expected_rows
    assert result["extracted_vars"].get("caller_phone") == expected_phone


async def _walk_graph(template, conversation_values, action_values=None):
    visited = []
    evaluator = ConditionEvaluator()
    action_values = action_values or {}

    async def conversation(state, config):
        node_id = state["current_node"]
        visited.append(node_id)
        values = conversation_values.get(node_id, {})
        return {"extracted_vars": values, "result": values, "_conversation_phase": "generate", "_slots_missing": [], "retry_count": 0}

    async def condition(state, config):
        node_id = state["current_node"]
        visited.append(node_id)
        node_config = state["nodes_by_id"][node_id]["data"]["config"]
        context = {**state.get("extracted_vars", {}), **state.get("result", {}), "result": state.get("result", {})}
        return {"_condition_met": evaluator.evaluate(node_config["expression"], context)}

    async def slot_validator(state, config):
        visited.append(state["current_node"])
        return {"result": {"branch": "done"}, "last_result": {"branch": "done"}}

    async def action(state, config):
        node_id = state["current_node"]
        visited.append(node_id)
        output = action_values.get(node_id, {"success": True})
        return {"result": output, "last_result": output, "_action_error": None}

    async def control(state, config):
        visited.append(state["current_node"])
        return {}

    handlers = {
        "conversation": conversation,
        "condition": condition,
        "slot_validator": slot_validator,
        "action": action,
        "trigger": control,
        "end": control,
        "end_call": control,
        "voicemail_detect": control,
        "note": control,
        "delay": control,
    }
    graph = {"nodes": template["nodes"], "edges": template["edges"]}
    compiled = compile_flow(graph, node_handlers=handlers)
    state = create_initial_state(graph, user_id=1, agent_id=1, caller_phone="+923001234567")
    await compiled.ainvoke(state, config={"recursion_limit": 100})
    return visited


@pytest.mark.asyncio
async def test_smilecare_emergency_branch_walks_to_emergency_end(demo_templates):
    visited = await _walk_graph(
        demo_templates["smilecare_dental"],
        {
            "conversation_1": {"patient_name": "Ali", "visit_type": "knocked out tooth", "is_emergency": "yes"},
            "conversation_emergency": {"understood_instructions": "yes"},
        },
    )
    assert "end_emergency" in visited
    assert "conversation_2" not in visited


@pytest.mark.asyncio
async def test_smilecare_booking_branch_walks_through_all_integrations(demo_templates):
    visited = await _walk_graph(
        demo_templates["smilecare_dental"],
        {
            "conversation_1": {"patient_name": "Ali", "visit_type": "cleaning", "is_emergency": "no"},
            "conversation_contact": {"patient_name": "Ali", "caller_email": "ali@example.com", "caller_phone": "+923001234567"},
            "conversation_visit": {"is_new_patient": "new", "service_requested": "cleaning"},
            "conversation_schedule": {"preferred_date": "2026-07-25", "preferred_time": "11:00"},
            "conversation_dentist": {"preferred_dentist": "Sana Tariq", "insurance_provider": "none"},
            "confirm_booking": {"confirm_booking": "yes"},
        },
        {
            "action_1": {"success": True, "rows": []},
            "action_2": {"success": True, "requested_time_available": True, "available_slots": [{"start": "2026-07-25T11:00:00+05:00"}]},
        },
    )
    assert [node_id for node_id in ("action_1", "action_2", "action_3", "sheets_1", "email_1", "end_1") if node_id not in visited] == []
    assert "conversation_4" not in visited


@pytest.mark.asyncio
async def test_umt_admission_visit_branch_walks_through_all_integrations(demo_templates):
    visited = await _walk_graph(
        demo_templates["umt_admission"],
        {
            "conversation_1": {"student_name": "Sara", "query_type": "admission_inquiry"},
            "conversation_2": {"student_name": "Sara", "caller_phone": "+923001234567", "caller_email": "sara@example.com", "program_interest": "BSCS", "intermediate_marks": "91%", "prospect_city": "Lahore"},
            "conversation_3": {"scholarship_tier": "knowledge-base tier", "wants_campus_visit": "yes", "preferred_date": "2026-07-25"},
            "conversation_4": {"preferred_date": "2026-07-25", "preferred_time": "11:00"},
        },
        {"action_3": {"success": True, "available_slots": ["11:00"]}},
    )
    assert [node_id for node_id in ("action_1", "action_2", "action_3", "action_4", "email_1", "end_1") if node_id not in visited] == []
    assert "conversation_general" not in visited


@pytest.mark.asyncio
async def test_umt_outreach_not_interested_branch_closes_without_integrations(demo_templates):
    visited = await _walk_graph(
        demo_templates["umt_outreach"],
        {"conversation_1": {"prospect_name": "Hamza", "is_interested": "no"}, "conversation_2": {"callback_requested": "no"}},
    )
    assert "end_1" in visited
    assert all(action_id not in visited for action_id in ("action_1", "action_2", "action_3", "action_4", "email_1"))


@pytest.mark.asyncio
async def test_umt_outreach_visit_branch_walks_through_all_integrations(demo_templates):
    visited = await _walk_graph(
        demo_templates["umt_outreach"],
        {
            "conversation_1": {"prospect_name": "Hamza", "is_interested": "yes"},
            "conversation_3": {"program_interest": "BSCS", "prospect_city": "Lahore"},
            "conversation_4": {"intermediate_marks": "90%", "board": "Lahore Board"},
            "conversation_5": {"scholarship_tier": "knowledge-base tier", "budget_concern": "no"},
            "conversation_7": {"wants_visit": "yes", "preferred_date": "2026-07-25"},
            "conversation_8": {"preferred_date": "2026-07-25", "preferred_time": "11:00", "caller_email": "hamza@example.com"},
        },
        {"action_3": {"success": True, "available_slots": ["11:00"]}},
    )
    assert [node_id for node_id in ("action_1", "action_2", "action_3", "action_4", "email_1", "end_2") if node_id not in visited] == []
    assert "conversation_9" not in visited


@pytest.mark.asyncio
async def test_workflow_create_and_update_sync_graph_and_mode_to_linked_agent(client, db_session, test_agent, demo_templates):
    admission = demo_templates["umt_admission"]
    graph = {"nodes": admission["nodes"], "edges": admission["edges"]}
    response = await client.post("/api/workflows", json={
        "name": "UMT Admission Demo",
        "trigger_phrases": admission["trigger_phrases"],
        "agent_id": test_agent.id,
        "graph": graph,
    })
    assert response.status_code == 201

    refreshed = (await db_session.execute(select(Agent).where(Agent.id == test_agent.id))).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.mode == "conversational_flow"
    assert json.loads(refreshed.graph_json) == graph

    outreach = demo_templates["umt_outreach"]
    updated_graph = {"nodes": outreach["nodes"], "edges": outreach["edges"]}
    workflow_id = response.json()["workflow"]["id"]
    update_response = await client.put(f"/api/workflows/{workflow_id}", json={"graph": updated_graph})
    assert update_response.status_code == 200
    await db_session.refresh(refreshed)
    assert refreshed.mode == "conversational_flow"
    assert json.loads(refreshed.graph_json) == updated_graph
