"""ConditionEvaluator — safe condition expression evaluation.

Extracted from WorkflowExecutor._evaluate_condition(). Supports simple
comparison operators (>, <, >=, <=, ==, !=), contains, not_empty, and
variable lookups from a context dict. No eval() or exec() — all parsing
is done with regex and string operations.

File named conditions.py (not evaluator.py) to avoid ambiguity with
future evaluators (ExpressionEvaluator, RouteEvaluator, TemplateEvaluator).
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger


class ConditionEvaluator:
    """Safely evaluate simple condition expressions against a context dict.

    Supported operators:
        >=, <=, !=, ==, >, <, contains, not_empty

    Variable lookups:
        Direct key: "caller_name"
        Dotted path: "result.is_emergency"
    """

    _OP_PATTERN = re.compile(r"(.+?)\s*(>=|<=|!=|==|>|<)\s*(.+)")

    def evaluate(self, expression: str, context: dict) -> bool:
        """Evaluate a condition expression and return True or False.

        Args:
            expression: The condition expression (e.g. "score >= 7", "name not_empty").
            context: Variable context for lookups.

        Returns:
            Boolean result of the condition evaluation.
        """
        expression = expression.strip()
        if not expression:
            return False

        def _resolve_operand(raw: str, *, fallback_to_literal: bool) -> Any:
            token = raw.strip()
            if not token:
                return None

            if (token.startswith('"') and token.endswith('"')) or (
                token.startswith("'") and token.endswith("'")
            ):
                return token[1:-1]

            lower = token.lower()
            if lower == "true":
                return True
            if lower == "false":
                return False
            if lower == "null":
                return None

            if re.fullmatch(r"-?\d+(\.\d+)?", token):
                return float(token) if "." in token else int(token)

            if token in context:
                return _normalize_value(context[token])

            if "." in token:
                current: Any = context
                for part in token.split("."):
                    if isinstance(current, dict) and part in current:
                        current = current[part]
                    else:
                        current = None
                        break
                if current is not None:
                    return _normalize_value(current)

            if fallback_to_literal:
                return token
            return None

        def _normalize_value(val: Any) -> Any:
            """Normalize string representations of booleans and numbers."""
            if val is None:
                return False
            if isinstance(val, str):
                lv = val.strip().lower()
                if not lv:
                    return False
                # Exact affirmative tokens plus spoken confirmations like "Yes, please".
                if lv in ("yes", "true", "1", "y", "yeah", "yep", "sure", "ok", "okay"):
                    return True
                if re.match(
                    r"^(yes|yeah|yep|yup|sure|ok|okay)([,\s!].*)?$",
                    lv,
                ) or lv in (
                    "go ahead",
                    "please do",
                    "book it",
                    "sounds good",
                    "please",
                ):
                    return True
                if lv in ("no", "false", "0", "n", "nope", "nah"):
                    return False
                if re.match(r"^(no|nope|nah)([,\s!].*)?$", lv):
                    return False
                try:
                    return int(lv)
                except ValueError:
                    pass
                try:
                    return float(lv)
                except ValueError:
                    pass
            return val

        try:
            # "not_empty" check — but only when used as a standalone operator
            if expression.endswith("not_empty"):
                var_name = expression[: -len("not_empty")].strip()
                if not re.search(r'>=|<=|==|!=|>|<', var_name):
                    value = _resolve_operand(var_name, fallback_to_literal=False)
                    result = bool(value.strip()) if isinstance(value, str) else bool(value)
                    logger.debug(f"Condition '{expression}' → {result} (value={value!r})")
                    return result

            # "contains" check
            if " contains " in expression:
                parts = expression.split(" contains ", 1)
                left = _resolve_operand(parts[0], fallback_to_literal=False)
                right = _resolve_operand(parts[1], fallback_to_literal=True)
                if left is None or right is None:
                    logger.debug(f"Condition '{expression}' → False (operand is None)")
                    return False
                if isinstance(left, (list, tuple, set)):
                    result = right in left
                else:
                    result = str(right).lower() in str(left).lower()
                logger.debug(f"Condition '{expression}' → {result}")
                return result

            # Comparison operators
            m = self._OP_PATTERN.match(expression)
            if m:
                left = _resolve_operand(m.group(1).strip(), fallback_to_literal=False)
                right = _resolve_operand(m.group(3).strip(), fallback_to_literal=True)
                op = m.group(2)

                # Treat "X == not_empty" / "X != not_empty" as the not_empty operator
                if isinstance(right, str) and right.strip().lower() == "not_empty":
                    is_nonempty = bool(left)
                    if isinstance(left, str):
                        is_nonempty = bool(left.strip())
                    if op == "!=":
                        result = not is_nonempty
                    else:
                        result = is_nonempty
                    logger.debug(f"Condition '{expression}' → {result} (left={left!r})")
                    return result

                if left is None:
                    logger.debug(f"Condition '{expression}' → False (left operand is None)")
                    return False

                if op == ">=":
                    result = left >= right
                elif op == "<=":
                    result = left <= right
                elif op == "!=":
                    if isinstance(left, str) and isinstance(right, str):
                        result = left.lower() != right.lower()
                    else:
                        result = left != right
                elif op == "==":
                    if isinstance(left, str) and isinstance(right, str):
                        result = left.lower() == right.lower()
                    else:
                        result = left == right
                elif op == ">":
                    result = left > right
                elif op == "<":
                    result = left < right
                else:
                    result = False
                logger.debug(f"Condition '{expression}' → {result} (left={left!r}, right={right!r})")
                return result

            result = bool(_resolve_operand(expression, fallback_to_literal=False))
            logger.debug(f"Condition '{expression}' → {result}")
            return result
        except Exception as e:
            logger.debug(f"Condition '{expression}' → False (exception: {e})")
            return False
