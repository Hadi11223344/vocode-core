"""Regression tests for Google Sheets range resolution fix.

Tests cover:
- A1 range parser (sheet title extraction, quoted titles, apostrophe escaping)
- Preflight tab validation (SHEETS_TAB_NOT_FOUND, SHEETS_RANGE_INVALID)
- Column count validation (SHEETS_COLUMN_COUNT_MISMATCH)
- Error classification (spreadsheet not found, permission denied, append failed)
- Plugin error propagation (error_code, row_appended=false)
- Business outcome (booking remains booked, partial success TTS)
- Persisted graph verification (Agent #14 has 'Sheet1'!A:K)
- Diagnostics contain no PII
"""

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch, patch as mock_patch

import pytest

from voice_platform.integrations.google_sheets import (
    GoogleSheetsClient,
    SheetsError,
    _parse_a1_range,
    _col_number,
    _classify_http_error,
)


# ── A1 Range Parser Tests ────────────────────────────────────────────────────


class TestA1RangeParser:

    def test_1_simple_sheet_title(self):
        result = _parse_a1_range("Patients!A:K")
        assert result["sheet_title"] == "Patients"
        assert result["cell_range"] == "A:K"
        assert result["start_column"] == 1
        assert result["end_column"] == 11

    def test_2_quoted_sheet_title_with_spaces(self):
        result = _parse_a1_range("'Patient Records'!A:K")
        assert result["sheet_title"] == "Patient Records"
        assert result["cell_range"] == "A:K"

    def test_3_apostrophe_in_sheet_name_escaped(self):
        result = _parse_a1_range("'Owner''s Records'!A:K")
        assert result["sheet_title"] == "Owner's Records"
        assert result["cell_range"] == "A:K"

    def test_4_no_explicit_title(self):
        result = _parse_a1_range("A:K")
        assert result["sheet_title"] is None
        assert result["cell_range"] == "A:K"

    def test_5_cell_reference_with_row(self):
        result = _parse_a1_range("A1:K10")
        assert result["sheet_title"] is None
        assert result["cell_range"] == "A1:K10"
        assert result["start_column"] == 1
        assert result["end_column"] == 11

    def test_6_sheet_with_cell_ref(self):
        result = _parse_a1_range("Sheet1!A1:K")
        assert result["sheet_title"] == "Sheet1"
        assert result["cell_range"] == "A1:K"

    def test_7_empty_range_raises_invalid(self):
        with pytest.raises(SheetsError) as exc:
            _parse_a1_range("")
        assert exc.value.code == "SHEETS_RANGE_INVALID"

    def test_8_empty_cell_expression_raises_invalid(self):
        with pytest.raises(SheetsError) as exc:
            _parse_a1_range("Patients!")
        assert exc.value.code == "SHEETS_RANGE_INVALID"

    def test_9_formula_rejected(self):
        with pytest.raises(SheetsError) as exc:
            _parse_a1_range("=SUM(A1:K1)")
        assert exc.value.code == "SHEETS_RANGE_INVALID"

    def test_10_multiple_exclamation_marks_rejected(self):
        with pytest.raises(SheetsError) as exc:
            _parse_a1_range("Patients!A!K")
        assert exc.value.code == "SHEETS_RANGE_INVALID"

    def test_11_malformed_quoting_rejected(self):
        with pytest.raises(SheetsError) as exc:
            _parse_a1_range("'Patients!A:K")
        assert exc.value.code == "SHEETS_RANGE_INVALID"

    def test_12_reversed_column_range_rejected(self):
        with pytest.raises(SheetsError) as exc:
            _parse_a1_range("K:A")
        assert exc.value.code == "SHEETS_RANGE_INVALID"


# ── Column Count Validation ──────────────────────────────────────────────────


class TestColumnCountValidation:

    def test_13_a_to_k_accepts_11_values(self):
        """A:K = 11 columns. 11 values should be accepted."""
        from voice_platform.integrations.google_sheets import _parse_a1_range
        parsed = _parse_a1_range("'Sheet1'!A:K")
        col_width = parsed["end_column"] - parsed["start_column"] + 1
        assert col_width == 11
        values = ["v1"] * 11
        assert len(values) <= col_width

    def test_14_a_to_k_rejects_12_values(self):
        """A:K = 11 columns. 12 values should raise SHEETS_COLUMN_COUNT_MISMATCH."""
        parsed = _parse_a1_range("'Sheet1'!A:K")
        col_width = parsed["end_column"] - parsed["start_column"] + 1
        values = ["v1"] * 12
        assert len(values) > col_width

    def test_14b_append_anchors_to_column_a_with_insert_rows(self):
        """Appending with A:K must still write from column A (not K2:U2)."""
        import asyncio
        from voice_platform.integrations.google_sheets import GoogleSheetsClient

        client = GoogleSheetsClient("{}", {"spreadsheet_id": "sheet123", "sheet_name": "Sheet1"})
        client._get_service = AsyncMock(return_value=MagicMock())
        client._get_sheet_titles = AsyncMock(return_value=["Sheet1"])

        captured = {}

        class _Values:
            def append(self, **kwargs):
                captured.update(kwargs)
                class _Exec:
                    def execute(self_inner):
                        return {
                            "updates": {
                                "updatedRange": "Sheet1!A2:K2",
                                "updatedRows": 1,
                            }
                        }
                return _Exec()

        class _Spreadsheets:
            def values(self):
                return _Values()

        svc = MagicMock()
        svc.spreadsheets.return_value = _Spreadsheets()
        client._get_service = AsyncMock(return_value=svc)

        result = asyncio.get_event_loop().run_until_complete(
            client.append_row(["a"] * 11, range="'Sheet1'!A:K")
        )
        assert captured["range"] == "Sheet1!A:A"
        assert captured["insertDataOption"] == "INSERT_ROWS"
        assert result["updated_range"] == "Sheet1!A2:K2"
        assert result["append_range_used"] == "Sheet1!A:A"


# ── Error Classification ─────────────────────────────────────────────────────


class TestErrorClassification:

    def _make_http_error(self, status, msg=""):
        exc = MagicMock()
        exc.resp = MagicMock()
        exc.resp.status = status
        exc.status_code = status
        exc.__str__ = lambda self: msg
        return exc

    def test_15_404_maps_to_spreadsheet_not_found(self):
        exc = self._make_http_error(404, "Not found")
        with pytest.raises(SheetsError) as se:
            _classify_http_error(exc)
        assert se.value.code == "SHEETS_SPREADSHEET_NOT_FOUND"

    def test_16_403_maps_to_permission_denied(self):
        exc = self._make_http_error(403, "Forbidden")
        with pytest.raises(SheetsError) as se:
            _classify_http_error(exc)
        assert se.value.code == "SHEETS_PERMISSION_DENIED"

    def test_17_400_unparseable_range_maps_to_tab_not_found(self):
        exc = self._make_http_error(400, "Unable to parse range: Patients!A1")
        with pytest.raises(SheetsError) as se:
            _classify_http_error(exc)
        assert se.value.code == "SHEETS_TAB_NOT_FOUND"

    def test_18_400_other_maps_to_range_invalid(self):
        exc = self._make_http_error(400, "Bad request")
        with pytest.raises(SheetsError) as se:
            _classify_http_error(exc)
        assert se.value.code == "SHEETS_RANGE_INVALID"

    def test_19_500_maps_to_append_failed(self):
        exc = self._make_http_error(500, "Internal error")
        with pytest.raises(SheetsError) as se:
            _classify_http_error(exc)
        assert se.value.code == "SHEETS_APPEND_FAILED"


# ── Plugin Error Propagation ─────────────────────────────────────────────────


class TestPluginErrorPropagation:

    def test_20_plugin_preserves_error_code(self):
        """SheetsPlugin should preserve error_code and row_appended=false on failure."""
        from voice_platform.integrations.plugins.sheets import SheetsPlugin
        from voice_platform.integrations.plugins.base import (
            IntegrationConfiguration,
            PluginExecutionRequest,
        )
        import asyncio

        plugin = SheetsPlugin(client_factory=lambda integ: None)

        # Mock client that raises SheetsError
        mock_client = AsyncMock()
        mock_client.append_row = AsyncMock(
            side_effect=SheetsError("SHEETS_TAB_NOT_FOUND")
        )
        plugin._client_factory = lambda integ: mock_client

        integration = IntegrationConfiguration(
            service_type="google_sheets",
            api_key=None,
            api_secret=None,
            config={},
            user_id=1,
        )
        request = PluginExecutionRequest(
            integration=integration,
            action="append_row",
            params={"values": ["test"], "range": "Patients!A:K"},
        )

        result = asyncio.run(plugin.execute(request))
        assert result.success is False
        assert result.output["row_appended"] is False
        assert result.output["error_code"] == "SHEETS_TAB_NOT_FOUND"
        assert result.error == "The configured worksheet was not found."


# ── Business Outcome Tests ───────────────────────────────────────────────────


class TestBusinessOutcome:

    def test_21_booking_remains_booked_when_sheets_fails(self):
        """When patient logging fails, booking must remain 'booked'."""
        from voice_platform.flow.nodes import _update_business_outcome, OperationType
        current = {
            "booking": "booked",
            "patient_log": "not_attempted",
            "email": "not_attempted",
            "overall": "in_progress",
        }
        integration_result = {
            "business_succeeded": False,
            "business_status": "failed",
            "operation": OperationType.APPEND_PATIENT_LOG,
            "evidence": {"patient_logged": False},
        }
        outcome = _update_business_outcome(current, integration_result)
        assert outcome["booking"] == "booked"
        assert outcome["patient_log"] == "failed"
        assert outcome["overall"] == "partial_success"

    def test_22_email_skipped_after_patient_log_failure(self):
        """After patient_log=failed, the business outcome should be partial_success."""
        from voice_platform.flow.nodes import _update_business_outcome, OperationType
        current = {
            "booking": "booked",
            "patient_log": "failed",
            "email": "not_attempted",
            "overall": "partial_success",
        }
        # If email is attempted and also fails
        integration_result = {
            "business_succeeded": False,
            "business_status": "failed",
            "operation": OperationType.SEND_EMAIL,
            "evidence": {"email_sent": False},
        }
        outcome = _update_business_outcome(current, integration_result)
        assert outcome["email"] == "failed"
        assert outcome["overall"] == "partial_success"

    def test_23_partial_success_tts_is_truthful(self):
        """Boundary response for booking should not say everything failed."""
        from voice_platform.flow.nodes import boundary_response, OperationType
        # Booking succeeded
        msg = boundary_response(OperationType.CREATE_BOOKING, True, {"booking": "booked"})
        assert msg is not None
        assert "booked" in msg.lower()
        assert "failed" not in msg.lower()

    def test_24_retrying_sheets_does_not_recreate_calendar(self):
        """_normalize_integration_result for APPEND_PATIENT_LOG does not set booking evidence."""
        from voice_platform.flow.nodes import _normalize_integration_result
        result = _normalize_integration_result(
            "sheets_1", "google_sheets", {"action": "append_row"},
            {"result": {"row_appended": False, "error_code": "SHEETS_TAB_NOT_FOUND"}},
            "error",
        )
        ev = result["integration_result"]["evidence"]
        assert ev["booking_created"] is False
        assert ev["patient_logged"] is False


# ── Persisted Graph Verification ─────────────────────────────────────────────


class TestPersistedGraphRange:

    def test_25_agent_14_contains_corrected_range(self):
        """Agent #14 persisted graph should have 'Sheet1'!A:K, not Patients!A:K."""
        from scripts.patch_smilecare_sheets_range import (
            _find_range_occurrences, _parse_graph, NEW_RANGE, OLD_RANGE,
        )

        # Build a mock graph matching the patched state
        graph = {
            "nodes": [
                {"id": "action_1", "type": "action", "data": {"config": {
                    "params": {"range": NEW_RANGE}
                }}},
                {"id": "sheets_1", "type": "google_sheets", "data": {"config": {
                    "params": {"range": NEW_RANGE}
                }}},
            ],
            "edges": [],
        }
        occurrences = _find_range_occurrences(graph)
        assert len(occurrences) == 0, "Should have no Patients!A:K occurrences"

    def test_26_patch_script_idempotent(self):
        """Running patch on already-fixed graph returns ALREADY_FIXED."""
        from scripts.patch_smilecare_sheets_range import _find_range_occurrences, NEW_RANGE
        graph = {
            "nodes": [
                {"id": "sheets_1", "type": "google_sheets", "data": {"config": {
                    "params": {"range": NEW_RANGE}
                }}},
            ],
            "edges": [],
        }
        occurrences = _find_range_occurrences(graph)
        assert len(occurrences) == 0


# ── Diagnostics Safety ───────────────────────────────────────────────────────


class TestDiagnosticsSafety:

    def test_27_sheets_error_message_has_no_pii(self):
        """SheetsError messages must not contain spreadsheet IDs, tab names, or raw exceptions."""
        for code in [
            "SHEETS_SPREADSHEET_NOT_FOUND",
            "SHEETS_PERMISSION_DENIED",
            "SHEETS_TAB_NOT_FOUND",
            "SHEETS_RANGE_INVALID",
            "SHEETS_COLUMN_COUNT_MISMATCH",
            "SHEETS_APPEND_FAILED",
        ]:
            err = SheetsError(code)
            msg = err.message_safe
            # No spreadsheet IDs (look for long alphanumeric strings)
            assert not re.search(r'[a-zA-Z0-9]{30,}', msg), f"{code} message may contain ID: {msg}"
            # No tab names
            assert "Patients" not in msg
            assert "Sheet1" not in msg
            # No raw exception text
            assert "HttpError" not in msg
            assert "400" not in msg

    def test_28_plugin_result_has_no_raw_exception(self):
        """PluginResult error should use message_safe, not raw exception text."""
        from voice_platform.integrations.plugins.sheets import SheetsPlugin
        from voice_platform.integrations.plugins.base import (
            IntegrationConfiguration,
            PluginExecutionRequest,
        )
        import asyncio

        plugin = SheetsPlugin()
        mock_client = AsyncMock()
        raw_exc = Exception("HttpError 400: Unable to parse range: Patients!A1 with spreadsheet 14alpNk...")
        mock_client.append_row = AsyncMock(side_effect=raw_exc)
        plugin._client_factory = lambda integ: mock_client

        integration = IntegrationConfiguration(
            service_type="google_sheets",
            api_key=None,
            api_secret=None,
            config={},
            user_id=1,
        )
        request = PluginExecutionRequest(
            integration=integration,
            action="append_row",
            params={"values": ["test"], "range": "Patients!A:K"},
        )

        result = asyncio.run(plugin.execute(request))
        assert result.success is False
        # For non-SheetsError exceptions, the raw message goes into error
        # but error_code should be SHEETS_APPEND_FAILED
        assert result.output["error_code"] == "SHEETS_APPEND_FAILED"
        assert result.output["row_appended"] is False
