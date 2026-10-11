"""Unit tests for ExtractionService."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from voice_platform.runtime.services.extraction import ExtractionPrompts, ExtractionService


def _make_service(generate_return=None, generate_side_effect=None):
    """Build an ExtractionService with a mock LLMGenerationService."""
    gen = MagicMock()
    if generate_side_effect is not None:
        gen.generate = AsyncMock(side_effect=generate_side_effect)
    else:
        gen.generate = AsyncMock(return_value=generate_return)
    return ExtractionService(gen)


# ── JSON Parsing Tests (moved from test_workflow_executor.py) ──────────────


class TestExtractionParsing:
    """Batch extraction should tolerate empty, fenced, and partial JSON responses."""

    def test_parse_json_empty(self):
        assert ExtractionService._parse_json("") is None
        assert ExtractionService._parse_json("   \n  ") is None

    def test_parse_json_markdown_fences(self):
        raw = "```json\n{\"patient_name\": \"Alice\"}\n```"
        parsed = ExtractionService._parse_json(raw)
        assert parsed == {"patient_name": "Alice"}

    def test_parse_json_repair_partial(self):
        raw = 'Here is the JSON: {"preferred_time": "10:00", "patient_name": "Alice"} hope this helps'
        parsed = ExtractionService._parse_json(raw)
        assert parsed == {"preferred_time": "10:00", "patient_name": "Alice"}

    def test_parse_json_invalid_returns_none(self):
        assert ExtractionService._parse_json("not json") is None


# ── Normalization Tests (moved from test_workflow_executor.py) ─────────────


class TestNormalizeExtractedValues:
    """Test phone/email/name normalization in _normalize_values."""

    def _make_service(self):
        return _make_service(generate_return=None)

    def test_normalize_phone_strips_non_digits(self):
        svc = self._make_service()
        result = svc._normalize_values({"caller_phone": "(555) 123-4567"})
        assert result["caller_phone"] == "5551234567"

    def test_normalize_phone_keeps_plus_prefix(self):
        svc = self._make_service()
        result = svc._normalize_values({"caller_phone": "+1 555 123 4567"})
        assert result["caller_phone"] == "+15551234567"

    def test_normalize_email_lowercases(self):
        svc = self._make_service()
        result = svc._normalize_values({"caller_email": "  John.Doe@Example.COM  "})
        assert result["caller_email"] == "john.doe@example.com"

    def test_normalize_name_strips_whitespace(self):
        svc = self._make_service()
        result = svc._normalize_values({"patient_name": "  John   Doe  "})
        assert result["patient_name"] == "John Doe"

    def test_normalize_non_matching_key_passthrough(self):
        svc = self._make_service()
        result = svc._normalize_values({"visit_type": "booking"})
        assert result["visit_type"] == "booking"


# ── Default Prompts Tests (moved from test_workflow_executor.py) ───────────


class TestExtractionPromptsGeneric:
    """Default extraction prompts should be industry-neutral."""

    def test_no_dental_in_default_prompts(self):
        prompts = ExtractionService._DEFAULT_EXTRACTION_PROMPTS
        for key, desc in prompts.items():
            assert "dental" not in desc.lower(), f"Prompt for '{key}' contains 'dental': {desc}"

    def test_no_patient_specific_in_default_prompts(self):
        prompts = ExtractionService._DEFAULT_EXTRACTION_PROMPTS
        for key, desc in prompts.items():
            if "patient" in key:
                continue
            assert "patient" not in desc.lower(), f"Prompt for '{key}' contains 'patient': {desc}"

    def test_caller_name_in_defaults(self):
        prompts = ExtractionService._DEFAULT_EXTRACTION_PROMPTS
        assert "caller_name" in prompts


# ── Per-Slot Extraction Tests (moved from test_workflow_executor.py) ───────


class TestPerSlotExtraction:
    """Per-slot extraction should only fill missing variables."""

    @pytest.mark.asyncio
    async def test_per_slot_extraction_only_fills_missing(self):
        svc = _make_service(generate_side_effect=["Alice", None])
        result = await svc._per_slot_extraction(
            ["patient_name", "preferred_date", "missing_var"],
            "transcript",
            {"preferred_date": "2024-07-18"},
        )
        assert result["patient_name"] == "Alice"
        assert result["preferred_date"] == "2024-07-18"
        assert "missing_var" not in result


# ── ExtractionPrompts value object ────────────────────────────────────────


class TestExtractionPromptsValueObject:
    def test_immutable(self):
        import pytest as _pytest

        ep = ExtractionPrompts()
        with _pytest.raises(Exception):
            ep.prompts = {}  # type: ignore[misc]

    def test_default_empty(self):
        ep = ExtractionPrompts()
        assert len(ep.prompts) == 0


# ── extract_variable tests ────────────────────────────────────────────────


class TestExtractVariable:
    @pytest.mark.asyncio
    async def test_returns_value_on_success(self):
        svc = _make_service(generate_return="Alice")
        svc.configure(agent_id=1, user_id=1)
        result = await svc.extract_variable("transcript", "the caller's name", "patient_name")
        assert result == "Alice"

    @pytest.mark.asyncio
    async def test_returns_none_on_not_found(self):
        svc = _make_service(generate_return="NOT_FOUND")
        svc.configure(agent_id=1, user_id=1)
        result = await svc.extract_variable("transcript", "the caller's name", "patient_name")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_generation_failure(self):
        svc = _make_service(generate_return=None)
        svc.configure(agent_id=1, user_id=1)
        result = await svc.extract_variable("transcript", "the caller's name", "patient_name")
        assert result is None

    @pytest.mark.asyncio
    async def test_regex_fallback_for_email(self):
        svc = _make_service(generate_return=None)
        svc.configure(agent_id=1, user_id=1)
        result = await svc.extract_variable(
            "Please contact john@example.com for details",
            "the caller's email address",
            "caller_email",
        )
        assert result == "john@example.com"


# ── extract_batch tests ───────────────────────────────────────────────────


class TestExtractBatch:
    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_variables(self):
        svc = _make_service()
        result = await svc.extract_batch(
            agent_id=1, user_id=1, transcript="text", variable_names=[]
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_parses_json_response(self):
        svc = _make_service(generate_return='{"patient_name": "Alice", "preferred_time": "10:00"}')
        result = await svc.extract_batch(
            agent_id=1, user_id=1, transcript="text",
            variable_names=["patient_name", "preferred_time"],
        )
        assert result["patient_name"] == "Alice"
        assert result["preferred_time"] == "10:00"

    @pytest.mark.asyncio
    async def test_falls_back_to_per_slot_on_empty_response(self):
        svc = _make_service(generate_side_effect=[None, "Alice"])
        result = await svc.extract_batch(
            agent_id=1, user_id=1, transcript="text",
            variable_names=["patient_name"],
        )
        assert result["patient_name"] == "Alice"

    @pytest.mark.asyncio
    async def test_falls_back_to_per_slot_on_invalid_json(self):
        svc = _make_service(generate_side_effect=["not json at all", "Alice"])
        result = await svc.extract_batch(
            agent_id=1, user_id=1, transcript="text",
            variable_names=["patient_name"],
        )
        assert result["patient_name"] == "Alice"

    @pytest.mark.asyncio
    async def test_strips_null_values(self):
        svc = _make_service(generate_return='{"patient_name": "Alice", "missing": null}')
        result = await svc.extract_batch(
            agent_id=1, user_id=1, transcript="text",
            variable_names=["patient_name", "missing"],
        )
        assert "patient_name" in result
        assert "missing" not in result

    @pytest.mark.asyncio
    async def test_extracts_email_locally_instead_of_accepting_redaction_placeholder(self):
        svc = _make_service(
            generate_return='{"patient_name": "Alex Patient", "caller_email": "[EMAIL]"}'
        )
        result = await svc.extract_batch(
            agent_id=1,
            user_id=1,
            transcript=(
                "Agent: Can I get your full name and email? "
                "Caller: My name is Alex Patient and patient1@example.com is my email."
            ),
            variable_names=["patient_name", "caller_email"],
        )

        assert result["patient_name"] == "Alex Patient"
        assert result["caller_email"] == "patient1@example.com"

    @pytest.mark.asyncio
    async def test_redaction_placeholder_is_never_returned_as_a_workflow_value(self):
        svc = _make_service(generate_return='{"caller_email": "[email]"}')
        result = await svc.extract_batch(
            agent_id=1,
            user_id=1,
            transcript="Agent: Is that correct? Caller: yes",
            variable_names=["caller_email"],
        )

        assert "caller_email" not in result
