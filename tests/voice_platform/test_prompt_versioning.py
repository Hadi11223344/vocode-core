"""
GAP-08: Prompt Versioning & A/B Testing Tests
"""

from unittest.mock import MagicMock

import pytest

from voice_platform.agents.agent_factory import _select_prompt_version


def test_select_prompt_version_single_active():
    """When only one version is active, it should be selected."""
    db_agent = MagicMock()
    db_agent.prompt_preamble = "Current agent prompt"
    db_agent.current_prompt_version_id = 5
    db_agent.prompt_versions = []

    active_version = MagicMock()
    active_version.is_active = True
    active_version.traffic_percentage = 100
    active_version.prompt_preamble = "Prompt v2"
    active_version.id = 2
    db_agent.prompt_versions = [active_version]

    selected, version_id = _select_prompt_version(db_agent)
    assert selected == "Prompt v2"
    assert version_id == 2


def test_select_prompt_version_ab_test_split():
    """A/B test should split traffic weighted by percentages."""
    db_agent = MagicMock()
    db_agent.prompt_preamble = "Current agent prompt"
    db_agent.current_prompt_version_id = None

    v_a = MagicMock()
    v_a.is_active = True
    v_a.traffic_percentage = 70
    v_a.prompt_preamble = "Prompt A"
    v_a.id = 1

    v_b = MagicMock()
    v_b.is_active = True
    v_b.traffic_percentage = 30
    v_b.prompt_preamble = "Prompt B"
    v_b.id = 2

    db_agent.prompt_versions = [v_a, v_b]

    # Run 100 selections and check distribution
    counts = {"Prompt A": 0, "Prompt B": 0}
    for _ in range(200):
        selected, _ = _select_prompt_version(db_agent)
        counts[selected] += 1

    assert counts["Prompt A"] > 0
    assert counts["Prompt B"] > 0
    assert counts["Prompt A"] > counts["Prompt B"]


def test_select_prompt_version_no_active_uses_current():
    """When no active versions, use agent's current prompt."""
    db_agent = MagicMock()
    db_agent.prompt_preamble = "Current default prompt"
    db_agent.current_prompt_version_id = 10
    db_agent.prompt_versions = []

    selected, version_id = _select_prompt_version(db_agent)
    assert selected == "Current default prompt"
    assert version_id == 10


def test_select_prompt_version_all_inactive():
    """When versions exist but none are active, use current prompt."""
    db_agent = MagicMock()
    db_agent.prompt_preamble = "Current default"
    db_agent.current_prompt_version_id = 7

    v1 = MagicMock()
    v1.is_active = False
    v1.traffic_percentage = 0
    v1.prompt_preamble = "Old prompt"
    v1.id = 1

    db_agent.prompt_versions = [v1]

    selected, version_id = _select_prompt_version(db_agent)
    assert selected == "Current default"
    assert version_id == 7


def test_select_prompt_version_zero_traffic():
    """Active versions with 0% traffic should be skipped."""
    db_agent = MagicMock()
    db_agent.prompt_preamble = "Current default"
    db_agent.current_prompt_version_id = 7

    v1 = MagicMock()
    v1.is_active = True
    v1.traffic_percentage = 0
    v1.prompt_preamble = "Zero traffic"
    v1.id = 1

    db_agent.prompt_versions = [v1]

    selected, version_id = _select_prompt_version(db_agent)
    assert selected == "Current default"
    assert version_id == 7
