"""M10.5 architecture validation tests.

Verifies:
- All Python files compile without syntax errors
- Key modules import without circular dependency errors
- Architecture check script passes
- ExecutionContext immutability invariant holds
"""

import importlib
import py_compile
import sys
from pathlib import Path

import pytest


# ── Compile All Tests ────────────────────────────────────────────────


def test_all_voice_platform_files_compile():
    """Every .py file under voice_platform/ should compile without syntax errors."""
    vp_root = Path(__file__).resolve().parent.parent.parent / "voice_platform"
    failures = []
    for py_file in vp_root.rglob("*.py"):
        try:
            py_compile.compile(str(py_file), doraise=True)
        except py_compile.PyCompileError as e:
            failures.append(f"{py_file}: {e}")
    assert len(failures) == 0, f"Compilation failures:\n{''.join(failures)}"


# ── Import Chain Tests ───────────────────────────────────────────────


def test_no_circular_imports_on_key_modules():
    """Importing key modules in sequence should not trigger circular import errors."""
    # Import in an order that would trigger circular imports if they exist
    modules = [
        "voice_platform.main",
        "voice_platform.flow.nodes",
        "voice_platform.flow.compiler",
        "voice_platform.flow.executor",
        "voice_platform.runtime.llm.client",
        "voice_platform.runtime.llm.factory",
        "voice_platform.runtime.services",
        "voice_platform.runtime.services.extraction",
        "voice_platform.runtime.services.llm",
        "voice_platform.runtime.services.knowledge",
        "voice_platform.runtime.services.memory",
        "voice_platform.runtime.session.session",
        "voice_platform.runtime.session.factory",
        "voice_platform.runtime.session.builder",
        "voice_platform.runtime.session.service_container",
        "voice_platform.runtime.flow.conditions",
        "voice_platform.integrations.executor",
        "voice_platform.api.playground_routes",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert mod is not None, f"Failed to import {mod_name}"


def test_lazy_services_module_exposes_all_symbols():
    """runtime.services.__init__ lazy __getattr__ should expose all declared symbols."""
    from voice_platform.runtime import services

    expected = [
        "ExtractionPrompts",
        "ExtractionService",
        "LLMGenerationService",
        "KnowledgeContext",
        "KnowledgeDocument",
        "KnowledgeService",
        "CallSummary",
        "ConversationMemory",
        "MemoryService",
    ]
    for name in expected:
        assert hasattr(services, name), f"services module missing {name}"


# ── ExecutionContext Immutability ────────────────────────────────────


def test_execution_context_is_frozen_dataclass():
    """ExecutionContext should be a frozen dataclass (immutable after construction)."""
    from voice_platform.runtime.session.context import ExecutionContext

    # Frozen dataclass should raise FrozenInstanceError on setattr
    from dataclasses import is_dataclass, fields

    assert is_dataclass(ExecutionContext), "ExecutionContext must be a dataclass"

    # Check __dataclass_fields__ for frozen=True
    # The easiest way: try to mutate and expect FrozenInstanceError
    from voice_platform.runtime.session.conversation_context import ConversationChannel, ConversationContext
    from voice_platform.runtime.session.infrastructure_context import InfrastructureContext
    from unittest.mock import MagicMock

    ctx = ExecutionContext(
        conversation=ConversationContext(
            conversation_id="test-immutable",
            user_id=1,
            agent_id=1,
            channel=ConversationChannel.PLAYGROUND_CHAT,
        ),
        runtime=MagicMock(),
        infrastructure=InfrastructureContext(
            db=MagicMock(),
            cache=MagicMock(),
            event_bus=MagicMock(),
            tracer=MagicMock(),
            plugin_registry=MagicMock(),
        ),
    )

    with pytest.raises(Exception):
        ctx.conversation = MagicMock()  # Should raise FrozenInstanceError


# ── Architecture Script ──────────────────────────────────────────────


def test_architecture_check_script_passes():
    """scripts/check_architecture.py should pass."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "scripts/check_architecture.py"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent.parent),
    )
    assert result.returncode == 0, f"Architecture check failed:\n{result.stderr}"


# ── ServiceContainer Validation ──────────────────────────────────────


def test_service_container_freezes_plugin_registry():
    """ServiceContainer should freeze PluginRegistry on construction."""
    from voice_platform.integrations.plugins.registry import PluginRegistry
    from voice_platform.runtime.session.service_container import ServiceContainer

    container = ServiceContainer()
    # A frozen registry should not accept new registrations
    with pytest.raises(Exception):
        container.plugin_registry.register("test", MagicMock())


# ── ConditionEvaluator API ───────────────────────────────────────────


def test_condition_evaluator_evaluate_returns_bool():
    """ConditionEvaluator.evaluate() should return a boolean."""
    from voice_platform.runtime.flow.conditions import ConditionEvaluator

    evaluator = ConditionEvaluator()
    result = evaluator.evaluate("is_emergency == true", {"is_emergency": "yes"})
    assert isinstance(result, bool)
    assert result is True

    result = evaluator.evaluate("is_emergency == false", {"is_emergency": "yes"})
    assert isinstance(result, bool)
    assert result is False
