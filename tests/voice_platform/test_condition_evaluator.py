"""Tests for the ConditionEvaluator extracted from WorkflowExecutor."""

import pytest

from voice_platform.runtime.flow.conditions import ConditionEvaluator


class TestConditionEvaluator:
    def setup_method(self):
        self.eval = ConditionEvaluator()

    def test_empty_expression_is_false(self):
        assert self.eval.evaluate("", {}) is False

    def test_unknown_variable_is_false(self):
        assert self.eval.evaluate("missing_var", {}) is False

    def test_not_empty_with_value(self):
        assert self.eval.evaluate("caller_phone not_empty", {"caller_phone": "+15551234567"}) is True

    def test_not_empty_with_empty_string(self):
        assert self.eval.evaluate("caller_phone not_empty", {"caller_phone": ""}) is False

    def test_not_empty_with_none(self):
        assert self.eval.evaluate("caller_phone not_empty", {"caller_phone": None}) is False

    def test_not_empty_missing_variable(self):
        assert self.eval.evaluate("missing_var not_empty", {}) is False

    def test_equals_string_comparison(self):
        assert self.eval.evaluate("account_action == cancel", {"account_action": "cancel"}) is True

    def test_equals_case_insensitive(self):
        assert self.eval.evaluate("status == Active", {"status": "active"}) is True

    def test_not_equals_string(self):
        assert self.eval.evaluate("status != done", {"status": "pending"}) is True

    def test_not_equals_case_insensitive(self):
        assert self.eval.evaluate("status != Done", {"status": "done"}) is False

    def test_contains_string(self):
        assert self.eval.evaluate("message contains urgent", {"message": "This is urgent please call back"}) is True

    def test_contains_list(self):
        assert self.eval.evaluate("tags contains vip", {"tags": ["new", "vip"]}) is True

    def test_contains_not_found(self):
        assert self.eval.evaluate("tags contains premium", {"tags": ["new", "vip"]}) is False

    def test_numeric_greater_than(self):
        assert self.eval.evaluate("score > 5", {"score": 10}) is True

    def test_numeric_less_than(self):
        assert self.eval.evaluate("score < 5", {"score": 3}) is True

    def test_numeric_greater_equal(self):
        assert self.eval.evaluate("nps_score >= 7", {"nps_score": 7}) is True

    def test_numeric_less_equal(self):
        assert self.eval.evaluate("nps_score <= 7", {"nps_score": 7}) is True

    def test_string_numeric_comparison(self):
        assert self.eval.evaluate("nps_score >= 7", {"nps_score": "8"}) is True

    def test_yes_string_compared_to_true(self):
        assert self.eval.evaluate("is_emergency == true", {"is_emergency": "yes"}) is True
        assert self.eval.evaluate("is_emergency == true", {"is_emergency": "true"}) is True
        assert self.eval.evaluate("is_emergency == false", {"is_emergency": "no"}) is True
        assert self.eval.evaluate("confirm_booking == true", {"confirm_booking": "yeah"}) is True
        assert self.eval.evaluate("confirm_booking == true", {"confirm_booking": "Yes, please"}) is True
        assert self.eval.evaluate("confirm_booking == true", {"confirm_booking": "yes please"}) is True
        assert self.eval.evaluate("confirm_booking == true", {"confirm_booking": "go ahead"}) is True

    def test_no_string_compared_to_false(self):
        assert self.eval.evaluate("is_emergency == false", {"is_emergency": "nope"}) is True

    def test_equals_not_empty_for_list(self):
        assert (
            self.eval.evaluate(
                "result.available_slots == not_empty",
                {"result": {"available_slots": [{"start": "10:00"}]}},
            )
            is True
        )

    def test_equals_not_empty_empty_list_is_false(self):
        assert (
            self.eval.evaluate(
                "result.available_slots == not_empty",
                {"result": {"available_slots": []}},
            )
            is False
        )

    def test_equals_not_empty_missing_variable_is_false(self):
        assert self.eval.evaluate("is_emergency == not_empty", {}) is False

    def test_not_equals_not_empty_missing_variable_is_true(self):
        assert self.eval.evaluate("is_emergency != not_empty", {}) is True

    def test_dot_notation_lookup(self):
        assert (
            self.eval.evaluate(
                "result.success == true",
                {"result": {"success": "yes", "data": "ok"}},
            )
            is True
        )

    def test_quoted_string_operand(self):
        assert self.eval.evaluate('status == "active"', {"status": "active"}) is True

    def test_boolean_true_literal(self):
        assert self.eval.evaluate("confirmed == true", {"confirmed": True}) is True

    def test_boolean_false_literal(self):
        assert self.eval.evaluate("confirmed == false", {"confirmed": False}) is True

    def test_exception_returns_false(self):
        assert self.eval.evaluate("!!!invalid!!!", {}) is False
