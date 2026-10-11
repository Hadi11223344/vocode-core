"""
Milestone 1 — PromptRenderer Extraction Tests

Tests T-1 through T-16 from the M1 Impact Analysis.
Verifies prompt rendering, guard presence, drift fixes, parity,
edge cases, and backward compatibility.
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Set required env vars before importing
os.environ.setdefault("TWILIO_ACCOUNT_SID", "ACtest")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test_token")
os.environ.setdefault("DEEPGRAM_API_KEY", "dg-test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")

from voice_platform.runtime.prompt_renderer import (
    _DRIVE_APPENDIX,
    _EMAIL_APPENDIX,
    _SECURITY_GUARD,
    _VOICE_CONDUCT,
    PromptExperiment,
    PromptRenderer,
    PromptTemplate,
    PromptVersion,
    RenderContext,
    RenderResult,
    _build_tool_availability_guard,
    _select_prompt_version,
)
from voice_platform.runtime.services.knowledge import KnowledgeContext, KnowledgeDocument
from voice_platform.runtime.session.runtime_config import WorkflowContext, WorkflowStep

# ═══════════════════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════════════════

def _make_agent(**kwargs):
    """Create a minimal fake agent for rendering."""
    defaults = dict(
        id=1,
        name="Test Agent",
        prompt_preamble="You are a helpful assistant.",
        prompt_versions=[],
        current_prompt_version_id=None,
        tools_config=None,
        tool_instructions=None,
        handbook_enabled=False,
        handbook_content=None,
        google_drive_integration_id=None,
        company_name=None,
        timezone=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_tool_action(tool_name="test_tool", integration_type=""):
    """Create a fake tool action."""
    return SimpleNamespace(tool_name=tool_name, integration_type=integration_type)


# ═══════════════════════════════════════════════════════════════════════
# T-1: Cache-hit path produces same prompt as fresh-build path
# ═══════════════════════════════════════════════════════════════════════

def test_t1_cache_hit_and_fresh_build_produce_same_prompt():
    """Both paths call PromptRenderer.render() with same context → same output."""
    agent = _make_agent(name="Alice", prompt_preamble="Hello [Name]")
    tool_actions = [_make_tool_action("read_drive_file", "google_drive")]
    drive_tool_actions = [_make_tool_action("read_drive_file")]
    skipped_tools = []

    ctx = RenderContext(
        db_agent=agent,
        tool_actions=tool_actions,
        skipped_tools=skipped_tools,
        drive_tool_actions=drive_tool_actions,
        tools_config='["read_drive_file"]',
    )

    result_a = PromptRenderer.render(ctx)
    result_b = PromptRenderer.render(ctx)

    assert result_a.prompt == result_b.prompt
    assert result_a.version_id == result_b.version_id


# ═══════════════════════════════════════════════════════════════════════
# T-2: Snapshot test — verify key prompt components for representative agents
# ═══════════════════════════════════════════════════════════════════════

def test_t2_snapshot_basic_agent():
    """Basic agent with no tools produces expected prompt structure."""
    agent = _make_agent(name="Basic Bot", prompt_preamble="You are a basic assistant.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
    )
    result = PromptRenderer.render(ctx)
    assert "You are a basic assistant." in result.prompt
    assert "[CAPABILITIES]" in result.prompt
    assert "[SECURITY]" in result.prompt
    assert "[VOICE CONDUCT]" in result.prompt


def test_t2_snapshot_agent_with_tools():
    """Agent with tools gets capabilities list."""
    agent = _make_agent(name="Tool Bot", prompt_preamble="You are a tool assistant.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[_make_tool_action("check_calendar"), _make_tool_action("send_email", "email")],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config='["check_calendar", "send_email"]',
    )
    result = PromptRenderer.render(ctx)
    assert "[CAPABILITIES]" in result.prompt
    assert "check_calendar" in result.prompt
    assert "send_email" in result.prompt


def test_t2_snapshot_agent_with_drive():
    """Agent with drive integration gets drive appendix."""
    agent = _make_agent(
        name="Drive Bot",
        prompt_preamble="You are a drive assistant.",
        google_drive_integration_id=42,
    )
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[_make_tool_action("read_drive_file")],
        tools_config=None,
    )
    result = PromptRenderer.render(ctx)
    assert "Google Drive Access" in result.prompt


def test_t2_snapshot_agent_with_email():
    """Agent with email tool gets email appendix."""
    agent = _make_agent(name="Email Bot", prompt_preamble="You are an email assistant.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[_make_tool_action("send_email", "email")],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config='["send_email"]',
    )
    result = PromptRenderer.render(ctx)
    assert "Email Capability" in result.prompt


def test_t2_snapshot_agent_with_placeholders():
    """Agent with placeholder in prompt gets substitution."""
    agent = _make_agent(name="Alice", prompt_preamble="Hello, my name is [Name] from [Company].")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
    )
    result = PromptRenderer.render(ctx)
    assert "Alice" in result.prompt
    assert "[Name]" not in result.prompt
    # [Company] is NOT replaced when company_name is None — original behavior
    # checks `if _replacement:` and skips empty values
    assert "[Company]" in result.prompt  # Unchanged because company_name is None


# ═══════════════════════════════════════════════════════════════════════
# T-3: All prompt guards present in output
# ═══════════════════════════════════════════════════════════════════════

def test_t3_all_guards_present():
    """Verify all four guard constants appear in rendered output."""
    agent = _make_agent(
        name="Guard Bot",
        prompt_preamble="Test prompt.",
        google_drive_integration_id=1,
    )
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[_make_tool_action("send_email", "email")],
        skipped_tools=[],
        drive_tool_actions=[_make_tool_action("read_drive_file")],
        tools_config='["send_email"]',
    )
    result = PromptRenderer.render(ctx)
    assert _SECURITY_GUARD in result.prompt
    assert _VOICE_CONDUCT in result.prompt
    assert _DRIVE_APPENDIX in result.prompt
    assert _EMAIL_APPENDIX in result.prompt


# ═══════════════════════════════════════════════════════════════════════
# T-4: Anti-fabrication guard present in playground path
# ═══════════════════════════════════════════════════════════════════════

def test_t4_anti_fab_guard_in_playground():
    """Playground path should now include anti-fabrication guard (drift fix)."""
    agent = _make_agent(name="Playground Bot", prompt_preamble="Test.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[("check_calendar", "google_calendar")],
        drive_tool_actions=[],
        tools_config=None,
        is_playground=True,
    )
    result = PromptRenderer.render(ctx)
    assert "[TOOL AVAILABILITY]" in result.prompt
    assert "check_calendar" in result.prompt
    assert "NOT available" in result.prompt


# ═══════════════════════════════════════════════════════════════════════
# T-5: [CAPABILITIES] section present in playground path
# ═══════════════════════════════════════════════════════════════════════

def test_t5_capabilities_in_playground():
    """Playground path should now include [CAPABILITIES] section (drift fix)."""
    agent = _make_agent(name="Playground Bot", prompt_preamble="Test.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[_make_tool_action("read_drive_file")],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
        is_playground=True,
    )
    result = PromptRenderer.render(ctx)
    assert "[CAPABILITIES]" in result.prompt
    assert "read_drive_file" in result.prompt


def test_t5_capabilities_no_tools_in_playground():
    """Playground with no tools should get 'no tools' capabilities message."""
    agent = _make_agent(name="Playground Bot", prompt_preamble="Test.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
        is_playground=True,
    )
    result = PromptRenderer.render(ctx)
    assert "[CAPABILITIES]" in result.prompt
    assert "no tools" in result.prompt


# ═══════════════════════════════════════════════════════════════════════
# T-6: Placeholder substitution works in playground path
# ═══════════════════════════════════════════════════════════════════════

def test_t6_placeholder_substitution_in_playground():
    """Playground path should now perform placeholder substitution (drift fix)."""
    agent = _make_agent(name="Alice", prompt_preamble="Hi, I'm [Name] from [Company].")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
        is_playground=True,
    )
    result = PromptRenderer.render(ctx)
    assert "Alice" in result.prompt
    assert "[Name]" not in result.prompt
    # [Company] is NOT replaced when company_name is None — original behavior
    assert "[Company]" in result.prompt  # Unchanged because company_name is None


# ═══════════════════════════════════════════════════════════════════════
# T-7: Email tool in tools_config but not in tool_actions
# ═══════════════════════════════════════════════════════════════════════

def test_t7_email_fallback_to_tools_config():
    """Email appendix should be appended when send_email is in tools_config but not tool_actions."""
    agent = _make_agent(name="Email Bot", prompt_preamble="Test.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],  # No tool_actions with integration_type == "email"
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config='["send_email"]',  # But tools_config has it
    )
    result = PromptRenderer.render(ctx)
    assert "Email Capability" in result.prompt


def test_t7_email_in_tool_actions():
    """Email appendix should be appended when tool_actions has integration_type == email."""
    agent = _make_agent(name="Email Bot", prompt_preamble="Test.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[_make_tool_action("send_email", "email")],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
    )
    result = PromptRenderer.render(ctx)
    assert "Email Capability" in result.prompt


def test_t7_email_not_present():
    """Email appendix should NOT be appended when no email tool anywhere."""
    agent = _make_agent(name="No Email Bot", prompt_preamble="Test.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[_make_tool_action("check_calendar")],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config='["check_calendar"]',
    )
    result = PromptRenderer.render(ctx)
    assert "Email Capability" not in result.prompt


# ═══════════════════════════════════════════════════════════════════════
# T-8: Language suffix still applied after PromptRenderer.render()
# ═══════════════════════════════════════════════════════════════════════

def test_t8_language_suffix_applied_post_render():
    """Verify _apply_language_overrides still works on rendered prompt."""
    from voice_platform.agents.agent_factory import _apply_language_overrides
    from voice_platform.constants import LANGUAGE_CONFIGS

    agent = _make_agent(name="Urdu Bot", prompt_preamble="You are a helpful assistant.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
    )
    result = PromptRenderer.render(ctx)

    # Simulate post-render language override
    agent_config = SimpleNamespace(prompt_preamble=result.prompt)
    transcriber_config = SimpleNamespace(language="en-US")

    class FakeSynth:
        voice_name = "default"

    _apply_language_overrides(
        SimpleNamespace(language="ur-PK"),
        agent_config,
        transcriber_config,
        FakeSynth(),
    )

    expected_suffix = LANGUAGE_CONFIGS["ur-PK"]["prompt_suffix"]
    assert expected_suffix in agent_config.prompt_preamble
    assert transcriber_config.language == "ur"


# ═══════════════════════════════════════════════════════════════════════
# T-9: Data models structure
# ═══════════════════════════════════════════════════════════════════════

def test_t9_prompt_template():
    """PromptTemplate has required fields including agent_id."""
    template = PromptTemplate(
        template_id="tpl-1",
        agent_id=42,
        sections={"main": "You are a helpful assistant."},
        variables=["name"],
        guards=["security"],
        metadata={"author": "admin"},
    )
    assert template.template_id == "tpl-1"
    assert template.agent_id == 42
    assert "main" in template.sections
    assert "name" in template.variables
    assert "security" in template.guards


def test_t9_prompt_version():
    """PromptVersion has required fields."""
    template = PromptTemplate(template_id="tpl-1", agent_id=1)
    version = PromptVersion(
        version_id="v-1",
        template=template,
        version_number=1,
        is_active=True,
        changelog="Initial version",
    )
    assert version.version_id == "v-1"
    assert version.is_active is True
    assert version.template.agent_id == 1


def test_t9_prompt_experiment():
    """PromptExperiment has required fields."""
    template_a = PromptTemplate(template_id="tpl-a", agent_id=1)
    template_b = PromptTemplate(template_id="tpl-b", agent_id=1)
    version_a = PromptVersion(version_id="va", template=template_a, version_number=1)
    version_b = PromptVersion(version_id="vb", template=template_b, version_number=2)
    experiment = PromptExperiment(
        experiment_id="exp-1",
        version_a=version_a,
        version_b=version_b,
        traffic_percentage=30.0,
        selection_key="agent_id",
        status="running",
    )
    assert experiment.experiment_id == "exp-1"
    assert experiment.traffic_percentage == 30.0
    assert experiment.status == "running"


# ═══════════════════════════════════════════════════════════════════════
# T-10: PromptRenderer.render() returns RenderResult with version_id
# ═══════════════════════════════════════════════════════════════════════

def test_t10_render_returns_render_result_with_version_id():
    """render() returns a RenderResult with prompt and version_id."""
    agent = _make_agent(
        prompt_preamble="Test prompt.",
        current_prompt_version_id=7,
        prompt_versions=[],
    )
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
    )
    result = PromptRenderer.render(ctx)
    assert isinstance(result, RenderResult)
    assert result.prompt is not None
    assert result.version_id == 7


# ═══════════════════════════════════════════════════════════════════════
# T-11: Empty handbook edge case
# ═══════════════════════════════════════════════════════════════════════

def test_t11_empty_handbook_no_crash():
    """Agent with handbook_enabled=True but handbook_content=None should not crash."""
    agent = _make_agent(
        name="Handbook Bot",
        prompt_preamble="Test.",
        handbook_enabled=True,
        handbook_content=None,
    )
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
    )
    result = PromptRenderer.render(ctx)
    assert "[AGENT HANDBOOK]" not in result.prompt


# ═══════════════════════════════════════════════════════════════════════
# T-12: Empty tools edge case
# ═══════════════════════════════════════════════════════════════════════

def test_t12_empty_tools_produces_no_tools_capabilities():
    """Agent with no tools should get 'no tools' capabilities message."""
    agent = _make_agent(name="No Tools Bot", prompt_preamble="Test.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
    )
    result = PromptRenderer.render(ctx)
    assert "[CAPABILITIES]" in result.prompt
    assert "no tools" in result.prompt


# ═══════════════════════════════════════════════════════════════════════
# T-13: Drive integration with no loaded tools
# ═══════════════════════════════════════════════════════════════════════

def test_t13_drive_integration_no_tools_no_appendix():
    """Drive appendix should NOT be appended when drive_integration_id exists but no drive tools loaded."""
    agent = _make_agent(
        name="Drive Bot",
        prompt_preamble="Test.",
        google_drive_integration_id=42,
    )
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],  # No drive tools loaded
        tools_config=None,
    )
    result = PromptRenderer.render(ctx)
    assert "Google Drive Access" not in result.prompt


def test_t13_drive_integration_with_tools_appends():
    """Drive appendix should be appended when drive_integration_id exists AND drive tools are loaded."""
    agent = _make_agent(
        name="Drive Bot",
        prompt_preamble="Test.",
        google_drive_integration_id=42,
    )
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[_make_tool_action("read_drive_file")],
        tools_config=None,
    )
    result = PromptRenderer.render(ctx)
    assert "Google Drive Access" in result.prompt


# ═══════════════════════════════════════════════════════════════════════
# T-14: _select_prompt_version backward compat re-export
# ═══════════════════════════════════════════════════════════════════════

def test_t14_select_prompt_version_importable_from_agent_factory():
    """_select_prompt_version should still be importable from agent_factory.py."""
    from voice_platform.agents.agent_factory import _select_prompt_version as af_select

    agent = _make_agent(
        prompt_preamble="Default prompt.",
        current_prompt_version_id=10,
        prompt_versions=[],
    )
    selected, version_id = af_select(agent)
    assert selected == "Default prompt."
    assert version_id == 10


# ═══════════════════════════════════════════════════════════════════════
# T-15: Large handbook truncation
# ═══════════════════════════════════════════════════════════════════════

def test_t15_handbook_truncation():
    """Handbook content exceeding 5000 chars should be truncated with marker."""
    long_content = "A" * 6000
    agent = _make_agent(
        name="Big Handbook Bot",
        prompt_preamble="Test.",
        handbook_enabled=True,
        handbook_content=long_content,
    )
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
    )
    result = PromptRenderer.render(ctx)
    assert "[AGENT HANDBOOK]" in result.prompt
    assert "... [truncated]" in result.prompt
    # The truncated content should be 5000 chars + "... [truncated]"
    assert "A" * 5000 in result.prompt


# ═══════════════════════════════════════════════════════════════════════
# T-16: Tool instructions truncation
# ═══════════════════════════════════════════════════════════════════════

def test_t16_tool_instructions_truncation():
    """Tool instructions exceeding 2000 chars should be truncated with marker."""
    long_instructions = "X" * 3000
    agent = _make_agent(
        name="Big Instructions Bot",
        prompt_preamble="Test.",
        tool_instructions=long_instructions,
    )
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
    )
    result = PromptRenderer.render(ctx)
    assert "[TOOL INSTRUCTIONS]" in result.prompt
    assert "... [truncated]" in result.prompt
    assert "X" * 2000 in result.prompt


# ═══════════════════════════════════════════════════════════════════════
# Additional: Playground-specific sections
# ═══════════════════════════════════════════════════════════════════════

def test_playground_context_prefix():
    """Playground path should include [CONTEXT: playground] prefix."""
    agent = _make_agent(name="Playground Bot", prompt_preamble="Test.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
        is_playground=True,
    )
    result = PromptRenderer.render(ctx)
    assert "[CONTEXT: This is a test conversation from the web playground." in result.prompt


def test_playground_gemini_warning():
    """Playground path with gemini_warning should include Gemini note."""
    agent = _make_agent(name="Gemini Bot", prompt_preamble="Test.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config='["check_calendar"]',
        is_playground=True,
        gemini_warning=True,
    )
    result = PromptRenderer.render(ctx)
    assert "Gemini" in result.prompt
    assert "limited support" in result.prompt


def test_playground_kb_injection():
    """Playground path with KnowledgeContext should include KB section."""
    agent = _make_agent(name="KB Bot", prompt_preamble="Test.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
        is_playground=True,
        knowledge=KnowledgeContext(documents=(
            KnowledgeDocument(title="KB", content="Important knowledge base content here."),
        )),
    )
    result = PromptRenderer.render(ctx)
    assert "Important knowledge base content here." in result.prompt
    assert "Related Knowledge Contexts" in result.prompt


def test_playground_workflow_context():
    """Playground path with WorkflowContext should include it."""
    agent = _make_agent(name="Workflow Bot", prompt_preamble="Test.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
        is_playground=True,
        workflow=WorkflowContext(steps=(
            WorkflowStep(name="Do something", description="specific task"),
        )),
    )
    result = PromptRenderer.render(ctx)
    assert "WORKFLOW INSTRUCTIONS" in result.prompt
    assert "Do something" in result.prompt


def test_non_playground_no_context_prefix():
    """Non-playground path should NOT include [CONTEXT: playground] prefix."""
    agent = _make_agent(name="Live Bot", prompt_preamble="Test.")
    ctx = RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        tools_config=None,
        is_playground=False,
    )
    result = PromptRenderer.render(ctx)
    assert "[CONTEXT: This is a test conversation" not in result.prompt
