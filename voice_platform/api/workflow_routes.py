"""
Voice Platform — Workflow API Routes
=======================================

CRUD endpoints for intent-based workflow routing rules.

Workflows define what happens when the AI detects a specific user intent.
Each workflow has trigger phrases (e.g. "schedule appointment") and an
associated action (e.g. call an external calendar API).

Routes:
    GET    /api/workflows       — List user's workflows
    POST   /api/workflows       — Create a new workflow
    GET    /api/workflows/{id}  — Get workflow details
    PUT    /api/workflows/{id}  — Update workflow
    DELETE /api/workflows/{id}  — Deactivate workflow
"""

import json  # For serializing trigger_phrases list to JSON string
from typing import Any, List, Literal, Optional  # Type hints

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.config import settings
from voice_platform.database import Agent, ReviewQueue, User, Workflow, get_db
from voice_platform.errors import (
    AgentNotFoundError,
    NotFoundError,
    ValidationError,
    WorkflowNotFoundError,
)
from voice_platform.middleware.auth_middleware import get_current_user
from voice_platform.graph_contracts import (
    add_missing_input_fallback_edges,
    canonical_content_hash,
    edge_branch_key,
    required_input_branch_violations,
)
from voice_platform.utils import normalize_trigger_phrases

# Create router
router = APIRouter(prefix="/api/workflows", tags=["Workflows"])


# ── Request Schemas ────────────────────────────────────────────────────

class WorkflowStepSchema(BaseModel):
    """Schema for a single workflow step."""
    step_number: int = Field(..., ge=1, description="Execution order (1-based)")
    integration_id: int = Field(..., description="Which integration to use")
    action: str = Field(..., description="Action to perform (e.g. create_event, append_row)")
    params: dict = Field(default_factory=dict, description="Action params with {{template}} support")


class CreateWorkflowRequest(BaseModel):
    """Schema for creating a new workflow."""
    name: str = Field(..., min_length=1, max_length=255, description="Workflow name")
    description: Optional[str] = Field(None, description="What this workflow does")
    # List of phrases that trigger this workflow
    # Stored as JSON in the database
    trigger_phrases: List[str] | str = Field(
        ..., description="Phrases that activate this workflow"
    )
    agent_id: Optional[int] = Field(None, description="Route to a different agent")
    action_type: Optional[str] = Field(None, description="Action type (e.g. 'action_external')")
    action_url: Optional[str] = Field(None, description="URL for external action")
    requires_approval: bool = Field(default=False, description="Needs human approval?")
    transition_flexibility: Optional[Literal["strict", "flex"]] = Field(
        default="flex", description="Graph execution mode: strict (follow edges) or flex (LLM chooses)"
    )
    steps: Optional[List[WorkflowStepSchema]] = Field(None, description="Integration steps to execute")
    graph: Optional[dict] = Field(None, description="Full ReactFlow graph state {nodes, edges} for lossless round-trip")


class UpdateWorkflowRequest(BaseModel):
    """Schema for updating a workflow. All fields optional."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    trigger_phrases: Optional[List[str] | str] = None
    agent_id: Optional[int] = None
    action_type: Optional[str] = None
    action_url: Optional[str] = None
    requires_approval: Optional[bool] = None
    is_active: Optional[bool] = None
    transition_flexibility: Optional[Literal["strict", "flex"]] = Field(
        default=None, description="Graph execution mode: strict or flex"
    )
    steps: Optional[List[WorkflowStepSchema]] = None
    graph: Optional[dict] = None
    expected_graph_hash: Optional[str] = Field(
        default=None,
        min_length=16,
        max_length=64,
        pattern=r"^[a-f0-9]+$",
        description="Graph hash returned by the last GET/PUT; prevents stale graph overwrites.",
    )


def _validate_graph(graph: dict) -> list[str]:
    """
    Validate a ReactFlow graph's structural integrity.

    Returns a list of warning strings (empty if valid).
    Raises ValidationError for blocking issues (dangling edge refs, duplicate edge IDs).
    """
    warnings: list[str] = []

    if not isinstance(graph, dict):
        raise ValidationError(
            field="graph",
            message="Graph must be a JSON object.",
            suggestion="Ensure the graph was exported from the ReactFlow editor.",
        )

    nodes = graph.get("nodes")
    edges = graph.get("edges")

    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValidationError(
            field="graph",
            message="Graph must contain 'nodes' and 'edges' arrays.",
            suggestion="Ensure the graph was exported from the ReactFlow editor.",
        )

    if not nodes:
        raise ValidationError(
            field="graph",
            message="Graph has no nodes.",
            suggestion="Add at least a trigger and an end node.",
        )

    def node_type(node: dict) -> str:
        data = node.get("data") or {}
        return str(data.get("nodeType") or node.get("type") or "")

    node_ids = set()
    for node in nodes:
        nid = node.get("id")
        if not nid:
            raise ValidationError(
                field="graph",
                message="All nodes must have an 'id' field.",
                suggestion="Check the graph node definitions.",
            )
        normalized_id = str(nid)
        if normalized_id in node_ids:
            raise ValidationError(
                field="graph",
                message=f"Duplicate node ID '{normalized_id}'.",
                suggestion="Ensure each graph node has a unique ID.",
            )
        node_ids.add(normalized_id)

    edge_ids_seen = set()
    for edge in edges:
        eid = edge.get("id")
        source = str(edge.get("source")) if edge.get("source") else None
        target = str(edge.get("target")) if edge.get("target") else None

        if not source or not target:
            raise ValidationError(
                field="graph",
                message="Every edge must have both a source and a target.",
                suggestion="Remove incomplete edges or reconnect them in the workflow editor.",
            )

        if source not in node_ids:
            raise ValidationError(
                field="graph",
                message=f"Edge references non-existent source node '{source}'.",
                suggestion="Remove the orphan edge or re-link it to an existing node.",
            )
        if target not in node_ids:
            raise ValidationError(
                field="graph",
                message=f"Edge references non-existent target node '{target}'.",
                suggestion="Remove the orphan edge or re-link it to an existing node.",
            )

        if eid:
            if eid in edge_ids_seen:
                raise ValidationError(
                    field="graph",
                    message=f"Duplicate edge ID '{eid}'.",
                    suggestion="Ensure each edge has a unique ID.",
                )
            edge_ids_seen.add(eid)

    nodes_by_id = {str(node["id"]): node for node in nodes}
    outgoing_edges = {node_id: [] for node_id in node_ids}
    incoming_edges = {node_id: [] for node_id in node_ids}
    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        outgoing_edges[source].append(edge)
        incoming_edges[target].append(edge)

    trigger_ids = [
        node_id for node_id, node in nodes_by_id.items()
        if node_type(node) == "trigger"
    ]
    if len(trigger_ids) != 1:
        raise ValidationError(
            field="graph",
            message=f"Graph must have exactly one trigger node; found {len(trigger_ids)}.",
            suggestion="Keep one call trigger and remove duplicate start nodes.",
        )

    explicit_terminal_ids = {
        node_id for node_id, node in nodes_by_id.items()
        if node_type(node) in {"end", "end_call"}
    }
    if not explicit_terminal_ids:
        raise ValidationError(
            field="graph",
            message="Graph must have at least one end or end_call node.",
            suggestion="Add an explicit terminal node to every completion path.",
        )
    for terminal_id in explicit_terminal_ids:
        if outgoing_edges[terminal_id]:
            raise ValidationError(
                field="graph",
                message=f"Terminal node '{terminal_id}' cannot have outgoing edges.",
                suggestion="Remove edges leaving end and end_call nodes.",
            )

    for node_id, node in nodes_by_id.items():
        if node_type(node) != "condition":
            continue
        branches = outgoing_edges[node_id]
        normalized_branches = []
        for edge in branches:
            branch = str(edge.get("sourceHandle") or edge.get("label") or "").strip().lower()
            if branch in {"yes", "true"}:
                edge["sourceHandle"] = "yes"
                edge["label"] = "Yes"
                normalized_branches.append("yes")
            elif branch in {"no", "false"}:
                edge["sourceHandle"] = "no"
                edge["label"] = "No"
                normalized_branches.append("no")
        if len(branches) != 2 or set(normalized_branches) != {"yes", "no"}:
            raise ValidationError(
                field="graph",
                message=f"Condition node '{node_id}' must have exactly one Yes edge and one No edge.",
                suggestion="Connect the labeled Yes and No handles to distinct workflow paths.",
            )

    branch_violations = required_input_branch_violations(graph)
    if branch_violations:
        violation = branch_violations[0]
        raise ValidationError(
            field="graph",
            message=(
                f"Action node '{violation['node_id']}' can emit on_missing but has "
                f"{violation['on_missing_edges']} on_missing edges; exactly one is required."
            ),
            suggestion=(
                "Connect the node's Missing info handle to a safe recovery or terminal node. "
                "Do not rely on the generic error edge."
            ),
        )

    reachable = set()
    stack = [trigger_ids[0]]
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        stack.extend(str(edge["target"]) for edge in outgoing_edges[node_id])
    unreachable = sorted(node_ids - reachable)
    if unreachable:
        raise ValidationError(
            field="graph",
            message=f"Graph contains nodes unreachable from the trigger: {', '.join(unreachable[:5])}.",
            suggestion="Connect or remove the unreachable nodes.",
        )

    runtime_terminal_ids = explicit_terminal_ids | {
        node_id for node_id, node in nodes_by_id.items()
        if node_type(node) == "transfer_call" and not outgoing_edges[node_id]
    }
    can_reach_terminal = set(runtime_terminal_ids)
    stack = list(runtime_terminal_ids)
    while stack:
        node_id = stack.pop()
        for edge in incoming_edges[node_id]:
            source = str(edge["source"])
            if source not in can_reach_terminal:
                can_reach_terminal.add(source)
                stack.append(source)
    dead_ends = sorted(reachable - can_reach_terminal)
    if dead_ends:
        raise ValidationError(
            field="graph",
            message=f"Graph contains paths that cannot reach an end node: {', '.join(dead_ends[:5])}.",
            suggestion="Connect every branch to an end, end_call, or final transfer_call node.",
        )

    from voice_platform.flow.compiler import get_cycle_warnings

    true_cycles, _ = get_cycle_warnings(graph)
    if true_cycles:
        raise ValidationError(
            field="graph",
            message=f"Graph contains an unbounded cycle near: {', '.join(true_cycles[:5])}.",
            suggestion="Remove the loop or gate it with a _slot_retry_count condition.",
        )

    return warnings


def _umt_admission_template() -> dict:
    return {
        "id": "umt_admission",
        "agent_template_id": "university",
        "name": "UMT Admission Guide",
        "description": "Inbound UMT admissions guide that answers from the knowledge base, captures qualified inquiries, schedules campus visits, and sends follow-up details.",
        "category": "education",
        "icon": "graduation-cap",
        "trigger_phrases": [
            "UMT admission information",
            "I want to apply to UMT",
            "tell me about UMT programs",
            "UMT fee structure",
            "UMT scholarships",
            "admission requirements",
            "schedule a UMT campus visit",
        ],
        "nodes": [
            {"id": "trigger_1", "type": "trigger", "position": {"x": 400, "y": 40},
             "data": {"label": "Admission Call Received", "config": {}}},
            {"id": "conversation_1", "type": "conversation", "position": {"x": 400, "y": 180},
             "data": {"label": "Identify Admission Need", "config": {
                 "prompt": "Welcome the caller to the University of Management and Technology in Lahore. Ask their name and whether they want to apply, need admission guidance, or have a general question about programs, fees, scholarships, campus life, or careers. Classify an application or eligibility discussion as admission_inquiry and other questions as general_question.",
                 "variables_to_extract": ["student_name", "query_type"],
             }}},
            {"id": "condition_1", "type": "condition", "position": {"x": 400, "y": 330},
             "data": {"label": "Admission Inquiry?", "config": {"expression": "query_type == \"admission_inquiry\""}}},
            {"id": "conversation_2", "type": "conversation", "position": {"x": 120, "y": 500},
             "data": {"label": "Collect Student Details", "config": {
                 "prompt": "Collect the prospective student's name, phone number, email address, program of interest, Intermediate marks or percentage, and city. Ask one question at a time, explain that the details are used only for admission follow-up, and do not guess missing information.",
                 "variables_to_extract": ["student_name", "caller_phone", "caller_email", "program_interest", "intermediate_marks", "prospect_city"],
                 "optional_inputs": ["intermediate_marks", "prospect_city"],
             }}},
            {"id": "slot_validator_1", "type": "slot_validator", "position": {"x": 120, "y": 680},
             "data": {"label": "Validate Student Details", "config": {
                 "required_slots": ["student_name", "caller_phone", "caller_email", "program_interest"],
                 "on_exhausted": "end_call",
             }}},
            {"id": "collect_name", "type": "conversation", "position": {"x": -360, "y": 620},
             "data": {"label": "Collect Student Name", "config": {"prompt": "May I have the student's full name?", "variables_to_extract": ["student_name"]}}},
            {"id": "collect_phone", "type": "conversation", "position": {"x": -360, "y": 730},
             "data": {"label": "Collect Phone", "config": {"prompt": "What is the best phone number for the admissions team to use?", "variables_to_extract": ["caller_phone"]}}},
            {"id": "collect_email", "type": "conversation", "position": {"x": -360, "y": 840},
             "data": {"label": "Collect Email", "config": {"prompt": "What email address should receive the admission brochure and follow-up details?", "variables_to_extract": ["caller_email"]}}},
            {"id": "collect_program", "type": "conversation", "position": {"x": -360, "y": 950},
             "data": {"label": "Collect Program", "config": {"prompt": "Which UMT program are you interested in?", "variables_to_extract": ["program_interest"]}}},
            {"id": "end_exhausted", "type": "end_call", "position": {"x": -360, "y": 1060},
             "data": {"label": "Student Details Exhausted", "config": {"message": "I am sorry, I could not collect the details needed for follow-up. Please call UMT admissions again or visit admissions dot UMT dot E-D-U dot P-K. Thank you for calling."}}},
            {"id": "action_1", "type": "action", "position": {"x": 120, "y": 850},
             "data": {"label": "Check Existing Inquiry", "config": {
                 "integration_type": "google_sheets",
                 "action": "read_rows",
                 "params": {"range": "Inquiries!A:I", "max_rows": 200},
                 "required_inputs": ["student_name"],
                 "prefill": True,
                 "has_header": True,
                 "prefill_match_column": 1,
                 "prefill_match_value": "{{student_name}}",
                 "prefill_mapping": {"1": "student_name", "2": "caller_phone", "3": "caller_email", "4": "program_interest", "5": "intermediate_marks", "6": "prospect_city"},
             }}},
            {"id": "conversation_3", "type": "conversation", "position": {"x": 120, "y": 1020},
             "data": {"label": "Answer and Assess", "config": {
                 "prompt": "Answer the student's questions only from the configured UMT knowledge base. Explain the requested program, verified fees, admission requirements, deadlines, and scholarship rules relevant to their marks. If the knowledge base does not contain a fact, say an admissions counselor will confirm it. Ask whether they want a campus visit and, if yes, which date they prefer.",
                 "variables_to_extract": ["scholarship_tier", "wants_campus_visit", "preferred_date"],
                 "optional_inputs": ["scholarship_tier", "preferred_date"],
             }}},
            {"id": "action_2", "type": "action", "position": {"x": 120, "y": 1190},
             "data": {"label": "Log Admission Inquiry", "config": {
                 "integration_type": "google_sheets",
                 "action": "append_row",
                 "params": {"range": "Inquiries!A:I", "values": ["{{current_date}}", "{{student_name}}", "{{caller_phone}}", "{{caller_email}}", "{{program_interest}}", "{{intermediate_marks}}", "{{prospect_city}}", "{{scholarship_tier}}", "admission inquiry"]},
                 "required_inputs": ["current_date", "student_name", "caller_phone", "caller_email", "program_interest"],
                 "optional_inputs": ["intermediate_marks", "prospect_city", "scholarship_tier"],
             }}},
            {"id": "condition_2", "type": "condition", "position": {"x": 120, "y": 1350},
             "data": {"label": "Campus Visit Requested?", "config": {"expression": "wants_campus_visit == true"}}},
            {"id": "slot_validator_visit", "type": "slot_validator", "position": {"x": -80, "y": 1510},
             "data": {"label": "Validate Visit Date", "config": {"required_slots": ["preferred_date"], "on_exhausted": "end_call"}}},
            {"id": "collect_visit_date", "type": "conversation", "position": {"x": -400, "y": 1510},
             "data": {"label": "Collect Visit Date", "config": {"prompt": "Which date would you prefer for your UMT campus visit?", "variables_to_extract": ["preferred_date"]}}},
            {"id": "end_visit_exhausted", "type": "end_call", "position": {"x": -400, "y": 1640},
             "data": {"label": "Visit Date Exhausted", "config": {"message": "I could not confirm a campus visit date, but your inquiry has been recorded and the admissions team can follow up. Thank you for calling UMT."}}},
            {"id": "action_3", "type": "action", "position": {"x": -80, "y": 1680},
             "data": {"label": "Check Campus Availability", "config": {
                 "integration_type": "google_calendar",
                 "action": "check_availability",
                 "params": {"date": "{{preferred_date}}", "duration_minutes": 60, "business_hours_start": "09:00", "business_hours_end": "18:00"},
                 "required_inputs": ["preferred_date"],
             }}},
            {"id": "conversation_4", "type": "conversation", "position": {"x": -80, "y": 1850},
             "data": {"label": "Confirm Campus Visit", "config": {
                 "prompt": "Use the calendar availability in the flow context to offer a valid UMT campus visit slot. Confirm the final date and time with the caller. Do not claim a slot is booked yet.",
                 "variables_to_extract": ["preferred_date", "preferred_time"],
             }}},
            {"id": "slot_validator_booking", "type": "slot_validator", "position": {"x": -80, "y": 2020},
             "data": {"label": "Validate Visit Booking", "config": {"required_slots": ["preferred_date", "preferred_time"], "on_exhausted": "end_call"}}},
            {"id": "collect_booking_date", "type": "conversation", "position": {"x": -400, "y": 1960},
             "data": {"label": "Confirm Visit Date", "config": {"prompt": "Which available visit date would you like to confirm?", "variables_to_extract": ["preferred_date"]}}},
            {"id": "collect_visit_time", "type": "conversation", "position": {"x": -400, "y": 2070},
             "data": {"label": "Confirm Visit Time", "config": {"prompt": "Which available time would you like for the campus visit?", "variables_to_extract": ["preferred_time"]}}},
            {"id": "end_booking_exhausted", "type": "end_call", "position": {"x": -400, "y": 2180},
             "data": {"label": "Visit Booking Exhausted", "config": {"message": "I could not confirm both the visit date and time. Your inquiry is saved and the admissions team can contact you to arrange the visit. Thank you for calling UMT."}}},
            {"id": "action_4", "type": "action", "position": {"x": -80, "y": 2190},
             "data": {"label": "Book Campus Visit", "config": {
                 "integration_type": "google_calendar",
                 "action": "create_event",
                 "params": {"title": "UMT Campus Visit - {{student_name}}", "date": "{{preferred_date}}", "time": "{{preferred_time}}", "duration_minutes": 60, "location": "UMT Main Campus, C-II Johar Town, Lahore", "description": "Student: {{student_name}}\nPhone: {{caller_phone}}\nEmail: {{caller_email}}\nProgram: {{program_interest}}"},
                 "required_inputs": ["student_name", "caller_phone", "caller_email", "program_interest", "preferred_date", "preferred_time"],
             }}},
            {"id": "email_1", "type": "send_email", "position": {"x": 120, "y": 2370},
             "data": {"label": "Send Admission Follow-up", "config": {
                 "to": "{{caller_email}}",
                 "subject": "UMT Admission Information for {{student_name}}",
                 "body": "Dear {{student_name}},\n\nThank you for contacting UMT about {{program_interest}}. Your admission inquiry has been recorded. Scholarship indication discussed on the call: {{scholarship_tier}}. Campus visit date: {{preferred_date}}. Campus visit time: {{preferred_time}}.\n\nPlease verify current fees, deadlines, eligibility, and scholarship approval with the UMT admissions office or admissions.umt.edu.pk.\n\nUMT Admissions",
                 "required_inputs": ["caller_email", "student_name"],
                 "optional_inputs": ["program_interest", "scholarship_tier", "preferred_date", "preferred_time"],
             }}},
            {"id": "end_1", "type": "end_call", "position": {"x": 120, "y": 2530},
             "data": {"label": "Admission Follow-up Complete", "config": {"message": "Thank you, {{student_name}}. Your inquiry has been recorded and the admission details will be sent to your email. Please visit admissions dot UMT dot E-D-U dot P-K for the official application. Allah hafiz.", "error_message": "Your details are recorded, but I could not complete one of the follow-up steps. A UMT admissions counselor can contact you. Thank you for calling."}}},
            {"id": "conversation_general", "type": "conversation", "position": {"x": 680, "y": 500},
             "data": {"label": "Answer General Question", "config": {
                 "prompt": "Answer the caller's general UMT question only from the configured knowledge base. Never guess fees, dates, eligibility, or scholarship terms. Ask whether they want an admissions counselor to send more information or follow up.",
                 "variables_to_extract": ["wants_more_info"],
             }}},
            {"id": "condition_3", "type": "condition", "position": {"x": 680, "y": 680},
             "data": {"label": "Follow-up Requested?", "config": {"expression": "wants_more_info == true"}}},
            {"id": "end_2", "type": "end_call", "position": {"x": 880, "y": 850},
             "data": {"label": "General Question Complete", "config": {"message": "I hope that answered your question. For official and current admission information, please visit admissions dot UMT dot E-D-U dot P-K. Thank you for calling UMT."}}},
            {"id": "end_integration_error", "type": "end_call", "position": {"x": 420, "y": 2190},
             "data": {"label": "Admission Integration Error", "config": {"message": "I have your details, but I could not complete the external follow-up right now. A UMT admissions counselor can contact you. Thank you for calling."}}},
        ],
        "edges": [
            {"source": "trigger_1", "target": "conversation_1"},
            {"source": "conversation_1", "target": "condition_1"},
            {"source": "condition_1", "target": "conversation_2", "label": "Yes"},
            {"source": "condition_1", "target": "conversation_general", "label": "No"},
            {"source": "conversation_2", "target": "slot_validator_1"},
            {"source": "slot_validator_1", "target": "collect_name", "label": "student_name"},
            {"source": "slot_validator_1", "target": "collect_phone", "label": "caller_phone"},
            {"source": "slot_validator_1", "target": "collect_email", "label": "caller_email"},
            {"source": "slot_validator_1", "target": "collect_program", "label": "program_interest"},
            {"source": "slot_validator_1", "target": "action_1", "label": "done"},
            {"source": "slot_validator_1", "target": "end_exhausted", "label": "exhausted"},
            {"source": "collect_name", "target": "slot_validator_1"},
            {"source": "collect_phone", "target": "slot_validator_1"},
            {"source": "collect_email", "target": "slot_validator_1"},
            {"source": "collect_program", "target": "slot_validator_1"},
            {"source": "action_1", "target": "conversation_3", "label": "error"},
            {"source": "action_1", "target": "conversation_3"},
            {"source": "conversation_3", "target": "action_2"},
            {"source": "action_2", "target": "condition_2"},
            {"source": "action_2", "target": "end_integration_error", "label": "error"},
            {"source": "condition_2", "target": "slot_validator_visit", "label": "Yes"},
            {"source": "condition_2", "target": "email_1", "label": "No"},
            {"source": "slot_validator_visit", "target": "collect_visit_date", "label": "preferred_date"},
            {"source": "slot_validator_visit", "target": "action_3", "label": "done"},
            {"source": "slot_validator_visit", "target": "end_visit_exhausted", "label": "exhausted"},
            {"source": "collect_visit_date", "target": "slot_validator_visit"},
            {"source": "action_3", "target": "conversation_4"},
            {"source": "action_3", "target": "end_integration_error", "label": "error"},
            {"source": "conversation_4", "target": "slot_validator_booking"},
            {"source": "slot_validator_booking", "target": "collect_booking_date", "label": "preferred_date"},
            {"source": "slot_validator_booking", "target": "collect_visit_time", "label": "preferred_time"},
            {"source": "slot_validator_booking", "target": "action_4", "label": "done"},
            {"source": "slot_validator_booking", "target": "end_booking_exhausted", "label": "exhausted"},
            {"source": "collect_booking_date", "target": "slot_validator_booking"},
            {"source": "collect_visit_time", "target": "slot_validator_booking"},
            {"source": "action_4", "target": "email_1"},
            {"source": "action_4", "target": "end_integration_error", "label": "error"},
            {"source": "email_1", "target": "end_1"},
            {"source": "email_1", "target": "end_integration_error", "label": "error"},
            {"source": "conversation_general", "target": "condition_3"},
            {"source": "condition_3", "target": "conversation_2", "label": "Yes"},
            {"source": "condition_3", "target": "end_2", "label": "No"},
        ],
    }


def _umt_outreach_template() -> dict:
    return {
        "id": "umt_outreach",
        "agent_template_id": "umt_outreach",
        "name": "UMT Outreach Counselor",
        "description": "Outbound UMT admissions outreach flow that qualifies prospects, explains scholarship eligibility from the knowledge base, logs leads, schedules visits, and sends follow-up details.",
        "category": "education",
        "icon": "megaphone",
        "trigger_phrases": [
            "outbound UMT admissions call started",
            "prospective student outreach",
            "UMT admissions follow-up call",
        ],
        "nodes": [
            {"id": "trigger_1", "type": "trigger", "position": {"x": 420, "y": 40},
             "data": {"label": "Outbound Call Placed", "config": {"trigger_type": "outbound_call"}}},
            {"id": "conversation_1", "type": "conversation", "position": {"x": 420, "y": 180},
             "data": {"label": "Permission and Interest", "config": {
                 "prompt": "Introduce yourself as Bilal from UMT admissions, confirm the prospect's name, and ask whether they have a quick minute to discuss programs and scholarship options. Be respectful and stop selling if they are not interested.",
                 "variables_to_extract": ["is_interested", "prospect_name"],
             }}},
            {"id": "condition_1", "type": "condition", "position": {"x": 420, "y": 340},
             "data": {"label": "Prospect Interested?", "config": {"expression": "is_interested == true"}}},
            {"id": "conversation_2", "type": "conversation", "position": {"x": 760, "y": 500},
             "data": {"label": "Respectful Close", "config": {
                 "prompt": "Thank the prospect for their time without pressure. Ask once whether a later callback would be useful; if not, close politely and do not continue qualification.",
                 "variables_to_extract": ["callback_requested"],
             }}},
            {"id": "end_1", "type": "end_call", "position": {"x": 760, "y": 670},
             "data": {"label": "Not Interested End", "config": {"message": "No problem at all. Thank you for your time, and best of luck with your studies. Allah hafiz."}}},
            {"id": "conversation_3", "type": "conversation", "position": {"x": 160, "y": 500},
             "data": {"label": "Program and City", "config": {
                 "prompt": "Ask which degree program the prospect is considering and which city they are from. React naturally to their answer and use only verified UMT knowledge-base facts when briefly describing a program.",
                 "variables_to_extract": ["program_interest", "prospect_city"],
             }}},
            {"id": "conversation_4", "type": "conversation", "position": {"x": 160, "y": 670},
             "data": {"label": "Academic Profile", "config": {
                 "prompt": "Ask for the prospect's Intermediate marks or percentage and board so scholarship eligibility can be discussed. Do not imply approval and do not invent a scholarship rule.",
                 "variables_to_extract": ["intermediate_marks", "board"],
                 "optional_inputs": ["board"],
             }}},
            {"id": "conversation_5", "type": "conversation", "position": {"x": 160, "y": 840},
             "data": {"label": "Scholarship and Value", "config": {
                 "prompt": "Using only the configured UMT knowledge base, calculate and explain the scholarship tier indicated by the prospect's marks. State that final eligibility requires official verification. Share one or two relevant UMT value points and ask whether budget is a concern.",
                 "variables_to_extract": ["scholarship_tier", "budget_concern"],
             }}},
            {"id": "condition_2", "type": "condition", "position": {"x": 160, "y": 1010},
             "data": {"label": "Budget Concern?", "config": {"expression": "budget_concern == true"}}},
            {"id": "conversation_6", "type": "conversation", "position": {"x": -140, "y": 1170},
             "data": {"label": "Address Budget", "config": {
                 "prompt": "Acknowledge the budget concern. From the knowledge base, explain only verified installment options, applicable scholarships, and a neutral fee comparison. Ask which option would be most useful for follow-up.",
                 "variables_to_extract": ["payment_preference"],
             }}},
            {"id": "action_1", "type": "action", "position": {"x": 160, "y": 1330},
             "data": {"label": "Check Existing Lead", "config": {
                 "integration_type": "google_sheets",
                 "action": "read_rows",
                 "params": {"range": "Leads!A:H", "max_rows": 500},
                 "required_inputs": ["prospect_name"],
                 "prefill": True,
                 "has_header": True,
                 "prefill_match_column": 1,
                 "prefill_match_value": "{{prospect_name}}",
                 "prefill_mapping": {"1": "prospect_name", "2": "caller_phone", "3": "program_interest", "4": "intermediate_marks", "5": "prospect_city", "6": "scholarship_tier"},
             }}},
            {"id": "action_2", "type": "action", "position": {"x": 160, "y": 1500},
             "data": {"label": "Log Qualified Lead", "config": {
                 "integration_type": "google_sheets",
                 "action": "append_row",
                 "params": {"range": "Leads!A:H", "values": ["{{current_date}}", "{{prospect_name}}", "{{caller_phone}}", "{{program_interest}}", "{{intermediate_marks}}", "{{prospect_city}}", "{{scholarship_tier}}", "Campus visit or follow-up offered"]},
                 "required_inputs": ["current_date", "prospect_name", "caller_phone", "program_interest", "intermediate_marks", "prospect_city", "scholarship_tier"],
             }}},
            {"id": "conversation_7", "type": "conversation", "position": {"x": 160, "y": 1670},
             "data": {"label": "Offer Campus Visit", "config": {
                 "prompt": "Offer a UMT campus visit or virtual guidance session. Ask whether the prospect wants a campus visit and, if yes, which date they prefer.",
                 "variables_to_extract": ["wants_visit", "preferred_date"],
                 "optional_inputs": ["preferred_date"],
             }}},
            {"id": "condition_3", "type": "condition", "position": {"x": 160, "y": 1840},
             "data": {"label": "Visit Requested?", "config": {"expression": "wants_visit == true"}}},
            {"id": "slot_validator_visit", "type": "slot_validator", "position": {"x": -80, "y": 2010},
             "data": {"label": "Validate Visit Date", "config": {"required_slots": ["preferred_date"], "on_exhausted": "end_call"}}},
            {"id": "collect_visit_date", "type": "conversation", "position": {"x": -400, "y": 2010},
             "data": {"label": "Collect Visit Date", "config": {"prompt": "Which date would work for your UMT campus visit?", "variables_to_extract": ["preferred_date"]}}},
            {"id": "end_visit_exhausted", "type": "end_call", "position": {"x": -400, "y": 2140},
             "data": {"label": "Visit Date Exhausted", "config": {"message": "I could not confirm a visit date, but your interest has been recorded and the admissions team can follow up. Thank you for your time."}}},
            {"id": "action_3", "type": "action", "position": {"x": -80, "y": 2180},
             "data": {"label": "Check Visit Availability", "config": {
                 "integration_type": "google_calendar",
                 "action": "check_availability",
                 "params": {"date": "{{preferred_date}}", "duration_minutes": 60, "business_hours_start": "09:00", "business_hours_end": "18:00"},
                 "required_inputs": ["preferred_date"],
             }}},
            {"id": "conversation_8", "type": "conversation", "position": {"x": -80, "y": 2350},
             "data": {"label": "Confirm Visit Slot", "config": {
                 "prompt": "Use the calendar availability in the flow context to offer a valid campus visit slot. Confirm the final date and time, then collect the prospect's email address for the visit confirmation. Do not claim the visit is booked yet.",
                 "variables_to_extract": ["preferred_date", "preferred_time", "caller_email"],
             }}},
            {"id": "slot_validator_booking", "type": "slot_validator", "position": {"x": -80, "y": 2520},
             "data": {"label": "Validate Visit Booking", "config": {"required_slots": ["preferred_date", "preferred_time", "caller_email"], "on_exhausted": "end_call"}}},
            {"id": "collect_booking_date", "type": "conversation", "position": {"x": -430, "y": 2460},
             "data": {"label": "Confirm Booking Date", "config": {"prompt": "Which available date should I confirm for your campus visit?", "variables_to_extract": ["preferred_date"]}}},
            {"id": "collect_booking_time", "type": "conversation", "position": {"x": -430, "y": 2570},
             "data": {"label": "Confirm Booking Time", "config": {"prompt": "Which available time should I confirm for your campus visit?", "variables_to_extract": ["preferred_time"]}}},
            {"id": "collect_booking_email", "type": "conversation", "position": {"x": -430, "y": 2680},
             "data": {"label": "Collect Confirmation Email", "config": {"prompt": "What email address should receive the campus visit confirmation?", "variables_to_extract": ["caller_email"]}}},
            {"id": "end_booking_exhausted", "type": "end_call", "position": {"x": -430, "y": 2790},
             "data": {"label": "Visit Booking Exhausted", "config": {"message": "I could not collect everything needed to book the visit. Your lead is recorded and the admissions team can contact you to arrange it. Thank you for your time."}}},
            {"id": "action_4", "type": "action", "position": {"x": -80, "y": 2710},
             "data": {"label": "Book Campus Visit", "config": {
                 "integration_type": "google_calendar",
                 "action": "create_event",
                 "params": {"title": "UMT Campus Visit - {{prospect_name}}", "date": "{{preferred_date}}", "time": "{{preferred_time}}", "duration_minutes": 60, "location": "UMT Main Campus, C-II Johar Town, Lahore", "description": "Prospect: {{prospect_name}}\nPhone: {{caller_phone}}\nEmail: {{caller_email}}\nProgram: {{program_interest}}\nScholarship indication: {{scholarship_tier}}"},
                 "required_inputs": ["prospect_name", "caller_phone", "caller_email", "program_interest", "preferred_date", "preferred_time"],
                 "optional_inputs": ["scholarship_tier"],
             }}},
            {"id": "conversation_9", "type": "conversation", "position": {"x": 470, "y": 2010},
             "data": {"label": "Choose Follow-up Channel", "config": {
                 "prompt": "Offer to send the relevant UMT program and scholarship information. Ask whether the prospect prefers email or another channel, and collect an email address only if email is selected.",
                 "variables_to_extract": ["contact_preference", "caller_email"],
                 "optional_inputs": ["caller_email"],
             }}},
            {"id": "condition_4", "type": "condition", "position": {"x": 470, "y": 2180},
             "data": {"label": "Email Follow-up?", "config": {"expression": "contact_preference == \"email\""}}},
            {"id": "email_1", "type": "send_email", "position": {"x": 160, "y": 2910},
             "data": {"label": "Send UMT Follow-up", "config": {
                 "to": "{{caller_email}}",
                 "subject": "UMT Program and Scholarship Follow-up for {{prospect_name}}",
                 "body": "Dear {{prospect_name}},\n\nThank you for speaking with UMT admissions about {{program_interest}}. Scholarship indication discussed on the call: {{scholarship_tier}}. Campus visit date: {{preferred_date}}. Campus visit time: {{preferred_time}}.\n\nFinal admission, fee, and scholarship decisions require official verification. Please visit admissions.umt.edu.pk for current details and the application.\n\nUMT Admissions",
                 "required_inputs": ["caller_email", "prospect_name"],
                 "optional_inputs": ["program_interest", "scholarship_tier", "preferred_date", "preferred_time"],
             }}},
            {"id": "end_2", "type": "end_call", "position": {"x": 160, "y": 3080},
             "data": {"label": "Outreach Complete", "config": {"message": "Thanks for your time, {{prospect_name}}. If you have any questions later, please contact UMT admissions or visit admissions dot UMT dot E-D-U dot P-K. Good luck with everything. Allah hafiz.", "error_message": "Your interest is recorded, but I could not complete one of the follow-up steps. A UMT admissions counselor can contact you. Thank you for your time."}}},
            {"id": "end_integration_error", "type": "end_call", "position": {"x": 470, "y": 2710},
             "data": {"label": "Outreach Integration Error", "config": {"message": "I have your details, but I could not complete the external follow-up right now. A UMT admissions counselor can contact you. Thank you for your time."}}},
        ],
        "edges": [
            {"source": "trigger_1", "target": "conversation_1"},
            {"source": "conversation_1", "target": "condition_1"},
            {"source": "condition_1", "target": "conversation_3", "label": "Yes"},
            {"source": "condition_1", "target": "conversation_2", "label": "No"},
            {"source": "conversation_2", "target": "end_1"},
            {"source": "conversation_3", "target": "conversation_4"},
            {"source": "conversation_4", "target": "conversation_5"},
            {"source": "conversation_5", "target": "condition_2"},
            {"source": "condition_2", "target": "conversation_6", "label": "Yes"},
            {"source": "condition_2", "target": "action_1", "label": "No"},
            {"source": "conversation_6", "target": "action_1"},
            {"source": "action_1", "target": "action_2", "label": "error"},
            {"source": "action_1", "target": "action_2"},
            {"source": "action_2", "target": "conversation_7"},
            {"source": "action_2", "target": "end_integration_error", "label": "error"},
            {"source": "conversation_7", "target": "condition_3"},
            {"source": "condition_3", "target": "slot_validator_visit", "label": "Yes"},
            {"source": "condition_3", "target": "conversation_9", "label": "No"},
            {"source": "slot_validator_visit", "target": "collect_visit_date", "label": "preferred_date"},
            {"source": "slot_validator_visit", "target": "action_3", "label": "done"},
            {"source": "slot_validator_visit", "target": "end_visit_exhausted", "label": "exhausted"},
            {"source": "collect_visit_date", "target": "slot_validator_visit"},
            {"source": "action_3", "target": "conversation_8"},
            {"source": "action_3", "target": "end_integration_error", "label": "error"},
            {"source": "conversation_8", "target": "slot_validator_booking"},
            {"source": "slot_validator_booking", "target": "collect_booking_date", "label": "preferred_date"},
            {"source": "slot_validator_booking", "target": "collect_booking_time", "label": "preferred_time"},
            {"source": "slot_validator_booking", "target": "collect_booking_email", "label": "caller_email"},
            {"source": "slot_validator_booking", "target": "action_4", "label": "done"},
            {"source": "slot_validator_booking", "target": "end_booking_exhausted", "label": "exhausted"},
            {"source": "collect_booking_date", "target": "slot_validator_booking"},
            {"source": "collect_booking_time", "target": "slot_validator_booking"},
            {"source": "collect_booking_email", "target": "slot_validator_booking"},
            {"source": "action_4", "target": "email_1"},
            {"source": "action_4", "target": "end_integration_error", "label": "error"},
            {"source": "conversation_9", "target": "condition_4"},
            {"source": "condition_4", "target": "email_1", "label": "Yes"},
            {"source": "condition_4", "target": "end_2", "label": "No"},
            {"source": "email_1", "target": "end_2"},
            {"source": "email_1", "target": "end_integration_error", "label": "error"},
        ],
    }


def _normalize_template_branch_handles(templates: list[dict]) -> list[dict]:
    """Make template branch contracts explicit and React Flow-compatible."""
    for index, original_template in enumerate(templates):
        template, repairs = add_missing_input_fallback_edges(original_template)
        templates[index] = template
        if repairs:
            logger.info(
                f"Added {len(repairs)} missing-input recovery edge(s) to "
                f"template '{template.get('id', 'unknown')}'"
            )
        node_types = {
            str(node.get("id")): str(node.get("type") or "")
            for node in template.get("nodes", [])
        }
        for edge in template.get("edges", []):
            if node_types.get(str(edge.get("source"))) != "condition":
                branch = edge_branch_key(edge)
                if branch in {"error", "on_error", "failure", "on_missing"}:
                    edge["sourceHandle"] = branch
                    if branch == "on_missing":
                        edge["label"] = "Missing info"
                continue
            label = str(edge.get("label") or "").strip().lower()
            if label in {"yes", "true"}:
                edge["sourceHandle"] = "yes"
                edge["label"] = "Yes"
            elif label in {"no", "false"}:
                edge["sourceHandle"] = "no"
                edge["label"] = "No"
    return templates


async def _ensure_single_agent_graph_owner(
    db: AsyncSession,
    user_id: int,
    agent_id: int,
    exclude_workflow_id: Optional[int] = None,
) -> None:
    """Prevent two active workflow records from silently owning one agent graph."""
    agent = await db.get(Agent, agent_id)
    if (
        agent is not None
        and agent.workflow_id is not None
        and agent.workflow_id != exclude_workflow_id
    ):
        linked = await db.get(Workflow, agent.workflow_id)
        if linked is not None and linked.is_active and linked.graph_json:
            raise ValidationError(
                field="agent_id",
                message=(
                    f"Agent {agent_id} already publishes conversational workflow "
                    f"'{linked.name}' (ID {linked.id})."
                ),
                suggestion=(
                    "Unassign or deactivate the published workflow before linking another graph."
                ),
            )

    query = select(Workflow).where(
        Workflow.user_id == user_id,
        Workflow.agent_id == agent_id,
        Workflow.is_active == True,
        Workflow.graph_json.is_not(None),
    )
    if exclude_workflow_id is not None:
        query = query.where(Workflow.id != exclude_workflow_id)
    conflict = (await db.execute(query.order_by(Workflow.id.asc()))).scalars().first()
    if conflict:
        raise ValidationError(
            field="agent_id",
            message=(
                f"Agent {agent_id} is already linked to active conversational workflow "
                f"'{conflict.name}' (ID {conflict.id})."
            ),
            suggestion=(
                "Unassign or deactivate the existing workflow before assigning this graph. "
                "An agent can execute only one canonical conversational graph."
            ),
        )


# ── Routes ─────────────────────────────────────────────────────────────

@router.get("/templates")
async def list_workflow_templates():
    """
    List pre-built workflow templates users can start from.

    Inspired by Retell AI's template gallery — each template provides
    a ready-to-use flow with nodes, edges, trigger phrases, and steps.
    Users can import a template and customize it.
    """
    return {
        "templates": _normalize_template_branch_handles([
            _umt_admission_template(),
            _umt_outreach_template(),
            {
                "id": "appointment_booking",
                "name": "Appointment Booking",
                "description": "Collect caller info, check availability, book with calendar, log to Sheets, notify staff on Slack, and send SMS confirmation.",
                "category": "scheduling",
                "icon": "calendar",
                "trigger_phrases": [
                    "schedule an appointment",
                    "book a meeting",
                    "I need to make an appointment",
                    "can I schedule a time",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Collect Details",
                              "config": {"prompt": "Greet the caller warmly and ask for their name, preferred date, preferred time, and the purpose of the appointment. Validate the date is in the future and not on a weekend unless the clinic is open Saturdays. If the caller is unsure of a specific date, offer to suggest the next available slot. Ask if they have a preferred staff member. Be friendly, concise, and conversational — don't sound like a form.",
                                         "variables_to_extract": ["preferred_date", "preferred_time", "appointment_purpose", "caller_name", "caller_phone", "preferred_staff"]}}},
                    {"id": "note_1", "type": "note", "position": {"x": 250, "y": 340},
                     "data": {"label": "Booking Policy Note",
                              "config": {"content": "CANCELLATION POLICY: Appointments can be cancelled or rescheduled up to 24 hours before the scheduled time. Same-day cancellations may incur a $25 fee. Remind the caller of this policy after booking is confirmed."}}},
                    {"id": "action_1", "type": "action", "position": {"x": 250, "y": 470},
                     "data": {"label": "Check Availability",
                              "config": {"integration_type": "google_calendar", "action": "check_availability",
                                         "params": {"date": "{{preferred_date}}", "time": "{{preferred_time}}"}}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 610},
                     "data": {"label": "Slot Available?", "config": {"expression": "result.requested_time_available == true"}}},
                    {"id": "action_2", "type": "action", "position": {"x": 100, "y": 750},
                     "data": {"label": "Create Event",
                              "config": {"integration_type": "google_calendar", "action": "create_event",
                                         "params": {"title": "Appointment - {{caller_name}}", "date": "{{preferred_date}}", "time": "{{preferred_time}}",
                                                    "description": "Purpose: {{appointment_purpose}}\nStaff: {{preferred_staff}}\nPhone: {{caller_phone}}"}}}},
                    {"id": "delay_1", "type": "delay", "position": {"x": 100, "y": 890},
                     "data": {"label": "Ensure Calendar Sync", "config": {"delay_seconds": 3}}},
                    {"id": "sheets_1", "type": "google_sheets", "position": {"x": 100, "y": 1010},
                     "data": {"label": "Log Booking",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{appointments_sheet_id}}", "range": "Bookings!A:G",
                                                    "values": ["{{current_date}}", "{{caller_name}}", "{{caller_phone}}", "{{preferred_date}}", "{{preferred_time}}", "{{appointment_purpose}}", "confirmed"]}}}},
                    {"id": "notification_1", "type": "notification", "position": {"x": 100, "y": 1140},
                     "data": {"label": "Notify Staff",
                              "config": {"channel": "slack", "message": "📅 New appointment booked: {{caller_name}} on {{preferred_date}} at {{preferred_time}}. Purpose: {{appointment_purpose}}. Staff: {{preferred_staff}}. Phone: {{caller_phone}}"}}},
                    {"id": "sms_1", "type": "send_sms", "position": {"x": 100, "y": 1270},
                     "data": {"label": "SMS Confirmation",
                              "config": {"to": "{{caller_phone}}",
                                         "body": "Your appointment on {{preferred_date}} at {{preferred_time}} is confirmed. Cancellations within 24h may incur a $25 fee. Reply CANCEL to cancel or RESCHEDULE to change. - VOIA"}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 100, "y": 1400},
                     "data": {"label": "Confirmed End",
                              "config": {"message": "Your appointment is confirmed for {{preferred_date}} at {{preferred_time}}, {{caller_name}}! You'll receive a text confirmation shortly. Just a reminder — cancellations within 24 hours may incur a fee. Have a wonderful day!"}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 400, "y": 750},
                     "data": {"label": "Suggest Alternatives",
                              "config": {"prompt": "That time is unavailable. Offer only real slots from the flow context, or ask for another date and time if none are listed. Never invent an opening.",
                                         "variables_to_extract": ["preferred_date", "preferred_time"]}}},
                    {"id": "condition_retry", "type": "condition", "position": {"x": 400, "y": 890},
                     "data": {"label": "Retries Left?", "config": {"expression": "_slot_retry_count < 2"}}},
                    {"id": "end_retry", "type": "end_call", "position": {"x": 400, "y": 1030},
                     "data": {"label": "No Suitable Slot", "config": {"message": "I could not confirm an available time after several checks. Please contact the scheduling team to finish the booking."}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "note_1"},
                    {"source": "note_1", "target": "action_1"},
                    {"source": "action_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "action_2", "label": "Yes"},
                    {"source": "condition_1", "target": "conversation_2", "label": "No"},
                    {"source": "action_2", "target": "delay_1"},
                    {"source": "delay_1", "target": "sheets_1"},
                    {"source": "sheets_1", "target": "notification_1"},
                    {"source": "notification_1", "target": "sms_1"},
                    {"source": "sms_1", "target": "end_1"},
                    {"source": "conversation_2", "target": "condition_retry"},
                    {"source": "condition_retry", "target": "action_1", "label": "Yes"},
                    {"source": "condition_retry", "target": "end_retry", "label": "No"},
                ],
            },
            {
                "id": "customer_support",
                "name": "Customer Support Triage",
                "description": "Greet caller, search & rank KB results with AI, resolve or escalate with full logging and Slack alerts.",
                "category": "support",
                "icon": "headphones",
                "trigger_phrases": [
                    "I need help",
                    "customer support",
                    "I have a problem",
                    "technical issue",
                    "billing question",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Identify Issue",
                              "config": {"prompt": "Greet the caller warmly and ask them to describe their issue in detail. Classify the issue into one of: billing, technical, general_inquiry, complaint, account_access, or feature_request. Also assess urgency as high, medium, or low based on language and impact. Ask follow-up questions if the description is vague. Be empathetic and professional.",
                                         "variables_to_extract": ["issue_type", "issue_description", "urgency_level", "caller_name", "account_id"]}}},
                    {"id": "kb_1", "type": "knowledge_base", "position": {"x": 250, "y": 350},
                     "data": {"label": "Search Knowledge Base",
                              "config": {"query": "{{issue_type}} {{issue_description}}", "max_results": 5}}},
                    {"id": "llm_1", "type": "llm_process", "position": {"x": 250, "y": 500},
                     "data": {"label": "Rank KB Results",
                              "config": {"prompt": "Given the user's issue (type={{issue_type}}, description={{issue_description}}, urgency={{urgency_level}}) and the knowledge base results, rank the top 3 most relevant articles. For each, provide a confidence score (0-100) and a brief summary of how it addresses the issue. If no results are relevant, state 'NO_MATCH'.",
                                         "max_tokens": 600}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 650},
                     "data": {"label": "KB Has Answer?", "config": {"expression": "llm_result != NO_MATCH"}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 100, "y": 800},
                     "data": {"label": "Provide Solution",
                              "config": {"prompt": "Using the ranked knowledge base results, walk the caller through the solution step by step. Be clear and patient. After explaining, ask: 'Did this resolve your issue?' If the caller says yes, confirm resolution. If no, ask what specifically didn't work.",
                                         "variables_to_extract": ["resolved", "resolution_notes"]}}},
                    {"id": "condition_2", "type": "condition", "position": {"x": 100, "y": 950},
                     "data": {"label": "Resolved?", "config": {"expression": "resolved == yes"}}},
                    {"id": "sheets_1", "type": "google_sheets", "position": {"x": 100, "y": 1100},
                     "data": {"label": "Log Interaction",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{support_log_sheet_id}}", "range": "Interactions!A:G",
                                                    "values": ["{{current_date}}", "{{caller_name}}", "{{issue_type}}", "{{issue_description}}", "{{urgency_level}}", "resolved", "{{resolution_notes}}"]}}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 100, "y": 1250},
                     "data": {"label": "Resolved",
                              "config": {"message": "I'm glad we could resolve that for you, {{caller_name}}! You'll receive a summary email shortly. If anything else comes up, don't hesitate to call. Have a great day!"}}},
                    {"id": "notification_1", "type": "notification", "position": {"x": 400, "y": 800},
                     "data": {"label": "Alert Support Team",
                              "config": {"channel": "slack", "message": "📋 Support escalation needed: {{caller_name}} has a {{urgency_level}} urgency {{issue_type}} issue: \"{{issue_description}}\". No KB match found. Transferring to agent."}}},
                    {"id": "delay_1", "type": "delay", "position": {"x": 400, "y": 950},
                     "data": {"label": "Brief Pause", "config": {"delay_seconds": 5}}},
                    {"id": "transfer_1", "type": "transfer_call", "position": {"x": 400, "y": 1100},
                     "data": {"label": "Transfer to Agent",
                              "config": {"transfer_to": "+1234567890",
                                         "transfer_message": "I've alerted our support team about your issue. I'm connecting you with a specialist now — please stay on the line.",
                                         "whisper_message": "Incoming transfer: {{caller_name}} has a {{urgency_level}} urgency {{issue_type}} issue: {{issue_description}}. KB search found no match. Account ID: {{account_id}}."}}},
                    {"id": "sheets_2", "type": "google_sheets", "position": {"x": 400, "y": 1250},
                     "data": {"label": "Log Escalation",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{support_log_sheet_id}}", "range": "Escalations!A:F",
                                                    "values": ["{{current_date}}", "{{caller_name}}", "{{issue_type}}", "{{issue_description}}", "{{urgency_level}}", "escalated_to_agent"]}}}},
                    {"id": "end_escalated", "type": "end_call", "position": {"x": 400, "y": 1400},
                     "data": {"label": "Escalation Complete", "config": {"message": "Your issue has been handed to our support specialist."}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "kb_1"},
                    {"source": "kb_1", "target": "llm_1"},
                    {"source": "llm_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "conversation_2", "label": "Yes"},
                    {"source": "condition_1", "target": "notification_1", "label": "No"},
                    {"source": "conversation_2", "target": "condition_2"},
                    {"source": "condition_2", "target": "sheets_1", "label": "Yes"},
                    {"source": "condition_2", "target": "notification_1", "label": "No"},
                    {"source": "sheets_1", "target": "end_1"},
                    {"source": "notification_1", "target": "delay_1"},
                    {"source": "delay_1", "target": "transfer_1"},
                    {"source": "transfer_1", "target": "sheets_2"},
                    {"source": "sheets_2", "target": "end_escalated"},
                ],
            },
            {
                "id": "lead_qualification",
                "name": "Lead Qualification",
                "description": "Qualify leads with BANT scoring, route hot leads to immediate transfer, log to Sheets, and notify sales team.",
                "category": "sales",
                "icon": "user-check",
                "trigger_phrases": [
                    "I'm interested in your product",
                    "pricing information",
                    "I want to learn more",
                    "demo request",
                    "sales inquiry",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Qualify Lead (BANT)",
                              "config": {"prompt": "Welcome the caller and qualify them using BANT methodology: Budget (what's their budget range?), Authority (are they a decision-maker?), Need (what problem are they solving?), Timeline (when do they need a solution?). Ask naturally — weave questions into conversation, don't interrogate. Also collect: company name, their role/title, company size, and email. If they seem hesitant, explain why you're asking (to match them with the right solution).",
                                         "variables_to_extract": ["company_name", "caller_name", "caller_role", "company_size", "budget_range", "timeline", "caller_email", "authority_level", "pain_point"]}}},
                    {"id": "llm_1", "type": "llm_process", "position": {"x": 250, "y": 350},
                     "data": {"label": "Score Lead (0-100)",
                              "config": {"prompt": "Score this lead 0-100 using BANT criteria: Budget={{budget_range}}, Authority={{authority_level}}, Need={{pain_point}}, Timeline={{timeline}}, Company size={{company_size}}. Output a numeric score and a one-line rationale. Also classify as: hot (70+), warm (40-69), or cold (below 40).",
                                         "max_tokens": 300}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 500},
                     "data": {"label": "Hot Lead? (score>70)", "config": {"expression": "lead_score > 70"}}},
                    {"id": "transfer_1", "type": "transfer_call", "position": {"x": 100, "y": 650},
                     "data": {"label": "Immediate Sales Transfer",
                              "config": {"transfer_to": "{{sales_hotline_number}}",
                                         "transfer_message": "Based on what you've shared, I'd like to connect you directly with our sales team right away — they can help you get started immediately. One moment please.",
                                         "whisper_message": "HOT LEAD (score {{lead_score}}): {{caller_name}} from {{company_name}} ({{caller_role}}). Budget: {{budget_range}}. Need: {{pain_point}}. Timeline: {{timeline}}."}}},
                    {"id": "webhook_1", "type": "api_request", "position": {"x": 400, "y": 650},
                     "data": {"label": "Create CRM Contact",
                              "config": {"url": "{{crm_api_url}}/contacts", "method": "POST",
                                         "body": {"name": "{{caller_name}}", "email": "{{caller_email}}", "company": "{{company_name}}", "role": "{{caller_role}}", "company_size": "{{company_size}}", "budget": "{{budget_range}}", "timeline": "{{timeline}}", "lead_score": "{{lead_score}}", "source": "inbound_call"}}}},
                    {"id": "sheets_1", "type": "google_sheets", "position": {"x": 400, "y": 800},
                     "data": {"label": "Log Lead",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{leads_sheet_id}}", "range": "Leads!A:J",
                                                    "values": ["{{current_date}}", "{{caller_name}}", "{{company_name}}", "{{caller_role}}", "{{company_size}}", "{{budget_range}}", "{{timeline}}", "{{lead_score}}", "{{lead_classification}}", "{{caller_email}}"]}}}},
                    {"id": "notification_1", "type": "notification", "position": {"x": 400, "y": 950},
                     "data": {"label": "Notify Sales Team",
                              "config": {"channel": "slack", "message": "🔥 New {{lead_classification}} lead (score {{lead_score}}): {{caller_name}} from {{company_name}} — {{caller_role}}. Budget: {{budget_range}}. Need: {{pain_point}}. Timeline: {{timeline}}. Email: {{caller_email}}"}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 400, "y": 1100},
                     "data": {"label": "Notify Sales Team",
                              "config": {"to": "sales@company.com", "subject": "New {{lead_classification}} Lead: {{company_name}} (Score: {{lead_score}})",
                                         "body": "New lead from inbound call:\n\nName: {{caller_name}} ({{caller_role}})\nCompany: {{company_name}} ({{company_size}} employees)\nBudget: {{budget_range}}\nTimeline: {{timeline}}\nNeed: {{pain_point}}\nLead Score: {{lead_score}}/100 ({{lead_classification}})\nEmail: {{caller_email}}\nPhone: {{caller_phone}}"}}},
                    {"id": "sms_1", "type": "send_sms", "position": {"x": 400, "y": 1250},
                     "data": {"label": "SMS Follow-up",
                              "config": {"to": "{{caller_phone}}",
                                         "body": "Thanks for your interest, {{caller_name}}! Our sales team will reach out within 24 hours. In the meantime, check out our pricing page: {{pricing_url}}. - VOIA"}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 1400},
                     "data": {"label": "End Call",
                              "config": {"message": "Thank you for your interest in our product, {{caller_name}}! Based on your needs, I've flagged you for a priority follow-up. Our sales team will contact you within 24 hours. Have a wonderful day!"}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "llm_1"},
                    {"source": "llm_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "transfer_1", "label": "Yes"},
                    {"source": "condition_1", "target": "webhook_1", "label": "No"},
                    {"source": "webhook_1", "target": "sheets_1"},
                    {"source": "sheets_1", "target": "notification_1"},
                    {"source": "notification_1", "target": "email_1"},
                    {"source": "email_1", "target": "sms_1"},
                    {"source": "sms_1", "target": "end_1"},
                ],
            },
            {
                "id": "order_status",
                "name": "Order Status Inquiry",
                "description": "Look up order status via API and provide real-time updates to caller.",
                "category": "support",
                "icon": "package",
                "trigger_phrases": [
                    "check my order",
                    "order status",
                    "where is my order",
                    "track my package",
                    "delivery update",
                ],
                "nodes": [
                    {
                        "id": "trigger_1",
                        "type": "trigger",
                        "position": {"x": 250, "y": 50},
                        "data": {"label": "Call Received", "config": {}},
                    },
                    {
                        "id": "conversation_1",
                        "type": "conversation",
                        "position": {"x": 250, "y": 180},
                        "data": {
                            "label": "Get Order Number",
                            "config": {
                                "prompt": "Ask for the order number or the email address used for the order.",
                                "variables_to_extract": ["order_number", "customer_email"],
                            },
                        },
                    },
                    {
                        "id": "webhook_1",
                        "type": "api_request",
                        "position": {"x": 250, "y": 330},
                        "data": {
                            "label": "Lookup Order",
                            "config": {
                                "url": "{{order_api_url}}/orders/{{order_number}}",
                                "method": "GET",
                                "response_mappings": {
                                    "order_status": "$.status",
                                    "estimated_delivery": "$.estimated_delivery",
                                    "tracking_number": "$.tracking_number",
                                },
                            },
                        },
                    },
                    {
                        "id": "conversation_2",
                        "type": "conversation",
                        "position": {"x": 250, "y": 480},
                        "data": {
                            "label": "Share Status",
                            "config": {
                                "prompt": "Tell the caller: order status is {{order_status}}, estimated delivery is {{estimated_delivery}}, tracking number is {{tracking_number}}. Ask if they need anything else.",
                            },
                        },
                    },
                    {
                        "id": "end_1",
                        "type": "end_call",
                        "position": {"x": 250, "y": 620},
                        "data": {
                            "label": "End Call",
                            "config": {"message": "Thanks for checking in! Have a great day."},
                        },
                    },
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "webhook_1"},
                    {"source": "webhook_1", "target": "conversation_2"},
                    {"source": "conversation_2", "target": "end_1"},
                ],
            },
            {
                "id": "after_hours",
                "name": "After-Hours Handler",
                "description": "Handle calls outside business hours with voicemail and callback scheduling.",
                "category": "routing",
                "icon": "moon",
                "trigger_phrases": [],
                "nodes": [
                    {
                        "id": "trigger_1",
                        "type": "trigger",
                        "position": {"x": 250, "y": 50},
                        "data": {"label": "Call Received", "config": {}},
                    },
                    {
                        "id": "conversation_1",
                        "type": "conversation",
                        "position": {"x": 250, "y": 180},
                        "data": {
                            "label": "After-Hours Greeting",
                            "config": {
                                "prompt": "Inform the caller that the office is currently closed. Ask if they'd like to leave a message or schedule a callback.",
                                "variables_to_extract": ["preference", "callback_time", "message_content"],
                            },
                        },
                    },
                    {
                        "id": "condition_1",
                        "type": "condition",
                        "position": {"x": 250, "y": 350},
                        "data": {
                            "label": "Wants Callback?",
                            "config": {"expression": "preference == callback"},
                        },
                    },
                    {
                        "id": "action_1",
                        "type": "action",
                        "position": {"x": 100, "y": 500},
                        "data": {
                            "label": "Schedule Callback",
                            "config": {
                                "integration_type": "google_calendar",
                                "action": "create_event",
                                "params": {
                                    "title": "Callback - {{caller_phone}}",
                                    "date": "{{callback_time}}",
                                    "description": "Caller requested callback. Message: {{message_content}}",
                                },
                            },
                        },
                    },
                    {
                        "id": "email_1",
                        "type": "send_email",
                        "position": {"x": 400, "y": 500},
                        "data": {
                            "label": "Email Voicemail",
                            "config": {
                                "to": "reception@company.com",
                                "subject": "Voicemail from {{caller_phone}}",
                                "body": "After-hours voicemail:\\n\\nFrom: {{caller_phone}}\\nMessage: {{message_content}}\\nTime: {{call_time}}",
                            },
                        },
                    },
                    {
                        "id": "end_1",
                        "type": "end_call",
                        "position": {"x": 250, "y": 650},
                        "data": {
                            "label": "End Call",
                            "config": {"message": "Thank you! We'll follow up with you during business hours. Goodbye!"},
                        },
                    },
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "action_1", "label": "Yes"},
                    {"source": "condition_1", "target": "email_1", "label": "No"},
                    {"source": "action_1", "target": "end_1"},
                    {"source": "email_1", "target": "end_1"},
                ],
            },
            # ═══════════════════════════════════════════════════════════
            # NEW TEMPLATES — Inspired by Synthflow, Retell AI, Vapi
            # ═══════════════════════════════════════════════════════════
            {
                "id": "healthcare_reminder",
                "name": "Healthcare Appointment Reminder",
                "description": "Call patients to remind them of upcoming appointments. Offer rescheduling or cancellation options.",
                "category": "healthcare",
                "icon": "heart-pulse",
                "trigger_phrases": [],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Outbound Call", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Confirm Appointment",
                              "config": {"prompt": "Hello, this is a reminder from {{clinic_name}}. You have an appointment on {{appointment_date}} at {{appointment_time}} with {{doctor_name}}. Can you confirm you'll attend?",
                                         "variables_to_extract": ["confirmation_status"]}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 340},
                     "data": {"label": "Confirmed?", "config": {"expression": "confirmation_status == confirmed"}}},
                    {"id": "sms_1", "type": "send_sms", "position": {"x": 80, "y": 490},
                     "data": {"label": "Send Confirmation SMS",
                              "config": {"to": "{{patient_phone}}", "body": "Confirmed: Your appointment with {{doctor_name}} on {{appointment_date}} at {{appointment_time}}. Reply CANCEL to cancel."}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 420, "y": 490},
                     "data": {"label": "Reschedule Flow",
                              "config": {"prompt": "No problem! When would you prefer to reschedule? I can check availability for you.",
                                         "variables_to_extract": ["new_date", "new_time"]}}},
                    {"id": "action_1", "type": "action", "position": {"x": 420, "y": 650},
                     "data": {"label": "Update Calendar",
                              "config": {"integration_type": "google_calendar", "action": "create_event",
                                         "params": {"title": "{{patient_name}} - Rescheduled", "date": "{{new_date}}", "time": "{{new_time}}"}}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 800},
                     "data": {"label": "End Call", "config": {"message": "Thank you! Take care and we'll see you at your appointment."}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "sms_1", "label": "Yes"},
                    {"source": "condition_1", "target": "conversation_2", "label": "No"},
                    {"source": "sms_1", "target": "end_1"},
                    {"source": "conversation_2", "target": "action_1"},
                    {"source": "action_1", "target": "end_1"},
                ],
            },
            {
                "id": "real_estate_inquiry",
                "name": "Real Estate Property Inquiry",
                "description": "Handle inbound calls about property listings. Collect buyer preferences and schedule viewings.",
                "category": "real_estate",
                "icon": "home",
                "trigger_phrases": [
                    "I'm looking for a property",
                    "house for sale",
                    "I want to buy a house",
                    "property listing",
                    "schedule a viewing",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Gather Preferences",
                              "config": {"prompt": "Welcome! I'd love to help you find the perfect property. What area are you looking in? What's your budget range? How many bedrooms do you need?",
                                         "variables_to_extract": ["location", "budget_range", "bedrooms", "property_type", "buyer_name", "buyer_email"]}}},
                    {"id": "webhook_1", "type": "api_request", "position": {"x": 250, "y": 350},
                     "data": {"label": "Search Listings",
                              "config": {"url": "{{listings_api}}/search", "method": "GET",
                                         "response_mappings": {"listing_count": "$.total", "top_listing": "$.listings[0].address"}}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 250, "y": 500},
                     "data": {"label": "Present Options",
                              "config": {"prompt": "I found {{listing_count}} properties matching your criteria. The top match is at {{top_listing}}. Would you like to schedule a viewing?",
                                         "variables_to_extract": ["wants_viewing", "preferred_viewing_date"]}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 660},
                     "data": {"label": "Wants Viewing?", "config": {"expression": "wants_viewing == yes"}}},
                    {"id": "action_1", "type": "action", "position": {"x": 100, "y": 810},
                     "data": {"label": "Schedule Viewing",
                              "config": {"integration_type": "google_calendar", "action": "create_event",
                                         "params": {"title": "Viewing - {{buyer_name}}", "date": "{{preferred_viewing_date}}", "description": "Property viewing at {{top_listing}}"}}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 100, "y": 960},
                     "data": {"label": "Send Details",
                              "config": {"to": "{{buyer_email}}", "subject": "Your Property Viewing Details",
                                         "body": "Hi {{buyer_name}},\n\nYour viewing is scheduled for {{preferred_viewing_date}}.\nProperty: {{top_listing}}\n\nOur agent will meet you there."}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 1100},
                     "data": {"label": "End Call", "config": {"message": "Great! We've sent you the details via email. Our agent will meet you at the property. Have a lovely day!"}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "webhook_1"},
                    {"source": "webhook_1", "target": "conversation_2"},
                    {"source": "conversation_2", "target": "condition_1"},
                    {"source": "condition_1", "target": "action_1", "label": "Yes"},
                    {"source": "condition_1", "target": "end_1", "label": "No"},
                    {"source": "action_1", "target": "email_1"},
                    {"source": "email_1", "target": "end_1"},
                ],
            },
            {
                "id": "restaurant_reservation",
                "name": "Restaurant Reservation",
                "description": "Book restaurant tables, handle dietary requirements, and confirm via SMS.",
                "category": "hospitality",
                "icon": "utensils",
                "trigger_phrases": [
                    "make a reservation",
                    "book a table",
                    "restaurant booking",
                    "I'd like to reserve a table",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Booking Details",
                              "config": {"prompt": "Welcome to {{restaurant_name}}! I'd be happy to help with a reservation. What date and time would you prefer? How many guests? Any dietary requirements or special occasions?",
                                         "variables_to_extract": ["reservation_date", "reservation_time", "party_size", "dietary_needs", "special_occasion", "guest_name"]}}},
                    {"id": "action_1", "type": "action", "position": {"x": 250, "y": 370},
                     "data": {"label": "Check Availability",
                              "config": {"integration_type": "google_calendar", "action": "check_availability",
                                         "params": {"date": "{{reservation_date}}", "time": "{{reservation_time}}"}}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 520},
                     "data": {"label": "Table Available?", "config": {"expression": "result.requested_time_available == true"}}},
                    {"id": "action_2", "type": "action", "position": {"x": 100, "y": 670},
                     "data": {"label": "Create Reservation",
                              "config": {"integration_type": "google_calendar", "action": "create_event",
                                         "params": {"title": "Reservation - {{guest_name}} ({{party_size}})", "date": "{{reservation_date}}", "time": "{{reservation_time}}",
                                                    "description": "Party: {{party_size}}, Dietary: {{dietary_needs}}, Occasion: {{special_occasion}}"}}}},
                    {"id": "sms_1", "type": "send_sms", "position": {"x": 100, "y": 820},
                     "data": {"label": "Confirm SMS",
                              "config": {"to": "{{caller_phone}}", "body": "Reservation confirmed at {{restaurant_name}}! Date: {{reservation_date}} Time: {{reservation_time}} Party: {{party_size}}. Reply CANCEL to cancel."}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 400, "y": 670},
                     "data": {"label": "Suggest Alternatives",
                              "config": {"prompt": "Sorry, that time is fully booked. Offer only real openings from the flow context, or ask for another date and time if no openings are listed.",
                                         "variables_to_extract": ["reservation_date", "reservation_time"]}}},
                    {"id": "condition_retry", "type": "condition", "position": {"x": 400, "y": 820},
                     "data": {"label": "Retries Left?", "config": {"expression": "_slot_retry_count < 2"}}},
                    {"id": "end_retry", "type": "end_call", "position": {"x": 550, "y": 960},
                     "data": {"label": "No Suitable Table", "config": {"message": "I could not confirm an available table after several checks. Please contact the restaurant directly for help."}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 960},
                     "data": {"label": "End Call", "config": {"message": "Your reservation is confirmed! We look forward to seeing you. Bon appétit!"}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "action_1"},
                    {"source": "action_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "action_2", "label": "Yes"},
                    {"source": "condition_1", "target": "conversation_2", "label": "No"},
                    {"source": "action_2", "target": "sms_1"},
                    {"source": "sms_1", "target": "end_1"},
                    {"source": "conversation_2", "target": "condition_retry"},
                    {"source": "condition_retry", "target": "action_1", "label": "Yes"},
                    {"source": "condition_retry", "target": "end_retry", "label": "No"},
                ],
            },
            {
                "id": "insurance_claims",
                "name": "Insurance Claims Intake",
                "description": "Collect initial claim information, create a ticket, and route to claims adjuster if needed.",
                "category": "insurance",
                "icon": "shield",
                "trigger_phrases": [
                    "file a claim",
                    "insurance claim",
                    "I need to report an incident",
                    "claim number",
                    "accident report",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Verify Identity",
                              "config": {"prompt": "I'm sorry to hear about your situation. For security, can you please provide your policy number and the name on the policy?",
                                         "variables_to_extract": ["policy_number", "policy_holder_name", "date_of_birth"]}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 250, "y": 340},
                     "data": {"label": "Gather Claim Details",
                              "config": {"prompt": "Thank you. Please describe the incident — when did it happen, what occurred, and was anyone injured?",
                                         "variables_to_extract": ["incident_date", "incident_description", "injury_reported", "claim_type", "estimated_damage"]}}},
                    {"id": "webhook_1", "type": "api_request", "position": {"x": 250, "y": 500},
                     "data": {"label": "Create Claim",
                              "config": {"url": "{{claims_api}}/claims", "method": "POST",
                                         "body": {"policy_number": "{{policy_number}}", "incident_date": "{{incident_date}}", "description": "{{incident_description}}", "type": "{{claim_type}}"},
                                         "response_mappings": {"claim_number": "$.claim_id"}}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 650},
                     "data": {"label": "Injury Reported?", "config": {"expression": "injury_reported == yes"}}},
                    {"id": "transfer_1", "type": "transfer_call", "position": {"x": 100, "y": 800},
                     "data": {"label": "Priority Transfer",
                              "config": {"transfer_to": "{{priority_claims_dept}}", "transfer_message": "I'm transferring you to a priority claims specialist right away.",
                                         "whisper_message": "Priority claim #{{claim_number}} — injury reported. Policy: {{policy_number}}"}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 400, "y": 800},
                     "data": {"label": "Email Confirmation",
                              "config": {"to": "{{caller_email}}", "subject": "Claim #{{claim_number}} Filed Successfully",
                                         "body": "Dear {{policy_holder_name}},\n\nYour claim #{{claim_number}} has been filed.\nType: {{claim_type}}\nDate: {{incident_date}}\n\nA claims adjuster will contact you within 48 hours."}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 400, "y": 950},
                     "data": {"label": "End Call", "config": {"message": "Your claim number is {{claim_number}}. You'll receive an email confirmation shortly. Thank you for calling."}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "conversation_2"},
                    {"source": "conversation_2", "target": "webhook_1"},
                    {"source": "webhook_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "transfer_1", "label": "Yes"},
                    {"source": "condition_1", "target": "email_1", "label": "No"},
                    {"source": "email_1", "target": "end_1"},
                ],
            },
            {
                "id": "interview_scheduling",
                "name": "Recruitment Interview Scheduling",
                "description": "Screen candidates, collect information, and schedule interviews.",
                "category": "recruitment",
                "icon": "briefcase",
                "trigger_phrases": [
                    "schedule an interview",
                    "I applied for a job",
                    "interview scheduling",
                    "I'm calling about a job application",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Verify Application",
                              "config": {"prompt": "Thank you for your interest! Can you share your full name, the position you applied for, and your application reference number?",
                                         "variables_to_extract": ["candidate_name", "position_applied", "reference_number", "candidate_email"]}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 250, "y": 340},
                     "data": {"label": "Pre-Screen Questions",
                              "config": {"prompt": "Great. I have a few quick screening questions: What's your earliest available start date? What are your salary expectations? Are you authorized to work in this country?",
                                         "variables_to_extract": ["start_date", "salary_expectations", "work_authorization", "years_experience"]}}},
                    {"id": "action_1", "type": "action", "position": {"x": 250, "y": 500},
                     "data": {"label": "Schedule Interview",
                              "config": {"integration_type": "google_calendar", "action": "create_event",
                                         "params": {"title": "Interview - {{candidate_name}} ({{position_applied}})", "date": "{{next_business_day}}",
                                                    "description": "Candidate: {{candidate_name}}\nPosition: {{position_applied}}\nExperience: {{years_experience}} years\nSalary: {{salary_expectations}}"}}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 250, "y": 650},
                     "data": {"label": "Send Interview Details",
                              "config": {"to": "{{candidate_email}}", "subject": "Interview Scheduled — {{position_applied}}",
                                         "body": "Hi {{candidate_name}},\n\nYour interview for {{position_applied}} has been scheduled.\n\nPlease prepare to discuss your experience and qualifications.\n\nBest regards,\n{{company_name}} HR Team"}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 800},
                     "data": {"label": "End Call", "config": {"message": "Your interview is scheduled! We've sent the details to your email. Good luck, {{candidate_name}}!"}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "conversation_2"},
                    {"source": "conversation_2", "target": "action_1"},
                    {"source": "action_1", "target": "email_1"},
                    {"source": "email_1", "target": "end_1"},
                ],
            },
            {
                "id": "ecommerce_returns",
                "name": "E-Commerce Return Processing",
                "description": "Handle returns with Shopify order lookup, Stripe refund check, AI resolution suggestion, Sheets logging, and manager alerts for high-value returns.",
                "category": "ecommerce",
                "icon": "package-x",
                "trigger_phrases": [
                    "I want to return",
                    "return a product",
                    "refund request",
                    "exchange an item",
                    "return policy",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Get Order Info",
                              "config": {"prompt": "Thank you for calling {{store_name}} support. I'm sorry to hear you need to return something. To get started, may I have your order number? Also, could you tell me the reason for the return and the current condition of the item — is it unopened, opened but unused, or used? This helps me determine the best resolution for you.",
                                         "variables_to_extract": ["order_number", "return_reason", "item_condition", "customer_email", "product_name"]}}},
                    {"id": "shopify_1", "type": "shopify", "position": {"x": 250, "y": 340},
                     "data": {"label": "Lookup Order (Shopify)",
                              "config": {"integration_type": "shopify", "action": "get_order",
                                         "params": {"order_id": "{{order_number}}"}}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 490},
                     "data": {"label": "Return Eligible?", "config": {"expression": "returnable == true"}}},
                    {"id": "llm_1", "type": "llm_process", "position": {"x": 100, "y": 640},
                     "data": {"label": "Suggest Resolution",
                              "config": {"prompt": "Based on return_reason={{return_reason}}, item_condition={{item_condition}}, order_total={{order_total}}, and product={{product_name}}, suggest the best resolution: full_refund, partial_refund, exchange, or store_credit. Consider: if item is unopened → full refund; opened but unused → partial refund or exchange; used → store_credit only. Provide a brief rationale.",
                                         "max_tokens": 300}}},
                    {"id": "stripe_1", "type": "stripe", "position": {"x": 100, "y": 790},
                     "data": {"label": "Check Refund Status",
                              "config": {"integration_type": "stripe", "action": "check_payment_status",
                                         "params": {"payment_intent": "{{order.payment_intent_id}}"}}}},
                    {"id": "shopify_2", "type": "shopify", "position": {"x": 100, "y": 940},
                     "data": {"label": "Search Orders (Shopify)",
                              "config": {"integration_type": "shopify", "action": "search_orders",
                                         "params": {"query": "{{order_number}}", "reason": "{{return_reason}}", "condition": "{{item_condition}}", "resolution": "{{suggested_resolution}}"}}}},
                    {"id": "sheets_1", "type": "google_sheets", "position": {"x": 100, "y": 1090},
                     "data": {"label": "Log Return",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{returns_sheet_id}}", "range": "Returns!A:I",
                                                    "values": ["{{current_date}}", "{{order_number}}", "{{customer_email}}", "{{product_name}}", "{{return_reason}}", "{{item_condition}}", "{{suggested_resolution}}", "{{order_total}}", "processed"]}}}},
                    {"id": "condition_2", "type": "condition", "position": {"x": 100, "y": 1240},
                     "data": {"label": "High Value? (>$500)", "config": {"expression": "order_total > 500"}}},
                    {"id": "notification_1", "type": "notification", "position": {"x": 100, "y": 1390},
                     "data": {"label": "Alert Manager",
                              "config": {"channel": "slack", "message": "⚠️ High-value return: Order #{{order_number}} — {{product_name}} (${{order_total}}). Reason: {{return_reason}}. Resolution: {{suggested_resolution}}. Customer: {{customer_email}}"}}},
                    {"id": "sms_1", "type": "send_sms", "position": {"x": 400, "y": 1390},
                     "data": {"label": "Send Return Label",
                              "config": {"to": "{{caller_phone}}",
                                         "body": "Your return #{{order_number}} is approved! Resolution: {{suggested_resolution}}. Download your shipping label: {{return_label_url}}. Refund will be processed in 3-5 business days."}}},
                    {"id": "send_email_1", "type": "send_email", "position": {"x": 400, "y": 1540},
                     "data": {"label": "Return Confirmation Email",
                              "config": {"to": "{{customer_email}}", "subject": "Return Confirmation — Order #{{order_number}}",
                                         "body": "Hi,\n\nYour return for order #{{order_number}} has been processed.\n\nProduct: {{product_name}}\nReason: {{return_reason}}\nResolution: {{suggested_resolution}}\n\nYour shipping label and refund details have been sent to your phone.\n\nThank you,\n{{store_name}}"}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 400, "y": 640},
                     "data": {"label": "Explain Policy",
                              "config": {"prompt": "I'm sorry, but this order is outside our 30-day return window. I understand this is frustrating. Let me explain our policy: returns are accepted within 30 days of delivery for unopened items, and within 14 days for opened items. However, I can offer you store credit or help you reach a supervisor who may make an exception. What would you prefer?",
                                         "variables_to_extract": ["wants_supervisor", "wants_store_credit"]}}},
                    {"id": "condition_3", "type": "condition", "position": {"x": 400, "y": 790},
                     "data": {"label": "Wants Supervisor?", "config": {"expression": "wants_supervisor == yes"}}},
                    {"id": "transfer_1", "type": "transfer_call", "position": {"x": 400, "y": 940},
                     "data": {"label": "Transfer to Supervisor",
                              "config": {"transfer_to": "{{supervisor_number}}",
                                         "transfer_message": "I'm connecting you with a supervisor who can review your case. Please hold for a moment.",
                                         "whisper_message": "Return exception request: Order #{{order_number}}, {{product_name}} ({{order_total}}). Outside return window. Customer wants supervisor review."}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 1690},
                     "data": {"label": "End Call",
                              "config": {"message": "Your return has been processed, and the shipping label has been sent to your phone. Your refund will be processed within 3-5 business days. Thank you for shopping with {{store_name}}!"}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "shopify_1"},
                    {"source": "shopify_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "llm_1", "label": "Yes"},
                    {"source": "condition_1", "target": "conversation_2", "label": "No"},
                    {"source": "llm_1", "target": "stripe_1"},
                    {"source": "stripe_1", "target": "shopify_2"},
                    {"source": "shopify_2", "target": "sheets_1"},
                    {"source": "sheets_1", "target": "condition_2"},
                    {"source": "condition_2", "target": "notification_1", "label": "Yes"},
                    {"source": "condition_2", "target": "sms_1", "label": "No"},
                    {"source": "notification_1", "target": "sms_1"},
                    {"source": "sms_1", "target": "send_email_1"},
                    {"source": "send_email_1", "target": "end_1"},
                    {"source": "conversation_2", "target": "condition_3"},
                    {"source": "condition_3", "target": "transfer_1", "label": "Yes"},
                    {"source": "condition_3", "target": "end_1", "label": "No"},
                ],
            },
            {
                "id": "smilecare_dental",
                "agent_template_id": "smilecare",
                "name": "SmileCare Dental Receptionist",
                "description": "Dental receptionist for emergency triage and appointment booking with existing-patient lookup, exact-time calendar validation, patient logging, optional insurance capture, and email confirmation.",
                "category": "healthcare",
                "icon": "smile",
                "trigger_phrases": [
                    "book a dental appointment",
                    "I need to see the dentist",
                    "dental cleaning",
                    "tooth pain",
                    "dental emergency",
                    "teeth whitening",
                    "braces consultation",
                    "root canal",
                    "dant ka dard",
                    "scaling karwani hai",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 480, "y": 40},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 480, "y": 200},
                     "data": {"label": "Identify Need", "config": {
                         "prompt": "Ask the caller whether they need to book an appointment or have a dental emergency. Speak only to the caller. Do not narrate instructions or coaching.",
                         "variables_to_extract": ["visit_type", "is_emergency", "patient_name"],
                         "optional_inputs": ["patient_name"],
                     }}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 480, "y": 380},
                     "data": {"label": "Emergency?", "config": {"expression": "is_emergency == true"}}},
                    {"id": "note_1", "type": "note", "position": {"x": 80, "y": 560},
                     "data": {"label": "Emergency First-Aid Instructions", "config": {"content": "Knocked-out tooth: hold only the crown and keep it in milk or saliva. Continuous bleeding: bite firmly on clean gauze for 20 to 30 minutes. Severe toothache with swelling: use a cold compress and seek urgent dental care. Fever with an abscess or a jaw injury requires emergency medical assessment. Do not diagnose. Direct severe or worsening cases to emergency services. SmileCare emergency line: 0300-1234567."}}},
                    {"id": "conversation_emergency", "type": "conversation", "position": {"x": 80, "y": 740},
                     "data": {"label": "Emergency Guidance", "config": {
                         "prompt": "Give only the first-aid guidance relevant to what the caller described, calmly direct them to the SmileCare emergency line at 0300-1234567, and tell them to seek emergency medical care if symptoms are severe or worsening. Ask whether they understand the immediate next step.",
                         "variables_to_extract": ["understood_instructions"],
                         "optional_inputs": ["understood_instructions"],
                     }}},
                    {"id": "end_emergency", "type": "end_call", "position": {"x": 80, "y": 920},
                     "data": {"label": "Emergency End", "config": {"message": "Please call 0300-1234567 now for urgent dental help. If the symptoms are severe or getting worse, go to the nearest emergency department. Take care."}}},
                    {"id": "action_1", "type": "action", "position": {"x": 800, "y": 560},
                     "data": {"label": "Check Existing Patient", "config": {
                         "integration_type": "google_sheets", "action": "read_rows",
                         "params": {"range": "Sheet1!A:K", "max_rows": 200},
                         "required_inputs": ["patient_name"], "prefill": True, "has_header": True,
                         "prefill_match_column": 1, "prefill_match_value": "{{patient_name}}",
                         "prefill_mapping": {"1": "patient_name", "2": "caller_phone", "3": "caller_email", "4": "service_requested", "5": "preferred_dentist", "8": "is_new_patient", "9": "insurance_provider"},
                     }}},
                    {"id": "condition_patient_found", "type": "condition", "position": {"x": 800, "y": 740},
                     "data": {"label": "Patient Found?", "config": {"expression": "result.rows not_empty"}}},
                    {"id": "note_prefill", "type": "note", "position": {"x": 480, "y": 920},
                     "data": {"label": "Confirm Existing Info", "config": {"content": "An existing record was found. Confirm saved contact details with the caller; never assume they are still current."}}},
                    {"id": "conversation_contact", "type": "conversation", "position": {"x": 800, "y": 920},
                     "data": {"label": "Contact Details", "config": {
                         "prompt": "Collect or confirm the patient's full name, callback phone number, and email address. Ask one question at a time.",
                         "variables_to_extract": ["patient_name", "caller_phone", "caller_email"],
                     }}},
                    {"id": "conversation_visit", "type": "conversation", "position": {"x": 800, "y": 1100},
                     "data": {"label": "Visit Details", "config": {
                         "prompt": "Ask what dental service the patient needs and whether they are a new or existing patient.",
                         "variables_to_extract": ["service_requested", "is_new_patient"],
                     }}},
                    {"id": "conversation_schedule", "type": "conversation", "position": {"x": 800, "y": 1280},
                     "data": {"label": "Date and Time", "config": {
                         "prompt": "Ask for the preferred appointment date and time. SmileCare is open Monday to Saturday from 10 AM to 9 PM and Sunday from 2 PM to 8 PM.",
                         "variables_to_extract": ["preferred_date", "preferred_time"],
                     }}},
                    {"id": "conversation_dentist", "type": "conversation", "position": {"x": 800, "y": 1460},
                     "data": {"label": "Dentist Preference", "config": {
                         "prompt": "Ask whether the patient prefers a dentist. Offer Dr. Ayesha for orthodontics, Dr. Imran for oral surgery, Dr. Sana for cosmetic dentistry, Dr. Bilal for endodontics, Dr. Hina for pediatric dentistry, or Dr. Farhan for periodontics. Optionally note their insurance provider.",
                         "variables_to_extract": ["preferred_dentist", "insurance_provider"],
                         "optional_inputs": ["insurance_provider"],
                     }}},
                    {"id": "action_2", "type": "action", "position": {"x": 800, "y": 1640},
                     "data": {"label": "Check Requested Time", "config": {
                         "integration_type": "google_calendar", "action": "check_availability",
                         "params": {"date": "{{preferred_date}}", "time": "{{preferred_time}}", "duration_minutes": 30, "business_hours_start": "10:00", "business_hours_end": "21:00"},
                         "required_inputs": ["preferred_date", "preferred_time"],
                     }}},
                    {"id": "condition_missing", "type": "condition", "position": {"x": 1480, "y": 1820},
                     "data": {"label": "Missing Info Retries Left?", "config": {
                         "expression": "_slot_retry_count < 2",
                         "retry_mode": "active_action",
                         "retry_owner": "action_2",
                     }}},
                    {"id": "condition_2", "type": "condition", "position": {"x": 800, "y": 1820},
                     "data": {"label": "Requested Time Available?", "config": {"expression": "result.requested_time_available == true"}}},
                    {"id": "confirm_booking", "type": "conversation", "position": {"x": 560, "y": 2000},
                     "data": {"label": "Confirm Booking", "config": {
                         "prompt": "Confirm the date, time, dentist, and service with the caller, then ask for explicit permission to book it.",
                         "variables_to_extract": ["confirm_booking"],
                     }}},
                    {"id": "condition_confirm", "type": "condition", "position": {"x": 560, "y": 2180},
                     "data": {"label": "Booking Confirmed?", "config": {"expression": "confirm_booking == true"}}},
                    {"id": "conversation_4", "type": "conversation", "position": {"x": 1040, "y": 2000},
                     "data": {"label": "Offer Real Alternatives", "config": {
                         "prompt": "The requested time is unavailable. Offer only the available calendar slots shown in the flow context. Ask the caller to pick a different date and time. Never invent an opening and do not re-check the previous unavailable time.",
                         "variables_to_extract": ["preferred_date", "preferred_time"],
                         "reset_variables": ["preferred_date", "preferred_time"],
                     }}},
                    {"id": "condition_3", "type": "condition", "position": {"x": 1040, "y": 2180},
                     "data": {"label": "Retries Left?", "config": {
                         "expression": "_slot_retry_count < 2",
                         "retry_mode": "configured",
                         "retry_scope": "condition_3:alt_time_retry",
                     }}},
                    {"id": "action_3", "type": "action", "position": {"x": 560, "y": 2360},
                     "data": {"label": "Book Appointment", "config": {
                         "integration_type": "google_calendar", "action": "create_event",
                         "params": {"title": "{{service_requested}} - {{patient_name}}", "date": "{{preferred_date}}", "time": "{{preferred_time}}", "duration_minutes": 30, "description": "Patient: {{patient_name}}\nPhone: {{caller_phone}}\nService: {{service_requested}}\nDentist: {{preferred_dentist}}\nNew patient: {{is_new_patient}}\nClinic: SmileCare Dental, 42-C MM Alam Road, Gulberg III, Lahore"},
                         "required_inputs": ["preferred_date", "preferred_time", "patient_name", "caller_phone", "service_requested", "preferred_dentist"],
                     }}},
                    {"id": "sheets_1", "type": "google_sheets", "position": {"x": 560, "y": 2540},
                     "data": {"label": "Log Patient", "config": {
                         "integration_type": "google_sheets", "action": "append_row",
                         "required_inputs": ["current_date", "patient_name", "caller_phone", "caller_email", "service_requested", "preferred_dentist", "preferred_date", "preferred_time", "is_new_patient"],
                         "optional_inputs": ["insurance_provider"],
                         "params": {"range": "Sheet1!A:K", "values": ["{{current_date}}", "{{patient_name}}", "{{caller_phone}}", "{{caller_email}}", "{{service_requested}}", "{{preferred_dentist}}", "{{preferred_date}}", "{{preferred_time}}", "{{is_new_patient}}", "{{insurance_provider}}", "confirmed"]},
                     }}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 560, "y": 2720},
                     "data": {"label": "Appointment Email", "config": {
                         "to": "{{caller_email}}", "subject": "SmileCare Dental appointment confirmation for {{patient_name}}",
                         "body": "Dear {{patient_name}},\n\nYour SmileCare appointment is confirmed for {{preferred_date}} at {{preferred_time}} with {{preferred_dentist}} for {{service_requested}}.\n\nAddress: 42-C MM Alam Road, Gulberg III, Lahore. Please arrive 10 minutes early. For emergencies call 0300-1234567.\n\nSmileCare Dental Clinic",
                         "required_inputs": ["caller_email", "patient_name", "preferred_date", "preferred_time", "preferred_dentist", "service_requested"],
                     }}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 560, "y": 2900},
                     "data": {"label": "Booking Complete", "config": {"message": "Your appointment is confirmed for {{preferred_date}} at {{preferred_time}} with {{preferred_dentist}}. A confirmation email has been sent. Please arrive 10 minutes early. Goodbye, and take care!"}}},
                    {"id": "end_no_slot", "type": "end_call", "position": {"x": 1040, "y": 2360},
                     "data": {"label": "No Suitable Slot", "config": {"message": "I could not find a suitable available time after several checks. Please call the front desk to arrange the appointment. Take care."}}},
                    {"id": "end_calendar_error", "type": "end_call", "position": {"x": 1200, "y": 1640},
                     "data": {"label": "Calendar Unavailable", "config": {"message": "I collected your preferred appointment details, but the calendar is unavailable right now. The front desk will need to confirm the time before it is booked."}}},
                    {"id": "end_booking_error", "type": "end_call", "position": {"x": 240, "y": 2360},
                     "data": {"label": "Booking Failed", "config": {"message": "I could not create the appointment in the calendar, so it is not confirmed yet. Please contact the front desk to complete the booking."}}},
                    {"id": "end_followup_error", "type": "end_call", "position": {"x": 240, "y": 2720},
                     "data": {"label": "Follow-up Failed", "config": {"message": "Your calendar appointment is confirmed, but I could not complete the patient log or confirmation email. Please note {{preferred_date}} at {{preferred_time}} and contact the front desk if you need written confirmation."}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "condition_1"},
                    {"source": "condition_1", "sourceHandle": "yes", "target": "note_1", "label": "Yes"},
                    {"source": "condition_1", "sourceHandle": "no", "target": "action_1", "label": "No"},
                    {"source": "note_1", "target": "conversation_emergency"},
                    {"source": "conversation_emergency", "target": "end_emergency"},
                    {"source": "action_1", "target": "condition_patient_found"},
                    {"source": "action_1", "target": "conversation_contact", "label": "error"},
                    {"source": "action_1", "sourceHandle": "on_missing", "target": "conversation_contact", "label": "Missing info"},
                    {"source": "condition_patient_found", "sourceHandle": "yes", "target": "note_prefill", "label": "Yes"},
                    {"source": "condition_patient_found", "sourceHandle": "no", "target": "conversation_contact", "label": "No"},
                    {"source": "note_prefill", "target": "conversation_contact"},
                    {"source": "conversation_contact", "target": "conversation_visit"},
                    {"source": "conversation_visit", "target": "conversation_schedule"},
                    {"source": "conversation_schedule", "target": "conversation_dentist"},
                    {"source": "conversation_dentist", "target": "action_2"},
                    {"source": "action_2", "target": "condition_2"},
                    {"source": "action_2", "target": "end_calendar_error", "label": "error"},
                    {"source": "action_2", "sourceHandle": "on_missing", "target": "condition_missing", "label": "Missing info"},
                    {"source": "condition_missing", "sourceHandle": "yes", "target": "conversation_schedule", "label": "Yes"},
                    {"source": "condition_missing", "sourceHandle": "no", "target": "end_no_slot", "label": "No"},
                    {"source": "condition_2", "sourceHandle": "yes", "target": "confirm_booking", "label": "Yes"},
                    {"source": "condition_2", "sourceHandle": "no", "target": "conversation_4", "label": "No"},
                    {"source": "confirm_booking", "target": "condition_confirm"},
                    {"source": "condition_confirm", "sourceHandle": "yes", "target": "action_3", "label": "Yes"},
                    {"source": "condition_confirm", "sourceHandle": "no", "target": "conversation_4", "label": "No"},
                    {"source": "conversation_4", "target": "condition_3"},
                    {"source": "condition_3", "sourceHandle": "yes", "target": "action_2", "label": "Yes"},
                    {"source": "condition_3", "sourceHandle": "no", "target": "end_no_slot", "label": "No"},
                    {"source": "action_3", "target": "sheets_1"},
                    {"source": "action_3", "target": "end_booking_error", "label": "error"},
                    {"source": "action_3", "sourceHandle": "on_missing", "target": "end_booking_error", "label": "Missing info"},
                    {"source": "sheets_1", "target": "email_1"},
                    {"source": "sheets_1", "target": "end_followup_error", "label": "error"},
                    {"source": "sheets_1", "sourceHandle": "on_missing", "target": "end_followup_error", "label": "Missing info"},
                    {"source": "email_1", "target": "end_1"},
                    {"source": "email_1", "target": "end_followup_error", "label": "error"},
                    {"source": "email_1", "sourceHandle": "on_missing", "target": "end_followup_error", "label": "Missing info"},
                ],
            },
            {
                "id": "hotel_concierge",
                "name": "Hotel Booking Concierge",
                "description": "Handle hotel room inquiries, check availability, process bookings, and send confirmation.",
                "category": "hospitality",
                "icon": "building",
                "trigger_phrases": [
                    "book a room",
                    "hotel reservation",
                    "room availability",
                    "I'd like to stay at your hotel",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Guest Requirements",
                              "config": {"prompt": "Welcome to {{hotel_name}}! When would you like to check in and check out? How many guests? Do you have a room type preference — standard, deluxe, or suite?",
                                         "variables_to_extract": ["check_in_date", "check_out_date", "num_guests", "room_type", "guest_name", "guest_email"]}}},
                    {"id": "webhook_1", "type": "api_request", "position": {"x": 250, "y": 350},
                     "data": {"label": "Check Availability",
                              "config": {"url": "{{hotel_api}}/availability", "method": "POST",
                                         "body": {"check_in": "{{check_in_date}}", "check_out": "{{check_out_date}}", "room_type": "{{room_type}}", "guests": "{{num_guests}}"},
                                         "response_mappings": {"available": "$.available", "rate": "$.rate_per_night", "total": "$.total_cost"}}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 510},
                     "data": {"label": "Room Available?", "config": {"expression": "available == true"}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 100, "y": 660},
                     "data": {"label": "Confirm Booking",
                              "config": {"prompt": "Great news! We have a {{room_type}} room available at ${{rate}} per night, total ${{total}}. Shall I go ahead and book it?",
                                         "variables_to_extract": ["booking_confirmed", "special_requests"]}}},
                    {"id": "webhook_2", "type": "api_request", "position": {"x": 100, "y": 810},
                     "data": {"label": "Create Booking",
                              "config": {"url": "{{hotel_api}}/bookings", "method": "POST",
                                         "body": {"guest_name": "{{guest_name}}", "email": "{{guest_email}}", "check_in": "{{check_in_date}}", "check_out": "{{check_out_date}}", "room_type": "{{room_type}}"},
                                         "response_mappings": {"confirmation_number": "$.confirmation_id"}}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 100, "y": 960},
                     "data": {"label": "Send Confirmation",
                              "config": {"to": "{{guest_email}}", "subject": "Booking Confirmation #{{confirmation_number}}",
                                         "body": "Dear {{guest_name}},\n\nYour reservation is confirmed!\nConfirmation: #{{confirmation_number}}\nCheck-in: {{check_in_date}}\nCheck-out: {{check_out_date}}\nRoom: {{room_type}}\nTotal: ${{total}}\n\nWe look forward to welcoming you!"}}},
                    {"id": "conversation_3", "type": "conversation", "position": {"x": 400, "y": 660},
                     "data": {"label": "Suggest Alternatives",
                              "config": {"prompt": "Unfortunately, {{room_type}} rooms aren't available for those dates. Ask for different check-in and check-out dates or a different room type.",
                                         "variables_to_extract": ["check_in_date", "check_out_date", "room_type"]}}},
                    {"id": "condition_retry", "type": "condition", "position": {"x": 400, "y": 810},
                     "data": {"label": "Retries Left?", "config": {"expression": "_slot_retry_count < 2"}}},
                    {"id": "end_retry", "type": "end_call", "position": {"x": 400, "y": 960},
                     "data": {"label": "No Suitable Room", "config": {"message": "I could not confirm a suitable room after several checks. Please contact the hotel reservations desk for help."}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 1100},
                     "data": {"label": "End Call", "config": {"message": "Your booking is confirmed! Confirmation details have been sent to your email. We look forward to your stay!"}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "webhook_1"},
                    {"source": "webhook_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "conversation_2", "label": "Yes"},
                    {"source": "condition_1", "target": "conversation_3", "label": "No"},
                    {"source": "conversation_2", "target": "webhook_2"},
                    {"source": "webhook_2", "target": "email_1"},
                    {"source": "email_1", "target": "end_1"},
                    {"source": "conversation_3", "target": "condition_retry"},
                    {"source": "condition_retry", "target": "webhook_1", "label": "Yes"},
                    {"source": "condition_retry", "target": "end_retry", "label": "No"},
                ],
            },
            {
                "id": "it_helpdesk",
                "name": "IT Helpdesk Triage",
                "description": "Categorize IT issues with AI, search KB for self-service, create Jira tickets, log to Sheets, and escalate P1 issues with Slack alerts.",
                "category": "it_support",
                "icon": "monitor",
                "trigger_phrases": [
                    "IT help",
                    "my computer is not working",
                    "technical support",
                    "password reset",
                    "network issue",
                    "VPN problem",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Identify Issue",
                              "config": {"prompt": "IT Helpdesk, how can I help? Please describe the issue you're experiencing. Is it hardware, software, network, access/password, email, or VPN related? When did it start? Is it affecting your ability to work? Also provide your employee ID for tracking.",
                                         "variables_to_extract": ["issue_category", "issue_description", "urgency", "employee_name", "employee_id", "device_type", "os_version", "error_message"]}}},
                    {"id": "kb_1", "type": "knowledge_base", "position": {"x": 250, "y": 350},
                     "data": {"label": "Search IT Solutions",
                              "config": {"query": "{{issue_category}} {{issue_description}} {{error_message}}", "max_results": 5}}},
                    {"id": "llm_1", "type": "llm_process", "position": {"x": 250, "y": 500},
                     "data": {"label": "Categorize & Suggest Fix",
                              "config": {"prompt": "Based on issue_category={{issue_category}}, description={{issue_description}}, error={{error_message}}, device={{device_type}}, OS={{os_version}}, and KB results, determine: (1) ITIL category (incident/service_request/problem), (2) priority (P1/P2/P3/P4) based on urgency and business impact, (3) whether a self-service fix from KB is likely to resolve it, (4) required technician type. If KB has a matching solution, summarize the steps.",
                                         "max_tokens": 500}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 650},
                     "data": {"label": "Self-Service Fix?", "config": {"expression": "self_service_fix == true"}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 100, "y": 800},
                     "data": {"label": "Guide Solution",
                              "config": {"prompt": "I found a solution in our knowledge base that should fix this. Let me walk you through the steps one at a time. After each step, confirm whether it worked before we move to the next. If at any point something doesn't match what you see on your screen, let me know. Did this resolve your issue?",
                                         "variables_to_extract": ["resolved", "resolution_notes"]}}},
                    {"id": "condition_2", "type": "condition", "position": {"x": 100, "y": 950},
                     "data": {"label": "Resolved?", "config": {"expression": "resolved == yes"}}},
                    {"id": "sheets_1", "type": "google_sheets", "position": {"x": 40, "y": 1100},
                     "data": {"label": "Log Resolved Incident",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{it_tickets_sheet_id}}", "range": "Resolved!A:H",
                                                    "values": ["{{current_date}}", "{{employee_name}}", "{{employee_id}}", "{{issue_category}}", "{{issue_description}}", "{{itil_category}}", "{{priority}}", "self_service_resolved"]}}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 100, "y": 1250},
                     "data": {"label": "Resolved",
                              "config": {"message": "Glad we could fix that, {{employee_name}}! The resolution has been logged. If the issue comes back or you need further help, just call us again and reference ticket category {{issue_category}}. Have a productive day!"}}},
                    {"id": "jira_1", "type": "jira", "position": {"x": 400, "y": 800},
                     "data": {"label": "Create Jira Issue",
                              "config": {"integration_type": "jira", "action": "create_issue",
                                         "params": {"project": "IT", "summary": "{{issue_category}}: {{issue_description}}", "reporter": "{{employee_name}} ({{employee_id}})", "priority": "{{priority}}", "category": "{{issue_category}}", "description": "Reported by: {{employee_name}} ({{employee_id}})\nDevice: {{device_type}}\nOS: {{os_version}}\nError: {{error_message}}\nUrgency: {{urgency}}"}}}},
                    {"id": "condition_3", "type": "condition", "position": {"x": 400, "y": 950},
                     "data": {"label": "P1/P2 Priority?", "config": {"expression": "priority == P1 or priority == P2"}}},
                    {"id": "notification_1", "type": "notification", "position": {"x": 320, "y": 1100},
                     "data": {"label": "Alert IT Team",
                              "config": {"channel": "slack", "message": "🚨 {{priority}} IT Issue: {{issue_category}} — {{issue_description}}. Reported by {{employee_name}} ({{employee_id}}). Jira ticket created. Escalating to L2 support."}}},
                    {"id": "sheets_2", "type": "google_sheets", "position": {"x": 600, "y": 1100},
                     "data": {"label": "Log Escalation",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{it_tickets_sheet_id}}", "range": "Escalated!A:H",
                                                    "values": ["{{current_date}}", "{{employee_name}}", "{{employee_id}}", "{{issue_category}}", "{{issue_description}}", "{{itil_category}}", "{{priority}}", "escalated_to_L2"]}}}},
                    {"id": "transfer_1", "type": "transfer_call", "position": {"x": 400, "y": 1250},
                     "data": {"label": "Escalate to L2",
                              "config": {"transfer_to": "{{l2_support_number}}",
                                         "transfer_message": "I've created a Jira ticket for your issue and I'm connecting you with a senior technician who can help further. Please stay on the line.",
                                         "whisper_message": "L2 escalation — Jira ticket: {{issue_category}}: {{issue_description}}. Reporter: {{employee_name}} ({{employee_id}}). Priority: {{priority}}. Device: {{device_type}}. Error: {{error_message}}."}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "kb_1"},
                    {"source": "kb_1", "target": "llm_1"},
                    {"source": "llm_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "conversation_2", "label": "Yes"},
                    {"source": "condition_1", "target": "jira_1", "label": "No"},
                    {"source": "conversation_2", "target": "condition_2"},
                    {"source": "condition_2", "target": "sheets_1", "label": "Yes"},
                    {"source": "condition_2", "target": "jira_1", "label": "No"},
                    {"source": "sheets_1", "target": "end_1"},
                    {"source": "jira_1", "target": "condition_3"},
                    {"source": "condition_3", "target": "notification_1", "label": "Yes"},
                    {"source": "condition_3", "target": "sheets_2", "label": "No"},
                    {"source": "notification_1", "target": "transfer_1"},
                    {"source": "sheets_2", "target": "transfer_1"},
                ],
            },
            {
                "id": "payment_collection",
                "name": "Payment Collection & Follow-Up",
                "description": "Outbound calls for outstanding payments with payment link generation and plan arrangement.",
                "category": "finance",
                "icon": "dollar-sign",
                "trigger_phrases": [],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Outbound Call", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Identify & Inform",
                              "config": {"prompt": "Hello, I'm calling from {{company_name}} regarding invoice #{{invoice_number}} for ${{amount_due}}. This was due on {{due_date}}. Are you able to process this payment today?",
                                         "variables_to_extract": ["can_pay_today", "payment_method", "partial_amount"]}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 350},
                     "data": {"label": "Can Pay?", "config": {"expression": "can_pay_today == yes"}}},
                    {"id": "webhook_1", "type": "api_request", "position": {"x": 100, "y": 500},
                     "data": {"label": "Generate Payment Link",
                              "config": {"url": "{{payment_api}}/payment-links", "method": "POST",
                                         "body": {"amount": "{{amount_due}}", "invoice": "{{invoice_number}}", "customer_email": "{{customer_email}}"},
                                         "response_mappings": {"payment_url": "$.url"}}}},
                    {"id": "sms_1", "type": "send_sms", "position": {"x": 100, "y": 650},
                     "data": {"label": "Send Payment Link",
                              "config": {"to": "{{caller_phone}}", "body": "Pay your invoice #{{invoice_number}} (${{amount_due}}) securely here: {{payment_url}}"}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 400, "y": 500},
                     "data": {"label": "Arrange Plan",
                              "config": {"prompt": "I understand. We can set up a payment plan. How much can you pay per month, and when would you like the first payment?",
                                         "variables_to_extract": ["monthly_amount", "first_payment_date"]}}},
                    {"id": "webhook_2", "type": "api_request", "position": {"x": 400, "y": 660},
                     "data": {"label": "Create Plan",
                              "config": {"url": "{{payment_api}}/plans", "method": "POST",
                                         "body": {"invoice": "{{invoice_number}}", "monthly_amount": "{{monthly_amount}}", "start_date": "{{first_payment_date}}"}}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 810},
                     "data": {"label": "End Call", "config": {"message": "Thank you for taking care of this. If you have any questions, don't hesitate to call us back."}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "webhook_1", "label": "Yes"},
                    {"source": "condition_1", "target": "conversation_2", "label": "No"},
                    {"source": "webhook_1", "target": "sms_1"},
                    {"source": "sms_1", "target": "end_1"},
                    {"source": "conversation_2", "target": "webhook_2"},
                    {"source": "webhook_2", "target": "end_1"},
                ],
            },
            {
                "id": "survey_feedback",
                "name": "Survey & Feedback Collection",
                "description": "Post-interaction surveys with NPS scoring and follow-up for detractors.",
                "category": "general",
                "icon": "star",
                "trigger_phrases": [],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Outbound Call", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "NPS Question",
                              "config": {"prompt": "Hi {{customer_name}}, this is a quick feedback call from {{company_name}}. On a scale of 0 to 10, how likely are you to recommend us to a friend or colleague?",
                                         "variables_to_extract": ["nps_score"]}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 250, "y": 340},
                     "data": {"label": "Follow-Up",
                              "config": {"prompt": "Thank you for that score. Could you briefly tell me the main reason for your rating? What could we do better?",
                                         "variables_to_extract": ["feedback_reason", "improvement_suggestion"]}}},
                    {"id": "webhook_1", "type": "api_request", "position": {"x": 250, "y": 500},
                     "data": {"label": "Save Feedback",
                              "config": {"url": "{{feedback_api}}/responses", "method": "POST",
                                         "body": {"customer": "{{customer_name}}", "nps_score": "{{nps_score}}", "reason": "{{feedback_reason}}", "suggestion": "{{improvement_suggestion}}"}}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 650},
                     "data": {"label": "Detractor?", "config": {"expression": "nps_score < 7"}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 100, "y": 800},
                     "data": {"label": "Alert Manager",
                              "config": {"to": "{{manager_email}}", "subject": "⚠️ Detractor Alert: {{customer_name}} (NPS: {{nps_score}})",
                                         "body": "Customer {{customer_name}} gave NPS score {{nps_score}}.\n\nReason: {{feedback_reason}}\nSuggestion: {{improvement_suggestion}}\n\nPlease follow up within 24 hours."}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 940},
                     "data": {"label": "End Call", "config": {"message": "Thank you so much for your feedback — it really helps us improve. Have a wonderful day!"}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "conversation_2"},
                    {"source": "conversation_2", "target": "webhook_1"},
                    {"source": "webhook_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "email_1", "label": "Yes"},
                    {"source": "condition_1", "target": "end_1", "label": "No"},
                    {"source": "email_1", "target": "end_1"},
                ],
            },
            {
                "id": "loan_prequalification",
                "name": "Loan Pre-Qualification",
                "description": "Collect financial information, run basic eligibility check, and connect with loan officer.",
                "category": "finance",
                "icon": "landmark",
                "trigger_phrases": [
                    "I want to apply for a loan",
                    "mortgage pre-qualification",
                    "loan application",
                    "I need financing",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Basic Info",
                              "config": {"prompt": "I'd be happy to help with pre-qualification. What type of loan are you looking for — mortgage, auto, personal, or business? What's the approximate amount you need?",
                                         "variables_to_extract": ["loan_type", "loan_amount", "applicant_name", "applicant_email"]}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 250, "y": 340},
                     "data": {"label": "Financial Details",
                              "config": {"prompt": "For pre-qualification, I need a few details: your approximate annual income, employment status, and estimated credit score range (excellent, good, fair, poor).",
                                         "variables_to_extract": ["annual_income", "employment_status", "credit_range", "monthly_debts"]}}},
                    {"id": "llm_1", "type": "llm_process", "position": {"x": 250, "y": 500},
                     "data": {"label": "Assess Eligibility",
                              "config": {"prompt": "Based on: loan_type={{loan_type}}, amount={{loan_amount}}, income={{annual_income}}, credit={{credit_range}}, debts={{monthly_debts}} — provide a brief pre-qualification assessment."}}},
                    {"id": "webhook_1", "type": "api_request", "position": {"x": 250, "y": 650},
                     "data": {"label": "Save Application",
                              "config": {"url": "{{crm_api}}/leads", "method": "POST",
                                         "body": {"name": "{{applicant_name}}", "email": "{{applicant_email}}", "loan_type": "{{loan_type}}", "amount": "{{loan_amount}}", "income": "{{annual_income}}", "credit": "{{credit_range}}"}}}},
                    {"id": "transfer_1", "type": "transfer_call", "position": {"x": 250, "y": 800},
                     "data": {"label": "Connect with Officer",
                              "config": {"transfer_to": "{{loan_officer_number}}", "transfer_message": "Based on your information, you may qualify! Let me connect you with a loan officer for next steps.",
                                         "whisper_message": "Pre-qualified lead: {{applicant_name}}, {{loan_type}} ${{loan_amount}}, income ${{annual_income}}, credit {{credit_range}}"}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 950},
                     "data": {"label": "Transfer Complete", "config": {"message": "I am connecting you with a loan officer now."}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "conversation_2"},
                    {"source": "conversation_2", "target": "llm_1"},
                    {"source": "llm_1", "target": "webhook_1"},
                    {"source": "webhook_1", "target": "transfer_1"},
                    {"source": "transfer_1", "target": "end_1"},
                ],
            },
            {
                "id": "event_registration",
                "name": "Event Registration",
                "description": "Register callers for events/webinars, send confirmations, and add to calendar.",
                "category": "events",
                "icon": "ticket",
                "trigger_phrases": [
                    "register for the event",
                    "sign up for the webinar",
                    "event registration",
                    "I want to attend",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Event Selection",
                              "config": {"prompt": "Thank you for your interest! We have several upcoming events. Which event are you interested in? I can also tell you about our upcoming schedule.",
                                         "variables_to_extract": ["event_name", "attendee_name", "attendee_email", "attendee_company", "num_tickets"]}}},
                    {"id": "webhook_1", "type": "api_request", "position": {"x": 250, "y": 350},
                     "data": {"label": "Register Attendee",
                              "config": {"url": "{{events_api}}/registrations", "method": "POST",
                                         "body": {"event": "{{event_name}}", "name": "{{attendee_name}}", "email": "{{attendee_email}}", "company": "{{attendee_company}}", "tickets": "{{num_tickets}}"},
                                         "response_mappings": {"registration_id": "$.id", "event_date": "$.event_date", "event_location": "$.location"}}}},
                    {"id": "action_1", "type": "action", "position": {"x": 250, "y": 510},
                     "data": {"label": "Add to Calendar",
                              "config": {"integration_type": "google_calendar", "action": "create_event",
                                         "params": {"title": "{{event_name}}", "date": "{{event_date}}", "description": "Registration #{{registration_id}}\nAttendee: {{attendee_name}}\nLocation: {{event_location}}"}}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 250, "y": 660},
                     "data": {"label": "Send Confirmation",
                              "config": {"to": "{{attendee_email}}", "subject": "Registration Confirmed: {{event_name}}",
                                         "body": "Hi {{attendee_name}},\n\nYou're registered for {{event_name}}!\n\nRegistration #: {{registration_id}}\nDate: {{event_date}}\nLocation: {{event_location}}\nTickets: {{num_tickets}}\n\nSee you there!"}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 810},
                     "data": {"label": "End Call", "config": {"message": "You're all registered! We've sent confirmation to your email. See you at the event!"}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "webhook_1"},
                    {"source": "webhook_1", "target": "action_1"},
                    {"source": "action_1", "target": "email_1"},
                    {"source": "email_1", "target": "end_1"},
                ],
            },
            {
                "id": "product_demo",
                "name": "Product Demo Scheduling",
                "description": "Qualify prospects and schedule product demos with the right sales rep.",
                "category": "sales",
                "icon": "presentation",
                "trigger_phrases": [
                    "I'd like a demo",
                    "schedule a product demo",
                    "can I see a demonstration",
                    "show me how it works",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Understand Needs",
                              "config": {"prompt": "I'd love to set up a demo for you! First, tell me about your use case — what challenges are you trying to solve? What's your company name and role?",
                                         "variables_to_extract": ["use_case", "company_name", "contact_role", "contact_name", "contact_email", "company_size"]}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 250, "y": 350},
                     "data": {"label": "Schedule Details",
                              "config": {"prompt": "What dates and times work best for a 30-minute demo? Our team is available Monday through Friday, 9 AM to 5 PM.",
                                         "variables_to_extract": ["preferred_demo_date", "preferred_demo_time"]}}},
                    {"id": "action_1", "type": "action", "position": {"x": 250, "y": 510},
                     "data": {"label": "Book Demo",
                              "config": {"integration_type": "google_calendar", "action": "create_event",
                                         "params": {"title": "Product Demo - {{company_name}}", "date": "{{preferred_demo_date}}", "time": "{{preferred_demo_time}}",
                                                    "description": "Company: {{company_name}}\nContact: {{contact_name}} ({{contact_role}})\nUse Case: {{use_case}}\nSize: {{company_size}}"}}}},
                    {"id": "webhook_1", "type": "api_request", "position": {"x": 250, "y": 660},
                     "data": {"label": "Create CRM Lead",
                              "config": {"url": "{{crm_api}}/contacts", "method": "POST",
                                         "body": {"name": "{{contact_name}}", "email": "{{contact_email}}", "company": "{{company_name}}", "role": "{{contact_role}}", "source": "demo_request", "notes": "{{use_case}}"}}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 250, "y": 810},
                     "data": {"label": "Send Demo Invite",
                              "config": {"to": "{{contact_email}}", "subject": "Your Product Demo is Confirmed!",
                                         "body": "Hi {{contact_name}},\n\nYour product demo is scheduled for {{preferred_demo_date}} at {{preferred_demo_time}}.\n\nA meeting link will be sent before the demo.\n\nLooking forward to showing you what we can do for {{company_name}}!"}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 960},
                     "data": {"label": "End Call", "config": {"message": "Your demo is booked! Check your email for confirmation. We're excited to show you what we can do. Talk soon!"}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "conversation_2"},
                    {"source": "conversation_2", "target": "action_1"},
                    {"source": "action_1", "target": "webhook_1"},
                    {"source": "webhook_1", "target": "email_1"},
                    {"source": "email_1", "target": "end_1"},
                ],
            },
            {
                "id": "emergency_dispatch",
                "name": "Emergency Dispatch & Routing",
                "description": "Triage emergency calls, collect location info, and immediately route to appropriate responders.",
                "category": "emergency",
                "icon": "siren",
                "trigger_phrases": [
                    "emergency",
                    "I need help urgently",
                    "there's been an accident",
                    "fire",
                    "medical emergency",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Emergency Call", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Assess Situation",
                              "config": {"prompt": "Please stay calm. What is your emergency? Is anyone injured? What is your current location or address?",
                                         "variables_to_extract": ["emergency_type", "injuries_reported", "location", "caller_name", "num_people_affected"]}}},
                    {"id": "notification_1", "type": "notification", "position": {"x": 250, "y": 340},
                     "data": {"label": "Alert Dispatch",
                              "config": {"channel": "slack", "message": "🚨 EMERGENCY: {{emergency_type}} at {{location}}. Injuries: {{injuries_reported}}. People affected: {{num_people_affected}}. Caller: {{caller_name}}"}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 490},
                     "data": {"label": "Life-Threatening?", "config": {"expression": "injuries_reported == yes"}}},
                    {"id": "transfer_1", "type": "transfer_call", "position": {"x": 100, "y": 640},
                     "data": {"label": "Priority Dispatch",
                              "config": {"transfer_to": "{{emergency_dispatch}}", "transfer_message": "Stay on the line — I'm connecting you with emergency dispatch immediately.",
                                         "whisper_message": "PRIORITY: {{emergency_type}} at {{location}}. Injuries reported. {{num_people_affected}} people affected."}}},
                    {"id": "transfer_2", "type": "transfer_call", "position": {"x": 400, "y": 640},
                     "data": {"label": "Standard Dispatch",
                              "config": {"transfer_to": "{{standard_dispatch}}", "transfer_message": "I'm connecting you with our dispatch team now.",
                                         "whisper_message": "{{emergency_type}} at {{location}}. No injuries. Caller: {{caller_name}}"}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 800},
                     "data": {"label": "Dispatch Transfer", "config": {"message": "Stay on the line while dispatch takes over."}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "notification_1"},
                    {"source": "notification_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "transfer_1", "label": "Yes"},
                    {"source": "condition_1", "target": "transfer_2", "label": "No"},
                    {"source": "transfer_1", "target": "end_1"},
                    {"source": "transfer_2", "target": "end_1"},
                ],
            },
            {
                "id": "subscription_management",
                "name": "Subscription Management",
                "description": "Handle subscription inquiries — upgrades, downgrades, cancellations with retention offers.",
                "category": "support",
                "icon": "repeat",
                "trigger_phrases": [
                    "cancel my subscription",
                    "upgrade my plan",
                    "downgrade my plan",
                    "change my subscription",
                    "billing inquiry",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Verify Account",
                              "config": {"prompt": "I can help with your subscription. Can you provide your account email or customer ID so I can pull up your account?",
                                         "variables_to_extract": ["customer_id", "customer_email", "account_action"]}}},
                    {"id": "webhook_1", "type": "api_request", "position": {"x": 250, "y": 340},
                     "data": {"label": "Fetch Account",
                              "config": {"url": "{{billing_api}}/customers/{{customer_id}}", "method": "GET",
                                         "response_mappings": {"current_plan": "$.plan_name", "billing_amount": "$.amount", "next_billing": "$.next_billing_date"}}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 500},
                     "data": {"label": "Wants to Cancel?", "config": {"expression": "account_action == cancel"}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 100, "y": 660},
                     "data": {"label": "Retention Offer",
                              "config": {"prompt": "I'm sorry to hear that. Before we process the cancellation, I'd like to offer you 3 months at 50% off. Would that interest you? Could you tell me the main reason for cancelling?",
                                         "variables_to_extract": ["accepts_retention", "cancellation_reason"]}}},
                    {"id": "conversation_3", "type": "conversation", "position": {"x": 400, "y": 660},
                     "data": {"label": "Plan Changes",
                              "config": {"prompt": "Your current plan is {{current_plan}} at ${{billing_amount}}/month. What changes would you like to make? I can show you available options.",
                                         "variables_to_extract": ["new_plan", "confirmed"]}}},
                    {"id": "webhook_2", "type": "api_request", "position": {"x": 250, "y": 830},
                     "data": {"label": "Apply Changes",
                              "config": {"url": "{{billing_api}}/customers/{{customer_id}}/subscription", "method": "PUT",
                                         "body": {"action": "{{account_action}}", "new_plan": "{{new_plan}}", "reason": "{{cancellation_reason}}"}}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 250, "y": 980},
                     "data": {"label": "Confirmation Email",
                              "config": {"to": "{{customer_email}}", "subject": "Subscription Update Confirmation",
                                         "body": "Hi,\n\nYour subscription has been updated.\n\nPrevious Plan: {{current_plan}}\nAction: {{account_action}}\n\nIf you have questions, reply to this email."}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 1120},
                     "data": {"label": "End Call", "config": {"message": "Your subscription changes have been processed. You'll receive a confirmation email shortly. Thank you!"}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "webhook_1"},
                    {"source": "webhook_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "conversation_2", "label": "Yes"},
                    {"source": "condition_1", "target": "conversation_3", "label": "No"},
                    {"source": "conversation_2", "target": "webhook_2"},
                    {"source": "conversation_3", "target": "webhook_2"},
                    {"source": "webhook_2", "target": "email_1"},
                    {"source": "email_1", "target": "end_1"},
                ],
            },
            # ═══════════════════════════════════════════════════════════
            # NEW TEMPLATES — High-value verticals with deep integrations
            # ═══════════════════════════════════════════════════════════
            {
                "id": "saas_onboarding",
                "name": "SaaS Onboarding & Setup Wizard",
                "description": "Guide new users through personalized setup with KB-driven steps, LLM-generated plan, calendar scheduling, and email confirmation.",
                "category": "saas",
                "icon": "rocket",
                "trigger_phrases": [
                    "setup help",
                    "onboarding",
                    "getting started",
                    "configure my account",
                    "set up my account",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Identify User & Plan",
                              "config": {"prompt": "Welcome to {{company_name}}! I'll help you get set up. Can you share your email address and tell me which plan you're on — Starter, Pro, or Enterprise? Also, what's your primary use case? What's your name and company?",
                                         "variables_to_extract": ["user_email", "plan_tier", "use_case", "company_name", "user_name"]}}},
                    {"id": "kb_1", "type": "knowledge_base", "position": {"x": 250, "y": 350},
                     "data": {"label": "Search Setup Guides",
                              "config": {"query": "{{plan_tier}} onboarding setup guide {{use_case}}", "max_results": 5}}},
                    {"id": "llm_1", "type": "llm_process", "position": {"x": 250, "y": 500},
                     "data": {"label": "Personalize Setup Steps",
                              "config": {"prompt": "Based on plan={{plan_tier}}, use_case={{use_case}}, and the KB results, generate a numbered step-by-step onboarding plan. Prioritize the 3 most critical setup steps for their use case. Include specific feature names and configuration paths. Format as: Step 1: ..., Step 2: ..., Step 3: ...",
                                         "max_tokens": 800}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 250, "y": 650},
                     "data": {"label": "Walk Through Steps",
                              "config": {"prompt": "I've created a personalized setup plan for you. Let me walk you through each step. First, {{step_1}}. Have you completed this, or would you like me to explain it in detail? After each step, let me know if you're stuck or ready to move on.",
                                         "variables_to_extract": ["setup_progress", "current_step", "needs_help_with"]}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 800},
                     "data": {"label": "Needs Human Help?", "config": {"expression": "setup_progress == stuck"}}},
                    {"id": "sheets_1", "type": "google_sheets", "position": {"x": 40, "y": 950},
                     "data": {"label": "Log Onboarding",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{onboarding_sheet_id}}", "range": "Onboarding!A:G",
                                                    "values": ["{{current_date}}", "{{user_email}}", "{{company_name}}", "{{plan_tier}}", "{{use_case}}", "{{setup_progress}}", "{{needs_help_with}}"]}}}},
                    {"id": "conversation_3", "type": "conversation", "position": {"x": 40, "y": 1100},
                     "data": {"label": "Schedule Setup Call",
                              "config": {"prompt": "Would you like to schedule a 30-minute call with our implementation team to finish your setup? They can help with {{needs_help_with}}. What day and time works best for you?",
                                         "variables_to_extract": ["preferred_date", "preferred_time"]}}},
                    {"id": "action_1", "type": "action", "position": {"x": 40, "y": 1250},
                     "data": {"label": "Schedule Setup Call",
                              "config": {"integration_type": "google_calendar", "action": "create_event",
                                         "params": {"title": "Onboarding Setup - {{company_name}}", "date": "{{preferred_date}}", "time": "{{preferred_time}}",
                                                    "description": "Plan: {{plan_tier}}\nUse case: {{use_case}}\nProgress: {{setup_progress}}\nNeeds help with: {{needs_help_with}}"}}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 400, "y": 1100},
                     "data": {"label": "Send Setup Guide",
                              "config": {"to": "{{user_email}}", "subject": "Your {{company_name}} Setup Guide",
                                         "body": "Hi {{user_name}},\n\nHere's your personalized setup plan:\n\n{{setup_plan}}\n\nYour implementation call is scheduled for {{preferred_date}} at {{preferred_time}}.\n\nIf you need help before then, reply to this email or call us.\n\nWelcome aboard!\n{{company_name}} Team"}}},
                    {"id": "sms_1", "type": "send_sms", "position": {"x": 400, "y": 1250},
                     "data": {"label": "Quick Reminder",
                              "config": {"to": "{{caller_phone}}",
                                         "body": "Your {{company_name}} setup call is scheduled for {{preferred_date}} at {{preferred_time}}. Reply CANCEL to reschedule."}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 1400},
                     "data": {"label": "End Call",
                              "config": {"message": "You're all set, {{user_name}}! Check your email for the complete setup guide. Your implementation call is booked for {{preferred_date}}. Welcome aboard!"}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "kb_1"},
                    {"source": "kb_1", "target": "llm_1"},
                    {"source": "llm_1", "target": "conversation_2"},
                    {"source": "conversation_2", "target": "condition_1"},
                    {"source": "condition_1", "target": "sheets_1", "label": "Yes"},
                    {"source": "condition_1", "target": "email_1", "label": "No"},
                    {"source": "sheets_1", "target": "conversation_3"},
                    {"source": "conversation_3", "target": "action_1"},
                    {"source": "action_1", "target": "email_1"},
                    {"source": "email_1", "target": "sms_1"},
                    {"source": "sms_1", "target": "end_1"},
                ],
            },
            {
                "id": "healthcare_patient_intake",
                "name": "Healthcare Patient Intake & Insurance Verification",
                "description": "Register new patients, verify insurance via API, search KB for covered services, book appointment, and send confirmation via SMS and email.",
                "category": "healthcare",
                "icon": "heart-pulse",
                "trigger_phrases": [
                    "new patient",
                    "register as a patient",
                    "insurance verification",
                    "I need to see a doctor",
                    "become a patient",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Collect Patient Info",
                              "config": {"prompt": "Welcome to {{clinic_name}}! I'll help you register as a new patient. May I have your full name, date of birth, address, and phone number? Also, what's the best email to reach you?",
                                         "variables_to_extract": ["patient_name", "date_of_birth", "address", "patient_phone", "patient_email"]}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 250, "y": 340},
                     "data": {"label": "Insurance Details",
                              "config": {"prompt": "Thank you, {{patient_name}}. Do you have insurance? If so, please share your insurance provider name, member ID, and group number. If you don't have insurance, let me know — we offer self-pay options.",
                                         "variables_to_extract": ["insurance_provider", "member_id", "group_number", "is_self_pay"]}}},
                    {"id": "webhook_1", "type": "api_request", "position": {"x": 250, "y": 500},
                     "data": {"label": "Verify Insurance",
                              "config": {"url": "{{insurance_api}}/verify", "method": "POST",
                                         "body": {"member_id": "{{member_id}}", "provider": "{{insurance_provider}}", "patient_dob": "{{date_of_birth}}"},
                                         "response_mappings": {"is_valid": "$.valid", "copay_amount": "$.copay", "coverage_type": "$.coverage_type", "in_network": "$.in_network"}}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 650},
                     "data": {"label": "Insurance Valid?", "config": {"expression": "is_valid == true"}}},
                    {"id": "conversation_3", "type": "conversation", "position": {"x": 400, "y": 800},
                     "data": {"label": "Insurance Invalid",
                              "config": {"prompt": "I wasn't able to verify your insurance. This could be due to an incorrect member ID or an out-of-network provider. Would you like to re-enter your information, or would you prefer to self-pay? Our self-pay rate for a new patient visit is ${{self_pay_rate}}.",
                                         "variables_to_extract": ["wants_retry", "payment_preference"]}}},
                    {"id": "sheets_1", "type": "google_sheets", "position": {"x": 100, "y": 800},
                     "data": {"label": "Log Patient Intake",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{patient_intake_sheet_id}}", "range": "Intake!A:G",
                                                    "values": ["{{current_date}}", "{{patient_name}}", "{{date_of_birth}}", "{{insurance_provider}}", "{{member_id}}", "{{is_valid}}", "{{copay_amount}}"]}}}},
                    {"id": "kb_1", "type": "knowledge_base", "position": {"x": 100, "y": 950},
                     "data": {"label": "Search Available Services",
                              "config": {"query": "{{clinic_name}} services covered by {{coverage_type}}", "max_results": 3}}},
                    {"id": "conversation_4", "type": "conversation", "position": {"x": 100, "y": 1100},
                     "data": {"label": "Discuss Coverage & Copay",
                              "config": {"prompt": "Great news — your insurance is verified! Your plan covers {{coverage_type}} with a ${{copay_amount}} copay. I found information about covered services at our clinic. Would you like to schedule your first appointment? What date and time work best? Do you have a preferred doctor?",
                                         "variables_to_extract": ["wants_appointment", "preferred_date", "preferred_time", "preferred_doctor"]}}},
                    {"id": "action_1", "type": "action", "position": {"x": 100, "y": 1250},
                     "data": {"label": "Book Appointment",
                              "config": {"integration_type": "google_calendar", "action": "create_event",
                                         "params": {"title": "New Patient - {{patient_name}}", "date": "{{preferred_date}}", "time": "{{preferred_time}}",
                                                    "description": "Patient: {{patient_name}}\nDOB: {{date_of_birth}}\nInsurance: {{insurance_provider}} ({{coverage_type}})\nCopay: ${{copay_amount}}\nPreferred doctor: {{preferred_doctor}}\nNew patient: yes"}}}},
                    {"id": "delay_1", "type": "delay", "position": {"x": 100, "y": 1400},
                     "data": {"label": "Ensure Calendar Sync", "config": {"delay_seconds": 3}}},
                    {"id": "sms_1", "type": "send_sms", "position": {"x": 100, "y": 1520},
                     "data": {"label": "Confirmation SMS",
                              "config": {"to": "{{patient_phone}}",
                                         "body": "Welcome to {{clinic_name}}, {{patient_name}}! Your appointment is on {{preferred_date}} at {{preferred_time}}. Copay: ${{copay_amount}}. Please arrive 20 min early with your insurance card and photo ID."}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 100, "y": 1640},
                     "data": {"label": "New Patient Packet",
                              "config": {"to": "{{patient_email}}", "subject": "Welcome to {{clinic_name}} — Your First Appointment",
                                         "body": "Dear {{patient_name}},\n\nWelcome to {{clinic_name}}! Your first appointment is scheduled:\n\nDate: {{preferred_date}}\nTime: {{preferred_time}}\nDoctor: {{preferred_doctor}}\nCopay: ${{copay_amount}}\n\nPlease complete the new patient intake forms before your visit: {{intake_forms_url}}\n\nBring your insurance card and photo ID. Arrive 20 minutes early.\n\nSee you soon!\n{{clinic_name}}"}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 1760},
                     "data": {"label": "End Call",
                              "config": {"message": "You're all registered, {{patient_name}}! Please check your email for the new patient packet and intake forms. We look forward to seeing you on {{preferred_date}}!"}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "conversation_2"},
                    {"source": "conversation_2", "target": "webhook_1"},
                    {"source": "webhook_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "sheets_1", "label": "Yes"},
                    {"source": "condition_1", "target": "conversation_3", "label": "No"},
                    {"source": "conversation_3", "target": "sheets_1"},
                    {"source": "sheets_1", "target": "kb_1"},
                    {"source": "kb_1", "target": "conversation_4"},
                    {"source": "conversation_4", "target": "action_1"},
                    {"source": "action_1", "target": "delay_1"},
                    {"source": "delay_1", "target": "sms_1"},
                    {"source": "sms_1", "target": "email_1"},
                    {"source": "email_1", "target": "end_1"},
                ],
            },
            {
                "id": "financial_advisor_booking",
                "name": "Financial Advisor Consultation Booking",
                "description": "Assess financial needs, match with advisor via KB + LLM, schedule consultation, log to Sheets, and notify advisor on Slack.",
                "category": "finance",
                "icon": "landmark",
                "trigger_phrases": [
                    "financial advice",
                    "speak with an advisor",
                    "investment consultation",
                    "retirement planning",
                    "wealth management",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Assess Financial Need",
                              "config": {"prompt": "Thank you for calling {{firm_name}}. I'd like to understand your needs. Are you interested in retirement planning, investment management, tax strategy, estate planning, or something else? Also, may I have your name, email, and an approximate net worth range (under $500K, $500K-$2M, $2M-$10M, $10M+)? What age range are you in?",
                                         "variables_to_extract": ["service_needed", "caller_name", "caller_email", "net_worth_range", "age_range"]}}},
                    {"id": "kb_1", "type": "knowledge_base", "position": {"x": 250, "y": 350},
                     "data": {"label": "Search Advisor Bios",
                              "config": {"query": "{{service_needed}} financial advisor specialization", "max_results": 3}}},
                    {"id": "llm_1", "type": "llm_process", "position": {"x": 250, "y": 500},
                     "data": {"label": "Match Advisor",
                              "config": {"prompt": "Based on the caller's need ({{service_needed}}), net worth range ({{net_worth_range}}), and age ({{age_range}}), and the KB advisor bios, recommend the best-fit advisor and explain why. Include their specialty areas and years of experience.",
                                         "max_tokens": 500}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 250, "y": 650},
                     "data": {"label": "Present Advisor Match",
                              "config": {"prompt": "Based on your needs, I'd recommend {{advisor_name}}, who specializes in {{service_needed}} for clients in your profile. They have {{years_experience}} years of experience. Would you like to schedule a consultation? What date and time work best? Would you prefer an in-person or virtual meeting?",
                                         "variables_to_extract": ["wants_consultation", "preferred_date", "preferred_time", "consultation_type"]}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 800},
                     "data": {"label": "Wants Consultation?", "config": {"expression": "wants_consultation == yes"}}},
                    {"id": "action_1", "type": "action", "position": {"x": 100, "y": 950},
                     "data": {"label": "Schedule Consultation",
                              "config": {"integration_type": "google_calendar", "action": "create_event",
                                         "params": {"title": "Consultation - {{caller_name}} with {{advisor_name}}", "date": "{{preferred_date}}", "time": "{{preferred_time}}",
                                                    "description": "Service: {{service_needed}}\nNet worth: {{net_worth_range}}\nAge: {{age_range}}\nType: {{consultation_type}}"}}}},
                    {"id": "sheets_1", "type": "google_sheets", "position": {"x": 100, "y": 1100},
                     "data": {"label": "Log Prospect",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{advisor_leads_sheet_id}}", "range": "Prospects!A:G",
                                                    "values": ["{{current_date}}", "{{caller_name}}", "{{caller_email}}", "{{service_needed}}", "{{net_worth_range}}", "{{advisor_name}}", "{{preferred_date}}"]}}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 100, "y": 1250},
                     "data": {"label": "Send Pre-Consultation Questionnaire",
                              "config": {"to": "{{caller_email}}", "subject": "Your Consultation with {{advisor_name}} — Pre-Meeting Questionnaire",
                                         "body": "Dear {{caller_name}},\n\nYour consultation with {{advisor_name}} is scheduled for {{preferred_date}} at {{preferred_time}} ({{consultation_type}}).\n\nTo make the most of your meeting, please complete this pre-consultation questionnaire: {{questionnaire_url}}\n\nPlease bring: recent statements, tax returns, and any specific questions.\n\nBest regards,\n{{firm_name}}"}}},
                    {"id": "sms_1", "type": "send_sms", "position": {"x": 100, "y": 1400},
                     "data": {"label": "Reminder SMS",
                              "config": {"to": "{{caller_phone}}",
                                         "body": "Your consultation with {{advisor_name}} at {{firm_name}} is confirmed for {{preferred_date}} at {{preferred_time}}. Please check your email for the pre-meeting questionnaire."}}},
                    {"id": "notification_1", "type": "notification", "position": {"x": 100, "y": 1550},
                     "data": {"label": "Alert Advisor",
                              "config": {"channel": "slack", "message": "New consultation booked: {{caller_name}} for {{service_needed}} (net worth: {{net_worth_range}}, age: {{age_range}}). Scheduled {{preferred_date}} at {{preferred_time}}. Type: {{consultation_type}}."}}},
                    {"id": "conversation_3", "type": "conversation", "position": {"x": 400, "y": 950},
                     "data": {"label": "Anything Else?",
                              "config": {"prompt": "Is there anything else I can help you with today? I can also provide information about our services or answer general questions about financial planning.",
                                         "variables_to_extract": ["needs_more_info"]}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 1700},
                     "data": {"label": "End Call",
                              "config": {"message": "Your consultation is booked, {{caller_name}}! Don't forget to complete the questionnaire before your meeting. We look forward to helping you achieve your financial goals."}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "kb_1"},
                    {"source": "kb_1", "target": "llm_1"},
                    {"source": "llm_1", "target": "conversation_2"},
                    {"source": "conversation_2", "target": "condition_1"},
                    {"source": "condition_1", "target": "action_1", "label": "Yes"},
                    {"source": "condition_1", "target": "conversation_3", "label": "No"},
                    {"source": "action_1", "target": "sheets_1"},
                    {"source": "sheets_1", "target": "email_1"},
                    {"source": "email_1", "target": "sms_1"},
                    {"source": "sms_1", "target": "notification_1"},
                    {"source": "notification_1", "target": "end_1"},
                    {"source": "conversation_3", "target": "end_1"},
                ],
            },
            {
                "id": "ecommerce_order_support",
                "name": "E-Commerce Order Support with Shopify",
                "description": "Look up Shopify orders, classify issues with AI, search KB for policies, check Stripe payments, log to Sheets, and resolve or escalate.",
                "category": "ecommerce",
                "icon": "shopping-bag",
                "trigger_phrases": [
                    "order problem",
                    "where is my order",
                    "wrong item",
                    "damaged product",
                    "order issue",
                    "missing items",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Get Order Details",
                              "config": {"prompt": "Hi, thanks for calling {{store_name}} support! I'm here to help with your order. Could you share your order number and the email associated with your account? Also, briefly describe the issue — is it a shipping delay, wrong item, damaged product, or missing items?",
                                         "variables_to_extract": ["order_number", "customer_email", "issue_type", "issue_description"]}}},
                    {"id": "shopify_1", "type": "shopify", "position": {"x": 250, "y": 340},
                     "data": {"label": "Get Order (Shopify)",
                              "config": {"integration_type": "shopify", "action": "get_order",
                                         "params": {"order_id": "{{order_number}}"}}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 490},
                     "data": {"label": "Order Found?", "config": {"expression": "result.found == true"}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 400, "y": 640},
                     "data": {"label": "Order Not Found",
                              "config": {"prompt": "I wasn't able to find an order with that number. Could you double-check? It's usually in your confirmation email. Alternatively, I can look it up by your email address.",
                                         "variables_to_extract": ["order_number", "customer_email"]}}},
                    {"id": "condition_retry", "type": "condition", "position": {"x": 700, "y": 790},
                     "data": {"label": "Lookup Retries Left?", "config": {"expression": "_slot_retry_count < 2"}}},
                    {"id": "end_lookup", "type": "end_call", "position": {"x": 700, "y": 940},
                     "data": {"label": "Order Not Located", "config": {"message": "I could not locate the order after several checks. Please contact support with the confirmation email available."}}},
                    {"id": "llm_1", "type": "llm_process", "position": {"x": 100, "y": 640},
                     "data": {"label": "Classify Issue",
                              "config": {"prompt": "Based on issue_type={{issue_type}}, issue_description={{issue_description}}, and order details, classify this as: shipping_delay, wrong_item, damaged, missing_items, refund_request, or other. Determine urgency (high/medium/low) and recommended resolution path.",
                                         "max_tokens": 300}}},
                    {"id": "kb_1", "type": "knowledge_base", "position": {"x": 100, "y": 790},
                     "data": {"label": "Search Store Policies",
                              "config": {"query": "{{issue_type}} policy return exchange shipping {{store_name}}", "max_results": 3}}},
                    {"id": "condition_2", "type": "condition", "position": {"x": 100, "y": 940},
                     "data": {"label": "Resolution Path", "config": {"expression": "issue_classification == refund_request"}}},
                    {"id": "condition_exchange", "type": "condition", "position": {"x": 400, "y": 940},
                     "data": {"label": "Exchange Path?", "config": {"expression": "issue_classification == exchange"}}},
                    {"id": "stripe_1", "type": "stripe", "position": {"x": 100, "y": 1090},
                     "data": {"label": "Check Payment Status",
                              "config": {"integration_type": "stripe", "action": "check_payment_status",
                                         "params": {"payment_intent": "{{order.payment_intent_id}}"}}}},
                    {"id": "shopify_2", "type": "shopify", "position": {"x": 400, "y": 1090},
                     "data": {"label": "Search Products (Exchange)",
                              "config": {"integration_type": "shopify", "action": "search_products",
                                         "params": {"query": "{{product_name}} replacement"}}}},
                    {"id": "sheets_1", "type": "google_sheets", "position": {"x": 250, "y": 1240},
                     "data": {"label": "Log Support Case",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{support_cases_sheet_id}}", "range": "Cases!A:H",
                                                    "values": ["{{current_date}}", "{{order_number}}", "{{customer_email}}", "{{issue_type}}", "{{issue_classification}}", "{{urgency_level}}", "{{recommended_resolution}}", "open"]}}}},
                    {"id": "conversation_3", "type": "conversation", "position": {"x": 250, "y": 1390},
                     "data": {"label": "Explain Resolution",
                              "config": {"prompt": "Here's what I can do for you: {{recommended_resolution}}. Based on our policy, {{policy_summary}}. Would you like me to proceed with this resolution?",
                                         "variables_to_extract": ["confirmed_resolution"]}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 250, "y": 1540},
                     "data": {"label": "Resolution Confirmation",
                              "config": {"to": "{{customer_email}}", "subject": "Update on Order #{{order_number}}",
                                         "body": "Hi,\n\nRegarding your order #{{order_number}}:\n\nIssue: {{issue_type}}\nResolution: {{recommended_resolution}}\n\n{{resolution_details}}\n\nIf you have questions, reply to this email or call us.\n\nThank you,\n{{store_name}} Support"}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 1690},
                     "data": {"label": "End Call",
                              "config": {"message": "Your issue has been resolved! You'll receive an email confirmation shortly. Is there anything else I can help with today?"}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "shopify_1"},
                    {"source": "shopify_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "llm_1", "label": "Yes"},
                    {"source": "condition_1", "target": "conversation_2", "label": "No"},
                    {"source": "conversation_2", "target": "condition_retry"},
                    {"source": "condition_retry", "target": "shopify_1", "label": "Yes"},
                    {"source": "condition_retry", "target": "end_lookup", "label": "No"},
                    {"source": "llm_1", "target": "kb_1"},
                    {"source": "kb_1", "target": "condition_2"},
                    {"source": "condition_2", "target": "stripe_1", "label": "Yes"},
                    {"source": "condition_2", "target": "condition_exchange", "label": "No"},
                    {"source": "condition_exchange", "target": "shopify_2", "label": "Yes"},
                    {"source": "condition_exchange", "target": "sheets_1", "label": "No"},
                    {"source": "stripe_1", "target": "sheets_1"},
                    {"source": "shopify_2", "target": "sheets_1"},
                    {"source": "sheets_1", "target": "conversation_3"},
                    {"source": "conversation_3", "target": "email_1"},
                    {"source": "email_1", "target": "end_1"},
                ],
            },
            {
                "id": "saas_trial_conversion",
                "name": "SaaS Trial Conversion & Sales",
                "description": "Identify trial users, fetch usage data, recommend plan with AI, create Stripe customer and payment link, log conversion, and notify sales on Slack.",
                "category": "saas",
                "icon": "zap",
                "trigger_phrases": [
                    "I'm on a trial",
                    "upgrade my trial",
                    "trial expiring",
                    "pricing plans",
                    "convert to paid",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Identify Trial User",
                              "config": {"prompt": "Hi! I see you're reaching out about your {{product_name}} trial. Can you share your email so I can pull up your account? What's been your experience so far? What features have you been using? What's your name and company?",
                                         "variables_to_extract": ["user_email", "user_name", "company_name", "trial_feedback", "company_size"]}}},
                    {"id": "webhook_1", "type": "api_request", "position": {"x": 250, "y": 350},
                     "data": {"label": "Get Trial Usage",
                              "config": {"url": "{{app_api}}/users/trial-status", "method": "GET",
                                         "body": {"email": "{{user_email}}"},
                                         "response_mappings": {"trial_days_left": "$.days_left", "features_used": "$.features_used", "plan_eligible": "$.plan_eligible", "usage_score": "$.usage_score"}}}},
                    {"id": "kb_1", "type": "knowledge_base", "position": {"x": 250, "y": 500},
                     "data": {"label": "Search Plan Comparison",
                              "config": {"query": "pricing plans comparison features {{company_size}} team", "max_results": 3}}},
                    {"id": "llm_1", "type": "llm_process", "position": {"x": 250, "y": 650},
                     "data": {"label": "Recommend Plan",
                              "config": {"prompt": "Based on trial_feedback={{trial_feedback}}, features_used={{features_used}}, company_size={{company_size}}, and usage_score={{usage_score}}, recommend the best plan (Starter/Pro/Enterprise) with reasoning. Generate a personalized value proposition highlighting features they've already used and how the recommended plan enhances them.",
                                         "max_tokens": 600}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 250, "y": 800},
                     "data": {"label": "Present Recommendation",
                              "config": {"prompt": "Based on your usage, I'd recommend the {{recommended_plan}} plan at ${{price}}/month. Here's why: {{value_proposition}}. You've been using {{features_used}} which are all included. Would you like to upgrade? Also, would you prefer monthly or annual billing?",
                                         "variables_to_extract": ["wants_upgrade", "billing_cycle", "wants_demo"]}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 950},
                     "data": {"label": "Wants Upgrade?", "config": {"expression": "wants_upgrade == yes"}}},
                    {"id": "stripe_1", "type": "stripe", "position": {"x": 100, "y": 1100},
                     "data": {"label": "Create Customer",
                              "config": {"integration_type": "stripe", "action": "create_customer",
                                         "params": {"email": "{{user_email}}", "name": "{{user_name}}", "company": "{{company_name}}"}}}},
                    {"id": "stripe_2", "type": "stripe", "position": {"x": 100, "y": 1250},
                     "data": {"label": "Create Payment Link",
                              "config": {"integration_type": "stripe", "action": "create_payment_link",
                                         "params": {"plan": "{{recommended_plan}}", "billing": "{{billing_cycle}}", "customer": "{{stripe_customer_id}}"}}}},
                    {"id": "sms_1", "type": "send_sms", "position": {"x": 100, "y": 1400},
                     "data": {"label": "Send Payment Link",
                              "config": {"to": "{{caller_phone}}",
                                         "body": "Complete your {{product_name}} upgrade here: {{payment_url}}. Your trial features will carry over seamlessly!"}}},
                    {"id": "sheets_1", "type": "google_sheets", "position": {"x": 100, "y": 1550},
                     "data": {"label": "Log Conversion",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{conversions_sheet_id}}", "range": "Conversions!A:G",
                                                    "values": ["{{current_date}}", "{{user_email}}", "{{company_name}}", "{{recommended_plan}}", "{{billing_cycle}}", "{{trial_days_left}}", "{{usage_score}}"]}}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 100, "y": 1700},
                     "data": {"label": "Welcome to Paid Plan",
                              "config": {"to": "{{user_email}}", "subject": "Welcome to {{product_name}} {{recommended_plan}}!",
                                         "body": "Hi {{user_name}},\n\nWelcome to the {{recommended_plan}} plan! Your upgrade is being processed.\n\nHere are some onboarding resources to get the most out of your new plan:\n- Getting started guide: {{docs_url}}\n- Feature walkthroughs: {{walkthroughs_url}}\n- Community forum: {{community_url}}\n\nIf you have any questions, just reply to this email.\n\nWelcome aboard!\n{{product_name}} Team"}}},
                    {"id": "notification_1", "type": "notification", "position": {"x": 100, "y": 1850},
                     "data": {"label": "Alert Sales Team",
                              "config": {"channel": "slack", "message": "Trial conversion! {{user_name}} from {{company_name}} upgraded to {{recommended_plan}} ({{billing_cycle}}). Usage score: {{usage_score}}. Days left on trial: {{trial_days_left}}."}}},
                    {"id": "conversation_3", "type": "conversation", "position": {"x": 400, "y": 1100},
                     "data": {"label": "Address Hesitation",
                              "config": {"prompt": "I understand you'd like to think about it. Your trial has {{trial_days_left}} days left. Can I schedule a demo to show you the {{recommended_plan}} features in action? What day works best?",
                                         "variables_to_extract": ["demo_date", "demo_time"]}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 2000},
                     "data": {"label": "End Call",
                              "config": {"message": "Welcome to the {{recommended_plan}} plan, {{user_name}}! Check your text for the payment link and your email for onboarding resources. We're excited to have you onboard!"}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "webhook_1"},
                    {"source": "webhook_1", "target": "kb_1"},
                    {"source": "kb_1", "target": "llm_1"},
                    {"source": "llm_1", "target": "conversation_2"},
                    {"source": "conversation_2", "target": "condition_1"},
                    {"source": "condition_1", "target": "stripe_1", "label": "Yes"},
                    {"source": "condition_1", "target": "conversation_3", "label": "No"},
                    {"source": "stripe_1", "target": "stripe_2"},
                    {"source": "stripe_2", "target": "sms_1"},
                    {"source": "sms_1", "target": "sheets_1"},
                    {"source": "sheets_1", "target": "email_1"},
                    {"source": "email_1", "target": "notification_1"},
                    {"source": "notification_1", "target": "end_1"},
                    {"source": "conversation_3", "target": "end_1"},
                ],
            },
            {
                "id": "medical_billing_dispute",
                "name": "Medical Billing Dispute Resolution",
                "description": "Verify patient identity, fetch bill details, search KB for billing policies, analyze dispute with AI, submit corrections, and log to Sheets.",
                "category": "healthcare",
                "icon": "receipt",
                "trigger_phrases": [
                    "billing dispute",
                    "medical bill question",
                    "insurance denied claim",
                    "unexpected charge",
                    "bill is wrong",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Verify Patient",
                              "config": {"prompt": "I understand you have a concern about a medical bill. For security, can you please provide your full name, date of birth, and the patient account number from your bill? Also, what date was the bill issued and what amount are you disputing?",
                                         "variables_to_extract": ["patient_name", "date_of_birth", "account_number", "bill_date", "disputed_amount", "patient_email"]}}},
                    {"id": "webhook_1", "type": "api_request", "position": {"x": 250, "y": 350},
                     "data": {"label": "Fetch Bill Details",
                              "config": {"url": "{{billing_api}}/accounts/{{account_number}}/bills/{{bill_date}}", "method": "GET",
                                         "response_mappings": {"total_amount": "$.total", "services_list": "$.services", "insurance_paid": "$.insurance_paid", "patient_owes": "$.patient_owes", "billing_codes": "$.billing_codes"}}}},
                    {"id": "kb_1", "type": "knowledge_base", "position": {"x": 250, "y": 500},
                     "data": {"label": "Search Billing Policies",
                              "config": {"query": "medical billing dispute policy {{billing_codes}} patient responsibility", "max_results": 5}}},
                    {"id": "llm_1", "type": "llm_process", "position": {"x": 250, "y": 650},
                     "data": {"label": "Analyze Dispute",
                              "config": {"prompt": "Analyze this billing dispute: patient disputes ${{disputed_amount}} on bill totaling ${{total_amount}}. Services: {{services_list}}. Insurance paid ${{insurance_paid}}. Patient owes ${{patient_owes}}. Billing codes: {{billing_codes}}. Based on KB policies, determine if the dispute is valid, partially_valid, or invalid. Suggest resolution options and explain the reasoning.",
                                         "max_tokens": 700}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 800},
                     "data": {"label": "Dispute Valid?", "config": {"expression": "dispute_assessment == valid"}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 100, "y": 950},
                     "data": {"label": "Explain Valid Dispute",
                              "config": {"prompt": "I've reviewed your bill and your concern appears valid. Here's what I found: {{explanation}}. I can initiate a billing correction of ${{disputed_amount}}. This will take 5-7 business days to process. Shall I proceed?",
                                         "variables_to_extract": ["wants_correction"]}}},
                    {"id": "webhook_2", "type": "api_request", "position": {"x": 100, "y": 1100},
                     "data": {"label": "Submit Correction",
                              "config": {"url": "{{billing_api}}/corrections", "method": "POST",
                                         "body": {"account_number": "{{account_number}}", "bill_date": "{{bill_date}}", "disputed_amount": "{{disputed_amount}}", "reason": "{{dispute_reason}}", "approved_by": "AI_agent"},
                                         "response_mappings": {"correction_id": "$.correction_id"}}}},
                    {"id": "sheets_1", "type": "google_sheets", "position": {"x": 100, "y": 1250},
                     "data": {"label": "Log Dispute",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{billing_disputes_sheet_id}}", "range": "Disputes!A:F",
                                                    "values": ["{{current_date}}", "{{account_number}}", "{{patient_name}}", "{{disputed_amount}}", "{{dispute_assessment}}", "{{correction_id}}"]}}}},
                    {"id": "send_email_1", "type": "send_email", "position": {"x": 100, "y": 1400},
                     "data": {"label": "Dispute Resolution Email",
                              "config": {"to": "{{patient_email}}", "subject": "Billing Dispute Update — Account #{{account_number}}",
                                         "body": "Dear {{patient_name}},\n\nYour billing dispute for account #{{account_number}} has been reviewed.\n\nDisputed Amount: ${{disputed_amount}}\nAssessment: {{dispute_assessment}}\nCorrection ID: {{correction_id}}\n\nThe correction will be processed within 5-7 business days. You'll receive an updated statement shortly.\n\nIf you have questions, call us back and reference correction ID {{correction_id}}.\n\n{{clinic_name}} Billing Department"}}},
                    {"id": "conversation_3", "type": "conversation", "position": {"x": 400, "y": 950},
                     "data": {"label": "Explain Invalid Dispute",
                              "config": {"prompt": "I've reviewed your bill and the charges appear to be correct based on our billing policies. Here's the breakdown: {{explanation}}. However, I understand this may be a financial hardship. I can set up a payment plan if that would help. Would you like to explore that option?",
                                         "variables_to_extract": ["wants_payment_plan", "monthly_amount"]}}},
                    {"id": "notification_1", "type": "notification", "position": {"x": 250, "y": 1550},
                     "data": {"label": "Alert Billing Dept",
                              "config": {"channel": "slack", "message": "Billing dispute: {{patient_name}}, account #{{account_number}}, ${{disputed_amount}}. Assessment: {{dispute_assessment}}. Correction: {{correction_id}}."}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 1700},
                     "data": {"label": "End Call",
                              "config": {"message": "Your billing concern has been documented{{correction_status}}. You'll receive an email with all the details. If you have further questions, don't hesitate to call back and reference your account number {{account_number}}."}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "webhook_1"},
                    {"source": "webhook_1", "target": "kb_1"},
                    {"source": "kb_1", "target": "llm_1"},
                    {"source": "llm_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "conversation_2", "label": "Yes"},
                    {"source": "condition_1", "target": "conversation_3", "label": "No"},
                    {"source": "conversation_2", "target": "webhook_2"},
                    {"source": "webhook_2", "target": "sheets_1"},
                    {"source": "sheets_1", "target": "send_email_1"},
                    {"source": "send_email_1", "target": "notification_1"},
                    {"source": "conversation_3", "target": "sheets_1"},
                    {"source": "notification_1", "target": "end_1"},
                ],
            },
            {
                "id": "property_maintenance",
                "name": "Property Management Maintenance Request",
                "description": "Identify tenant issues, search KB for troubleshooting, triage with AI, log to Sheets, schedule maintenance, and alert for emergencies.",
                "category": "professional_services",
                "icon": "wrench",
                "trigger_phrases": [
                    "maintenance request",
                    "something is broken",
                    "repair needed",
                    "plumbing issue",
                    "electrical problem",
                    "heating not working",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Identify Tenant & Issue",
                              "config": {"prompt": "Hello, this is {{property_company}} maintenance line. Can you share your unit number, building name, and describe the maintenance issue? Is it plumbing, electrical, HVAC, appliance, structural, or something else? How urgent is it — is it an emergency (flooding, no heat in winter, electrical hazard), or can it wait a day or two? Also, what's your name and best contact number?",
                                         "variables_to_extract": ["unit_number", "building_name", "tenant_name", "tenant_phone", "issue_description", "issue_category", "urgency_level", "tenant_email"]}}},
                    {"id": "kb_1", "type": "knowledge_base", "position": {"x": 250, "y": 350},
                     "data": {"label": "Search Maintenance Guides",
                              "config": {"query": "{{issue_category}} troubleshooting {{building_name}}", "max_results": 3}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 500},
                     "data": {"label": "Emergency?", "config": {"expression": "urgency_level == emergency"}}},
                    {"id": "notification_1", "type": "notification", "position": {"x": 100, "y": 650},
                     "data": {"label": "Emergency Alert",
                              "config": {"channel": "slack", "message": "MAINTENANCE EMERGENCY: {{issue_category}} at {{building_name}} unit {{unit_number}}. Tenant: {{tenant_name}}. Issue: {{issue_description}}. Immediate dispatch required."}}},
                    {"id": "transfer_1", "type": "transfer_call", "position": {"x": 100, "y": 800},
                     "data": {"label": "Emergency Dispatch",
                              "config": {"transfer_to": "{{emergency_maintenance_number}}",
                                         "transfer_message": "This appears to be an emergency. I'm connecting you to our emergency maintenance team immediately.",
                                         "whisper_message": "Emergency: {{issue_category}} at {{building_name}} unit {{unit_number}}. {{issue_description}}. Tenant: {{tenant_name}} ({{tenant_phone}})"}}},
                    {"id": "llm_1", "type": "llm_process", "position": {"x": 400, "y": 650},
                     "data": {"label": "Triage & Prioritize",
                              "config": {"prompt": "Based on issue_category={{issue_category}}, urgency={{urgency_level}}, and building={{building_name}}, determine priority (P1-P4), estimated repair time, and required technician type (plumber/electrician/HVAC/general). Also check if KB troubleshooting steps could resolve it.",
                                         "max_tokens": 400}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 400, "y": 800},
                     "data": {"label": "Self-Service Option",
                              "config": {"prompt": "Before I schedule a technician, I found some troubleshooting steps that might resolve this. Would you like to try them first, or would you prefer to schedule a maintenance visit?",
                                         "variables_to_extract": ["wants_self_service", "tried_troubleshooting"]}}},
                    {"id": "condition_2", "type": "condition", "position": {"x": 400, "y": 950},
                     "data": {"label": "Self-Service Resolved?", "config": {"expression": "tried_troubleshooting == resolved"}}},
                    {"id": "sheets_1", "type": "google_sheets", "position": {"x": 250, "y": 1100},
                     "data": {"label": "Log Request",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{maintenance_sheet_id}}", "range": "Requests!A:J",
                                                    "values": ["{{current_date}}", "{{building_name}}", "{{unit_number}}", "{{tenant_name}}", "{{issue_category}}", "{{issue_description}}", "{{urgency_level}}", "{{priority}}", "{{technician_type}}", "{{status}}"]}}}},
                    {"id": "action_1", "type": "action", "position": {"x": 250, "y": 1250},
                     "data": {"label": "Schedule Maintenance Visit",
                              "config": {"integration_type": "google_calendar", "action": "create_event",
                                         "params": {"title": "Maintenance - {{building_name}} Unit {{unit_number}}", "date": "{{preferred_date}}",
                                                    "description": "Issue: {{issue_description}}\nCategory: {{issue_category}}\nPriority: {{priority}}\nTechnician: {{technician_type}}\nTenant: {{tenant_name}} ({{tenant_phone}})"}}}},
                    {"id": "sms_1", "type": "send_sms", "position": {"x": 250, "y": 1400},
                     "data": {"label": "Confirmation SMS",
                              "config": {"to": "{{tenant_phone}}",
                                         "body": "Maintenance scheduled for {{building_name}} unit {{unit_number}} on {{preferred_date}}. Technician: {{technician_type}}. Reply CANCEL to reschedule."}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 250, "y": 1550},
                     "data": {"label": "Details to Tenant",
                              "config": {"to": "{{tenant_email}}", "subject": "Maintenance Request Confirmed — {{building_name}}",
                                         "body": "Dear {{tenant_name}},\n\nYour maintenance request has been scheduled:\n\nBuilding: {{building_name}}\nUnit: {{unit_number}}\nDate: {{preferred_date}}\nTechnician: {{technician_type}}\nIssue: {{issue_description}}\n\nPlease ensure access to the unit. If you need to reschedule, reply to this email or call us.\n\n{{property_company}}"}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 1700},
                     "data": {"label": "End Call",
                              "config": {"message": "Your maintenance request has been logged{{visit_scheduled}}. You'll receive SMS and email confirmation. If the issue worsens, call us back and mention emergency."}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "kb_1"},
                    {"source": "kb_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "notification_1", "label": "Yes"},
                    {"source": "condition_1", "target": "llm_1", "label": "No"},
                    {"source": "notification_1", "target": "transfer_1"},
                    {"source": "llm_1", "target": "conversation_2"},
                    {"source": "conversation_2", "target": "condition_2"},
                    {"source": "condition_2", "target": "sheets_1", "label": "Yes"},
                    {"source": "condition_2", "target": "action_1", "label": "No"},
                    {"source": "action_1", "target": "sheets_1"},
                    {"source": "sheets_1", "target": "sms_1"},
                    {"source": "sms_1", "target": "email_1"},
                    {"source": "email_1", "target": "end_1"},
                ],
            },
            {
                "id": "saas_churn_prevention",
                "name": "SaaS Churn Prevention & Winback",
                "description": "Understand churn reasons, fetch account data, generate AI retention strategy, apply offers, schedule demos, log risk, and alert customer success on Slack.",
                "category": "saas",
                "icon": "shield",
                "trigger_phrases": [
                    "cancel my account",
                    "I want to cancel",
                    "thinking of leaving",
                    "not happy with the product",
                    "switching to competitor",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Understand Churn Reason",
                              "config": {"prompt": "I'm sorry to hear you're considering leaving {{product_name}}. I'd love to understand what's not working for you. Can you tell me about your experience and what's driving this decision? Are there specific features missing? Are you considering a competitor? What's your name, email, and company?",
                                         "variables_to_extract": ["user_email", "churn_reason", "competitor_name", "usage_frequency", "feature_gaps", "user_name", "company_name"]}}},
                    {"id": "webhook_1", "type": "api_request", "position": {"x": 250, "y": 350},
                     "data": {"label": "Get Account Data",
                              "config": {"url": "{{app_api}}/users/account", "method": "GET",
                                         "body": {"email": "{{user_email}}"},
                                         "response_mappings": {"plan_tier": "$.plan", "monthly_value": "$.monthly_value", "days_active": "$.days_active", "last_login": "$.last_login", "features_used": "$.features_used", "support_tickets": "$.support_tickets"}}}},
                    {"id": "kb_1", "type": "knowledge_base", "position": {"x": 250, "y": 500},
                     "data": {"label": "Search Winback Offers",
                              "config": {"query": "retention winback offer {{plan_tier}} {{churn_reason}}", "max_results": 5}}},
                    {"id": "llm_1", "type": "llm_process", "position": {"x": 250, "y": 650},
                     "data": {"label": "Generate Retention Strategy",
                              "config": {"prompt": "Based on churn_reason={{churn_reason}}, competitor={{competitor_name}}, features_used={{features_used}}, feature_gaps={{feature_gaps}}, and KB winback offers, generate a personalized retention strategy. Include: (1) empathy response, (2) feature gap solutions or workarounds, (3) competitive differentiation, (4) best retention offer (discount/feature unlock/extended trial). Prioritize by likelihood of retention.",
                                         "max_tokens": 800}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 250, "y": 800},
                     "data": {"label": "Address Concerns",
                              "config": {"prompt": "I understand your frustration with {{churn_reason}}. Let me address that: {{addressed_concern}}. Also, many of our customers who considered {{competitor_name}} found that {{competitive_advantage}}. I'd like to offer you {{retention_offer}}. Would that change your mind?",
                                         "variables_to_extract": ["offer_accepted", "wants_feature_demo", "wants_to_think"]}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 950},
                     "data": {"label": "Offer Accepted?", "config": {"expression": "offer_accepted == yes"}}},
                    {"id": "webhook_2", "type": "api_request", "position": {"x": 100, "y": 1100},
                     "data": {"label": "Apply Retention Offer",
                              "config": {"url": "{{app_api}}/accounts/retention", "method": "POST",
                                         "body": {"user_email": "{{user_email}}", "offer_type": "{{offer_type}}", "discount": "{{discount_amount}}", "duration": "{{offer_duration}}"}}}},
                    {"id": "sheets_1", "type": "google_sheets", "position": {"x": 100, "y": 1250},
                     "data": {"label": "Log Churn Risk",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{churn_log_sheet_id}}", "range": "Churn!A:I",
                                                    "values": ["{{current_date}}", "{{user_email}}", "{{company_name}}", "{{plan_tier}}", "{{churn_reason}}", "{{competitor_name}}", "{{offer_type}}", "{{offer_accepted}}", "{{monthly_value}}"]}}}},
                    {"id": "condition_demo", "type": "condition", "position": {"x": 400, "y": 1250},
                     "data": {"label": "Feature Demo Requested?", "config": {"expression": "wants_feature_demo == yes"}}},
                    {"id": "conversation_3", "type": "conversation", "position": {"x": 100, "y": 1400},
                     "data": {"label": "Schedule Feature Demo",
                              "config": {"prompt": "Great! Let me also schedule a personalized demo of the features you mentioned are missing. What day works best for you?",
                                         "variables_to_extract": ["demo_date", "demo_time"]}}},
                    {"id": "action_1", "type": "action", "position": {"x": 100, "y": 1550},
                     "data": {"label": "Book Demo",
                              "config": {"integration_type": "google_calendar", "action": "create_event",
                                         "params": {"title": "Feature Demo - {{user_name}} ({{company_name}})", "date": "{{demo_date}}", "time": "{{demo_time}}",
                                                    "description": "Churn prevention demo. Gaps: {{feature_gaps}}. Competitor: {{competitor_name}}."}}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 100, "y": 1700},
                     "data": {"label": "Offer Confirmation",
                              "config": {"to": "{{user_email}}", "subject": "Your {{product_name}} Offer — We're Keeping You!",
                                         "body": "Hi {{user_name}},\n\nThank you for giving us the chance to make things right. Your retention offer is active:\n\nOffer: {{offer_type}}\nDiscount: {{discount_amount}}\nDuration: {{offer_duration}}\n\nYour feature demo is scheduled for {{demo_date}} at {{demo_time}}.\n\nWe're committed to making {{product_name}} work great for you.\n\n{{product_name}} Team"}}},
                    {"id": "notification_1", "type": "notification", "position": {"x": 100, "y": 1850},
                     "data": {"label": "Alert Customer Success",
                              "config": {"channel": "slack", "message": "Churn risk: {{user_name}} from {{company_name}} ({{plan_tier}}, ${{monthly_value}}/mo). Reason: {{churn_reason}}. Competitor: {{competitor_name}}. Offer: {{offer_type}}. Status: {{offer_accepted}}."}}},
                    {"id": "conversation_4", "type": "conversation", "position": {"x": 700, "y": 1400},
                     "data": {"label": "Final Check",
                              "config": {"prompt": "Is there anything else I can do to make your experience better? I'm here to help.",
                                         "variables_to_extract": ["additional_concerns"]}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 2000},
                     "data": {"label": "End Call",
                              "config": {"message": "Thank you for talking this through, {{user_name}}. We've recorded the agreed next steps and our customer success team has been notified."}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "webhook_1"},
                    {"source": "webhook_1", "target": "kb_1"},
                    {"source": "kb_1", "target": "llm_1"},
                    {"source": "llm_1", "target": "conversation_2"},
                    {"source": "conversation_2", "target": "condition_1"},
                    {"source": "condition_1", "target": "webhook_2", "label": "Yes"},
                    {"source": "condition_1", "target": "sheets_1", "label": "No"},
                    {"source": "webhook_2", "target": "sheets_1"},
                    {"source": "sheets_1", "target": "condition_demo"},
                    {"source": "condition_demo", "target": "conversation_3", "label": "Yes"},
                    {"source": "condition_demo", "target": "conversation_4", "label": "No"},
                    {"source": "conversation_3", "target": "action_1"},
                    {"source": "action_1", "target": "email_1"},
                    {"source": "email_1", "target": "notification_1"},
                    {"source": "notification_1", "target": "end_1"},
                    {"source": "conversation_4", "target": "notification_1"},
                ],
            },
            {
                "id": "legal_consultation_intake",
                "name": "Legal Consultation Intake",
                "description": "Identify legal needs, match with attorney via KB + LLM, conflict check, schedule consultation, log to Sheets, and send confirmation email.",
                "category": "professional_services",
                "icon": "scale",
                "trigger_phrases": [
                    "legal advice",
                    "speak with a lawyer",
                    "attorney consultation",
                    "legal matter",
                    "need legal help",
                ],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Call Received", "config": {}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 180},
                     "data": {"label": "Identify Legal Need",
                              "config": {"prompt": "Thank you for calling {{law_firm}}. I understand you need legal assistance. Can you tell me the general nature of your matter — family law, criminal defense, personal injury, business law, estate planning, or immigration? Please keep details brief for now. Also, may I have your name, email, and phone number?",
                                         "variables_to_extract": ["legal_category", "caller_name", "caller_email", "caller_phone", "brief_description"]}}},
                    {"id": "kb_1", "type": "knowledge_base", "position": {"x": 250, "y": 350},
                     "data": {"label": "Search Attorney Bios",
                              "config": {"query": "{{legal_category}} attorney lawyer specialization experience", "max_results": 5}}},
                    {"id": "llm_1", "type": "llm_process", "position": {"x": 250, "y": 500},
                     "data": {"label": "Match Attorney",
                              "config": {"prompt": "Based on legal_category={{legal_category}} and the KB attorney bios, recommend the best-fit attorney. Include their experience level, notable cases, and consultation fee. Generate a brief confidence explanation.",
                                         "max_tokens": 500}}},
                    {"id": "note_1", "type": "note", "position": {"x": 250, "y": 650},
                     "data": {"label": "Conflict Check Reminder",
                              "config": {"content": "CONFLICT CHECK: Before scheduling, verify no conflict of interest with opposing party. Ask caller for names of all parties involved. If conflict exists, politely decline and recommend another firm."}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 250, "y": 800},
                     "data": {"label": "Conflict Check",
                              "config": {"prompt": "Before we schedule, I need to verify there's no conflict of interest. Can you share the names of all parties involved in this matter? This is standard procedure and completely confidential.",
                                         "variables_to_extract": ["parties_involved", "conflict_clear"]}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 950},
                     "data": {"label": "Conflict Clear?", "config": {"expression": "conflict_clear == yes"}}},
                    {"id": "conversation_3", "type": "conversation", "position": {"x": 100, "y": 1100},
                     "data": {"label": "Schedule Consultation",
                              "config": {"prompt": "Great, no conflicts detected. I'd recommend {{attorney_name}}, who has {{years_experience}} years of experience in {{legal_category}}. The initial consultation is ${{consultation_fee}}. Would you like to schedule? What date and time work best? Would you prefer in-person or virtual?",
                                         "variables_to_extract": ["wants_consultation", "preferred_date", "preferred_time", "consultation_format"]}}},
                    {"id": "action_1", "type": "action", "position": {"x": 100, "y": 1250},
                     "data": {"label": "Book Consultation",
                              "config": {"integration_type": "google_calendar", "action": "create_event",
                                         "params": {"title": "Legal Consultation - {{caller_name}} with {{attorney_name}}", "date": "{{preferred_date}}", "time": "{{preferred_time}}",
                                                    "description": "Category: {{legal_category}}\nParties: {{parties_involved}}\nFormat: {{consultation_format}}\nFee: ${{consultation_fee}}\nBrief: {{brief_description}}"}}}},
                    {"id": "sheets_1", "type": "google_sheets", "position": {"x": 100, "y": 1400},
                     "data": {"label": "Log Intake",
                              "config": {"integration_type": "google_sheets", "action": "append_row",
                                         "params": {"spreadsheet_id": "{{legal_intake_sheet_id}}", "range": "Intakes!A:G",
                                                    "values": ["{{current_date}}", "{{caller_name}}", "{{legal_category}}", "{{attorney_name}}", "{{consultation_fee}}", "{{preferred_date}}", "{{conflict_clear}}"]}}}},
                    {"id": "email_1", "type": "send_email", "position": {"x": 100, "y": 1550},
                     "data": {"label": "Consultation Confirmation",
                              "config": {"to": "{{caller_email}}", "subject": "Consultation Confirmed with {{attorney_name}}",
                                         "body": "Dear {{caller_name}},\n\nYour consultation with {{attorney_name}} is confirmed:\n\nDate: {{preferred_date}}\nTime: {{preferred_time}}\nFormat: {{consultation_format}}\nFee: ${{consultation_fee}}\n\nWhat to bring:\n- Any relevant documents\n- List of witnesses (if applicable)\n- Timeline of events\n- Questions for the attorney\n\nCONFIDENTIALITY NOTICE: This communication is privileged and confidential.\n\n{{law_firm}}"}}},
                    {"id": "conversation_4", "type": "conversation", "position": {"x": 400, "y": 1100},
                     "data": {"label": "Conflict Declined",
                              "config": {"prompt": "I apologize, but we've identified a potential conflict of interest and cannot represent you in this matter. This is a standard ethical requirement. I'd recommend contacting the state bar association for a referral to another qualified attorney. Is there anything else I can help with?",
                                         "variables_to_extract": ["needs_referral"]}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 250, "y": 1700},
                     "data": {"label": "End Call",
                              "config": {"message": "Your consultation with {{attorney_name}} is scheduled for {{preferred_date}}. Please check your email for important preparation instructions. Remember, this is not legal advice until your formal consultation. Thank you for calling {{law_firm}}."}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "conversation_1"},
                    {"source": "conversation_1", "target": "kb_1"},
                    {"source": "kb_1", "target": "llm_1"},
                    {"source": "llm_1", "target": "note_1"},
                    {"source": "note_1", "target": "conversation_2"},
                    {"source": "conversation_2", "target": "condition_1"},
                    {"source": "condition_1", "target": "conversation_3", "label": "Yes"},
                    {"source": "condition_1", "target": "conversation_4", "label": "No"},
                    {"source": "conversation_3", "target": "action_1"},
                    {"source": "action_1", "target": "sheets_1"},
                    {"source": "sheets_1", "target": "email_1"},
                    {"source": "email_1", "target": "end_1"},
                    {"source": "conversation_4", "target": "end_1"},
                ],
            },
            {
                "id": "outbound_appointment_reminder",
                "name": "Outbound Appointment Reminder & Rescheduling",
                "description": "Outbound call to remind patients of upcoming appointments, detect voicemail, confirm or reschedule with calendar integration, and send SMS.",
                "category": "healthcare",
                "icon": "phone-outgoing",
                "trigger_phrases": [],
                "nodes": [
                    {"id": "trigger_1", "type": "trigger", "position": {"x": 250, "y": 50},
                     "data": {"label": "Outbound Call", "config": {}}},
                    {"id": "voicemail_1", "type": "voicemail_detect", "position": {"x": 250, "y": 180},
                     "data": {"label": "Detect Voicemail",
                              "config": {"voicemail_message": "Hello, this is a reminder from {{clinic_name}}. You have an appointment on {{appointment_date}} at {{appointment_time}} with {{doctor_name}}. Please call us back at {{clinic_phone}} to confirm or reschedule. Thank you!"}}},
                    {"id": "conversation_1", "type": "conversation", "position": {"x": 250, "y": 340},
                     "data": {"label": "Reminder & Confirm",
                              "config": {"prompt": "Hello, this is a reminder from {{clinic_name}}. You have an appointment on {{appointment_date}} at {{appointment_time}} with {{doctor_name}}. Can you still make it? If yes, I'll confirm. If no, I can help you reschedule right now.",
                                         "variables_to_extract": ["confirmation_status", "patient_name"]}}},
                    {"id": "condition_1", "type": "condition", "position": {"x": 250, "y": 490},
                     "data": {"label": "Confirmed?", "config": {"expression": "confirmation_status == confirmed"}}},
                    {"id": "sms_1", "type": "send_sms", "position": {"x": 100, "y": 640},
                     "data": {"label": "Confirmation SMS",
                              "config": {"to": "{{caller_phone}}",
                                         "body": "Confirmed: Your appointment with {{doctor_name}} on {{appointment_date}} at {{appointment_time}}. Reply CANCEL to cancel or RESCHEDULE to change. - {{clinic_name}}"}}},
                    {"id": "end_1", "type": "end_call", "position": {"x": 100, "y": 790},
                     "data": {"label": "Confirmed End",
                              "config": {"message": "Great, we'll see you on {{appointment_date}} at {{appointment_time}}! You'll receive a text confirmation. Have a good day, {{patient_name}}!"}}},
                    {"id": "conversation_2", "type": "conversation", "position": {"x": 400, "y": 640},
                     "data": {"label": "Reschedule Flow",
                              "config": {"prompt": "No problem! When would you prefer to reschedule? I can check availability for the next two weeks. What day and time work best for you?",
                                         "variables_to_extract": ["new_date", "new_time", "reschedule_reason"]}}},
                    {"id": "action_1", "type": "action", "position": {"x": 400, "y": 790},
                     "data": {"label": "Check Availability",
                              "config": {"integration_type": "google_calendar", "action": "check_availability",
                                         "params": {"date": "{{new_date}}", "time": "{{new_time}}"}}}},
                    {"id": "condition_2", "type": "condition", "position": {"x": 400, "y": 940},
                     "data": {"label": "Slot Available?", "config": {"expression": "result.requested_time_available == true"}}},
                    {"id": "action_2", "type": "action", "position": {"x": 400, "y": 1090},
                     "data": {"label": "Create New Event",
                              "config": {"integration_type": "google_calendar", "action": "create_event",
                                         "params": {"title": "{{patient_name}} - Rescheduled", "date": "{{new_date}}", "time": "{{new_time}}",
                                                    "description": "Rescheduled from {{appointment_date}}. Reason: {{reschedule_reason}}. Doctor: {{doctor_name}}"}}}},
                    {"id": "action_3", "type": "action", "position": {"x": 400, "y": 1240},
                     "data": {"label": "Cancel Old Event",
                              "config": {"integration_type": "google_calendar", "action": "delete_event",
                                         "params": {"event_id": "{{original_event_id}}"}}}},
                    {"id": "delay_1", "type": "delay", "position": {"x": 400, "y": 1390},
                     "data": {"label": "Ensure Calendar Sync", "config": {"delay_seconds": 2}}},
                    {"id": "sms_2", "type": "send_sms", "position": {"x": 400, "y": 1520},
                     "data": {"label": "New Appointment SMS",
                              "config": {"to": "{{caller_phone}}",
                                         "body": "Rescheduled: Your appointment with {{doctor_name}} is now on {{new_date}} at {{new_time}}. Reply CANCEL to cancel. - {{clinic_name}}"}}},
                    {"id": "end_2", "type": "end_call", "position": {"x": 250, "y": 1670},
                     "data": {"label": "Rescheduled End",
                              "config": {"message": "Your appointment has been rescheduled to {{new_date}} at {{new_time}}. You'll receive a text confirmation shortly. Take care, {{patient_name}}!"}}},
                    {"id": "conversation_3", "type": "conversation", "position": {"x": 700, "y": 1090},
                     "data": {"label": "Suggest Other Times",
                              "config": {"prompt": "Unfortunately that slot isn't available. Offer only real openings from the flow context, or ask for another date and time if none are listed.",
                                         "variables_to_extract": ["new_date", "new_time"]}}},
                    {"id": "condition_retry", "type": "condition", "position": {"x": 700, "y": 1240},
                     "data": {"label": "Retries Left?", "config": {"expression": "_slot_retry_count < 2"}}},
                    {"id": "end_retry", "type": "end_call", "position": {"x": 700, "y": 1390},
                     "data": {"label": "Reschedule Not Completed", "config": {"message": "I could not confirm an available replacement time after several checks. Please contact the clinic to reschedule."}}},
                ],
                "edges": [
                    {"source": "trigger_1", "target": "voicemail_1"},
                    {"source": "voicemail_1", "target": "conversation_1", "label": "Human"},
                    {"source": "voicemail_1", "target": "end_1", "label": "Voicemail"},
                    {"source": "conversation_1", "target": "condition_1"},
                    {"source": "condition_1", "target": "sms_1", "label": "Yes"},
                    {"source": "sms_1", "target": "end_1"},
                    {"source": "condition_1", "target": "conversation_2", "label": "No"},
                    {"source": "conversation_2", "target": "action_1"},
                    {"source": "action_1", "target": "condition_2"},
                    {"source": "condition_2", "target": "action_2", "label": "Yes"},
                    {"source": "condition_2", "target": "conversation_3", "label": "No"},
                    {"source": "action_2", "target": "action_3"},
                    {"source": "action_3", "target": "delay_1"},
                    {"source": "delay_1", "target": "sms_2"},
                    {"source": "sms_2", "target": "end_2"},
                    {"source": "conversation_3", "target": "condition_retry"},
                    {"source": "condition_retry", "target": "action_1", "label": "Yes"},
                    {"source": "condition_retry", "target": "end_retry", "label": "No"},
                ],
            },
        ])
    }


@router.get("")
async def list_workflows(
    include_inactive: bool = Query(default=False, description="Include deactivated workflows"),
    agent_id: Optional[int] = Query(default=None, description="Filter workflows by linked agent ID"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all workflows belonging to the current user.

    Returns workflows sorted by creation date (newest first).
    The trigger_phrases field is returned as a parsed JSON array.
    By default, only active workflows are returned.

    Returns:
        List of workflow objects
    """
    query = select(Workflow).where(Workflow.user_id == user.id)
    if not include_inactive:
        query = query.where(Workflow.is_active == True)
    if agent_id is not None:
        query = query.where(Workflow.agent_id == agent_id)
    query = query.order_by(Workflow.created_at.desc())

    result = await db.execute(query)
    workflows = result.scalars().all()

    # Parse trigger_phrases from JSON string back to list for each workflow
    workflow_dicts = []
    for wf in workflows:
        d = wf.to_dict()
        d["trigger_phrases"] = normalize_trigger_phrases(d.get("trigger_phrases"))
        workflow_dicts.append(d)

    return {"workflows": workflow_dicts}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workflow(
    request: CreateWorkflowRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new intent-based workflow.

    The trigger_phrases list defines when this workflow activates.
    During a call, if the LLM detects the user's intent matches any
    of these phrases, the associated action is executed.

    Args:
        request: Workflow configuration
        user: Authenticated user
        db: Database session
        
    Returns:
        Created workflow object (HTTP 201)
    """
    trigger_phrases = normalize_trigger_phrases(request.trigger_phrases)
    if not trigger_phrases:
        raise ValidationError(
            field="trigger_phrases",
            message="trigger_phrases must contain at least one phrase",
            suggestion="Add at least one trigger phrase to activate the workflow.",
        )

    # Serialize trigger_phrases list to JSON string for storage
    trigger_phrases_json = json.dumps(trigger_phrases)

    # Validate agent_id belongs to the current user if provided.
    linked_agent: Agent | None = None
    if request.agent_id is not None:
        agent_result = await db.execute(
            select(Agent).where(
                Agent.id == request.agent_id,
                Agent.user_id == user.id,
            )
        )
        linked_agent = agent_result.scalar_one_or_none()
        if linked_agent is None:
            raise AgentNotFoundError(request.agent_id, suggestion="Check the agent ID and ensure you have access to it.")
        if request.graph is not None:
            await _ensure_single_agent_graph_owner(db, int(user.id), request.agent_id)

    # Serialize steps to JSON if provided — but only when no graph is present.
    # When graph_json is provided, it is the source of truth and steps_json is
    # legacy redundancy that can diverge. Skip steps_json to keep a single source.
    steps_json = None
    if request.steps and not request.graph:
        steps_json = json.dumps([s.model_dump() for s in request.steps])

    # Serialize graph state for lossless round-trip
    graph_json = None
    graph_warnings: list[str] = []
    if request.graph:
        graph_warnings = _validate_graph(request.graph)
        graph_json = json.dumps(request.graph)
        if graph_warnings:
            logger.warning(f"Workflow graph validation warnings for '{request.name}': {graph_warnings}")

    workflow = Workflow(
        user_id=user.id,
        name=request.name,
        description=request.description,
        trigger_phrases=trigger_phrases_json,
        agent_id=request.agent_id,
        action_type=request.action_type,
        action_url=request.action_url,
        requires_approval=request.requires_approval,
        transition_flexibility=request.transition_flexibility or "flex",
        steps_json=steps_json,
        graph_json=graph_json,
    )

    db.add(workflow)
    await db.flush()

    # The workflow is canonical. graph_json remains mirrored on Agent only for
    # compatibility with older readers and is updated in the same transaction.
    if linked_agent is not None and graph_json is not None:
        linked_agent.workflow_id = workflow.id
        linked_agent.graph_json = graph_json
        linked_agent.mode = "conversational_flow"
        linked_agent.transition_flexibility = request.transition_flexibility or "flex"
        logger.info(
            f"Published canonical workflow #{workflow.id} to agent #{linked_agent.id}"
        )

    await db.commit()
    await db.refresh(workflow)

    # Return with parsed trigger_phrases
    result = workflow.to_dict()
    result["trigger_phrases"] = trigger_phrases

    return {"workflow": result, "graph_warnings": graph_warnings}


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get details of a specific workflow.

    Only returns the workflow if it belongs to the current user.
    """
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
    )
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise WorkflowNotFoundError(workflow_id)

    d = workflow.to_dict()
    d["trigger_phrases"] = normalize_trigger_phrases(d.get("trigger_phrases"))

    return {"workflow": d}


@router.put("/{workflow_id}")
async def update_workflow(
    workflow_id: int,
    request: UpdateWorkflowRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a workflow's configuration.

    Only updates fields that were provided in the request.
    """
    result = await db.execute(
        select(Workflow)
        .where(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
        .with_for_update()
    )
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise WorkflowNotFoundError(workflow_id)

    old_agent_id = workflow.agent_id
    old_graph_json = workflow.graph_json

    # Get non-None fields from request
    update_data = request.model_dump(exclude_unset=True)
    expected_graph_hash = update_data.pop("expected_graph_hash", None)

    if "graph" in update_data and workflow.graph_json is not None:
        try:
            current_graph = json.loads(workflow.graph_json)
        except (TypeError, json.JSONDecodeError):
            raise ValidationError(
                field="graph",
                message="The stored workflow graph is corrupted and cannot be updated safely.",
                suggestion="Restore a known-good graph revision before saving new edits.",
            )
        current_graph_hash = canonical_content_hash(current_graph)
        if expected_graph_hash is None:
            raise HTTPException(
                status_code=428,
                detail=(
                    "expected_graph_hash is required when updating an existing graph. "
                    "Reload the workflow and retry."
                ),
            )
        if expected_graph_hash != current_graph_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This workflow graph changed after the editor loaded it. "
                    "Reload before saving so the newer graph is not overwritten."
                ),
            )

    # Special handling: serialize trigger_phrases to JSON if provided
    if "trigger_phrases" in update_data and update_data["trigger_phrases"] is not None:
        parsed = normalize_trigger_phrases(update_data["trigger_phrases"])
        if not parsed:
            raise ValidationError(
            field="trigger_phrases",
            message="trigger_phrases must contain at least one phrase",
            suggestion="Add at least one trigger phrase to activate the workflow.",
        )
        update_data["trigger_phrases"] = json.dumps(parsed)

    # Keep create/update behavior consistent: validate agent ownership when provided.
    if "agent_id" in update_data and update_data["agent_id"] is not None:
        agent_result = await db.execute(
            select(Agent).where(
                Agent.id == update_data["agent_id"],
                Agent.user_id == user.id,
            )
        )
        if agent_result.scalar_one_or_none() is None:
            raise AgentNotFoundError(update_data["agent_id"], suggestion="Check the agent ID and ensure you have access to it.")
    
    # Special handling: serialize steps to JSON if provided — but skip when
    # graph is also being updated (graph is the source of truth).
    has_graph_update = "graph" in update_data and update_data["graph"] is not None
    if "steps" in update_data:
        if update_data["steps"] is not None and not has_graph_update:
            update_data["steps_json"] = json.dumps([
                s.model_dump() if hasattr(s, "model_dump") else s
                for s in update_data["steps"]
            ])
        elif has_graph_update:
            # Graph is being updated — clear legacy steps_json to avoid divergence
            update_data["steps_json"] = None
        else:
            update_data["steps_json"] = None
        del update_data["steps"]

    # Special handling: serialize graph to JSON if provided
    graph_warnings: list[str] = []
    if "graph" in update_data:
        if update_data["graph"] is not None:
            graph_warnings = _validate_graph(update_data["graph"])
            update_data["graph_json"] = json.dumps(update_data["graph"])
            if graph_warnings:
                logger.warning(f"Workflow graph validation warnings for workflow {workflow_id}: {graph_warnings}")
        else:
            update_data["graph_json"] = None
        del update_data["graph"]

    resulting_agent_id = update_data.get("agent_id", workflow.agent_id)
    resulting_graph_json = update_data.get("graph_json", workflow.graph_json)
    resulting_is_active = update_data.get("is_active", workflow.is_active)
    if (
        resulting_is_active
        and resulting_agent_id is not None
        and resulting_graph_json is not None
        and (
            "agent_id" in update_data
            or "graph_json" in update_data
            or update_data.get("is_active") is True
        )
    ):
        await _ensure_single_agent_graph_owner(
            db,
            int(user.id),
            int(resulting_agent_id),
            exclude_workflow_id=workflow_id,
        )
    
    # Apply updates only to known ORM columns. New schema fields that do not
    # exist on the Workflow model must be remapped above or they are ignored.
    allowed_fields = {
        "name",
        "description",
        "trigger_phrases",
        "agent_id",
        "action_type",
        "action_url",
        "requires_approval",
        "transition_flexibility",
        "is_active",
        "steps_json",
        "graph_json",
    }
    for field, value in update_data.items():
        if field in allowed_fields:
            setattr(workflow, field, value)

    # Atomically publish the canonical workflow and maintain graph_json only as
    # a compatibility mirror for older readers.
    sync_graph = resulting_graph_json if (
        resulting_is_active
        and (
            "graph_json" in update_data
            or "agent_id" in update_data
            or "is_active" in update_data
            or "transition_flexibility" in update_data
        )
    ) else None
    sync_agent_id = update_data.get("agent_id", workflow.agent_id)
    sync_flex = update_data.get("transition_flexibility", workflow.transition_flexibility)
    if sync_graph is not None and sync_agent_id is not None:
        agent_result = await db.execute(
            select(Agent).where(
                Agent.id == sync_agent_id,
                Agent.user_id == user.id,
            )
        )
        agent = agent_result.scalar_one_or_none()
        if agent:
            agent.workflow_id = workflow_id
            agent.graph_json = sync_graph
            agent.mode = "conversational_flow"
            agent.transition_flexibility = sync_flex or "flex"
            logger.info(
                f"Published canonical workflow #{workflow_id} to agent #{agent.id}"
            )

    should_detach_old_agent = (
        old_agent_id is not None
        and (
            old_agent_id != sync_agent_id
            or not resulting_is_active
            or resulting_graph_json is None
        )
    )
    if should_detach_old_agent:
        old_agent = await db.get(Agent, old_agent_id)
        if old_agent and old_agent.user_id == user.id:
            owns_workflow = old_agent.workflow_id == workflow_id
            if owns_workflow:
                old_agent.workflow_id = None
            if owns_workflow or old_agent.graph_json == old_graph_json:
                old_agent.graph_json = None
            if old_agent.graph_json is None and old_agent.mode == "conversational_flow":
                old_agent.mode = "single_prompt"
            logger.info(
                f"Detached workflow #{workflow_id} from previous agent #{old_agent_id}"
            )

    await db.commit()
    await db.refresh(workflow)
    
    d = workflow.to_dict()
    d["trigger_phrases"] = normalize_trigger_phrases(d.get("trigger_phrases"))
    
    return {"workflow": d, "graph_warnings": graph_warnings}


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Deactivate a workflow (soft delete).
    
    Sets is_active=False instead of deleting the record.
    """
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
    )
    workflow = result.scalar_one_or_none()
    
    if workflow is None:
        raise WorkflowNotFoundError(workflow_id)
    
    workflow.is_active = False  # type: ignore[assignment]

    if workflow.agent_id is not None and workflow.graph_json is not None:
        graph_owner = await db.get(Agent, workflow.agent_id)
        if (
            graph_owner
            and graph_owner.user_id == user.id
        ):
            owns_workflow = graph_owner.workflow_id == workflow_id
            if owns_workflow:
                graph_owner.workflow_id = None
            if owns_workflow or graph_owner.graph_json == workflow.graph_json:
                graph_owner.graph_json = None
            if graph_owner.graph_json is None and graph_owner.mode == "conversational_flow":
                graph_owner.mode = "single_prompt"
    await db.commit()
    
    return {"message": f"Workflow '{workflow.name}' deactivated"}


class ExecuteWorkflowRequest(BaseModel):
    """Context variables for workflow execution."""
    context: dict = Field(
        default_factory=dict,
        description="Template variables: caller_name, caller_phone, transcript, etc."
    )
    force: bool = Field(
        default=False,
        description="If true, bypass requires_approval and execute immediately."
    )


def _validate_execute_workflow_context(context: Any) -> dict:
    """Reject oversized or deeply nested workflow execution context payloads."""
    if not isinstance(context, dict):
        raise ValidationError(
            field="context",
            message="Context must be a JSON object.",
            suggestion="Send a flat object of template variables like caller_name and transcript.",
        )

    try:
        serialized = json.dumps(context, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        raise ValidationError(
            field="context",
            message="Context must contain JSON-serializable values.",
            suggestion="Use strings, numbers, booleans, null, or shallow lists of those values.",
        )

    if len(serialized.encode("utf-8")) > 100_000:
        raise ValidationError(
            field="context",
            message="Context payload is too large.",
            suggestion="Keep workflow execution context under 100 KB.",
        )

    def _is_shallow_json_value(value: Any) -> bool:
        if value is None or isinstance(value, (str, int, float, bool)):
            return True
        if isinstance(value, list):
            return all(item is None or isinstance(item, (str, int, float, bool)) for item in value)
        return False

    for key, value in context.items():
        if not isinstance(key, str) or not key.strip():
            raise ValidationError(
                field="context",
                message="Context keys must be non-empty strings.",
                suggestion="Use plain template variable names like caller_name.",
            )
        if not _is_shallow_json_value(value):
            raise ValidationError(
                field="context",
                message=f"Context value for '{key}' must be a primitive or shallow list.",
                suggestion="Avoid nested objects in workflow execution context.",
            )

    return context


@router.post("/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: int,
    request: ExecuteWorkflowRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Manually execute a workflow's integration steps.

    Runs each step sequentially, resolving {{template}} variables
    from the provided context. Returns results for each step.

    This endpoint is for manual testing. During calls, workflows
    are triggered automatically by the agent.
    """
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
    )
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise WorkflowNotFoundError(workflow_id)

    is_active: bool = workflow.is_active  # type: ignore[assignment]
    if not is_active:
        raise ValidationError(
            field="workflow",
            message="Workflow is deactivated and cannot be executed.",
            suggestion="Activate the workflow before running it.",
        )

    request_context = _validate_execute_workflow_context(request.context)

    # Parse steps + graph
    steps: list = []
    steps_json: str = workflow.steps_json or ""  # type: ignore[assignment]
    if steps_json:
        try:
            steps = json.loads(steps_json)
        except json.JSONDecodeError:
            raise ValidationError(
                field="steps_json",
                message="Workflow has invalid steps_json.",
                suggestion="Check the workflow steps definition for JSON syntax errors.",
            )

    graph: dict | None = None
    graph_json: str = workflow.graph_json or ""  # type: ignore[assignment]
    if graph_json:
        try:
            graph = json.loads(graph_json)
        except json.JSONDecodeError:
            raise ValidationError(
                field="graph_json",
                message="Workflow has invalid graph_json.",
                suggestion="Check the workflow graph definition for JSON syntax errors.",
            )

    if not steps and not graph:
        raise ValidationError(
            field="workflow",
            message="Workflow has no executable definition (steps/graph).",
            suggestion="Add steps or a graph to the workflow before executing.",
        )

    # Execute workflow (graph-first)
    from voice_platform.integrations.executor import WorkflowExecutor
    from voice_platform.integrations.plugins.registry import build_default_plugin_registry

    user_id: int = user.id  # type: ignore[assignment]
    executor = WorkflowExecutor(db, user_id, plugin_registry=build_default_plugin_registry(), agent_id=workflow.agent_id)
    transition_flexibility: str = workflow.transition_flexibility or "flex"  # type: ignore[assignment]

    if workflow.requires_approval and not request.force:
        review = ReviewQueue(
            workflow_id=workflow.id,
            user_id=user_id,
            action_type="workflow_execution",
            action_url=workflow.action_url,
            action_params=json.dumps({
                "workflow_id": workflow.id,
                "workflow_name": workflow.name,
                "steps": steps,
                "graph": graph,
                "context": request_context,
            }),
            trigger_context="Manual execution from dashboard",
            status="pending",
        )
        db.add(review)
        await db.commit()
        await db.refresh(review)
        return {
            "workflow": workflow.name,
            "mode": "pending_approval",
            "steps_executed": 0,
            "results": [],
            "review_id": review.id,
            "message": "Workflow requires approval. A review queue entry was created.",
        }

    execution = await executor.execute_workflow(
        steps=steps,
        graph=graph,
        context=request_context,
        transition_flexibility=transition_flexibility,
    )
    results = execution.get("results", [])

    return {
        "workflow": workflow.name,
        "mode": execution.get("mode", "steps"),
        "steps_executed": len(results),
        "results": results,
    }
