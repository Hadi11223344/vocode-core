"""Phase 6.11: is_emergency normalization and condition evaluation tests."""

import pytest

from voice_platform.flow.slots import normalize_variable
from voice_platform.runtime.flow.conditions import ConditionEvaluator


@pytest.mark.parametrize("raw,expected", [
    ("yes", "true"),
    ("YES", "true"),
    ("true", "true"),
    ("True", "true"),
    ("1", "true"),
    ("y", "true"),
    ("yeah", "true"),
    ("yep", "true"),
    ("sure", "true"),
    ("no", "false"),
    ("NO", "false"),
    ("false", "false"),
    ("False", "false"),
    ("0", "false"),
    ("n", "false"),
    ("nope", "false"),
    ("nah", "false"),
    ("maybe", "maybe"),
    ("", ""),
])
def test_is_emergency_normalize_variable(raw, expected):
    """is_emergency should be canonicalized to "true"/"false" immediately."""
    assert normalize_variable("is_emergency", raw) == expected


def test_normalize_variable_preserves_other_booleans():
    """Other boolean-ish variables continue to use yes/no where appropriate."""
    assert normalize_variable("has_companion", "yes") == "yes"
    assert normalize_variable("has_companion", "no") == "no"
    assert normalize_variable("is_new_patient", "new") == "new"
    assert normalize_variable("is_new_patient", "existing") == "existing"


@pytest.mark.parametrize("value,expected", [
    ("true", True),
    ("True", True),
    ("yes", True),
    ("y", True),
    ("yeah", True),
    ("1", True),
    ("false", False),
    ("False", False),
    ("no", False),
    ("n", False),
    ("nope", False),
    ("0", False),
    ("", False),
    (None, False),
])
def test_evaluate_condition_is_emergency(value, expected):
    """is_emergency condition should be true for all truthy forms and false for missing/empty values."""
    evaluator = ConditionEvaluator()
    result = evaluator.evaluate("is_emergency == true", {"is_emergency": value})
    assert result is expected


def test_evaluate_condition_missing_is_emergency_defaults_false():
    """A missing is_emergency variable should not break the condition; it should evaluate to false."""
    evaluator = ConditionEvaluator()
    assert evaluator.evaluate("is_emergency == true", {}) is False
