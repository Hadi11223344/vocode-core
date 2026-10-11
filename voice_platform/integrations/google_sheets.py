"""
Voice Platform — Google Sheets Integration
=============================================

Wraps the Google Sheets API for use during voice calls.
Supports reading rows, appending data, updating rows, and searching.

Usage:
    client = GoogleSheetsClient(credentials_json, config)
    rows = await client.read_rows(range="A1:D10")
    await client.append_row(values=["John", "john@example.com", "2024-01-15"])

Authentication:
    Users provide a Google Cloud service account JSON key via /api/keys.
    The service account must have access to the target spreadsheet.
"""

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from loguru import logger

# M-7: Timeout for all Google Sheets API calls
_API_TIMEOUT = 30

# M-8: Dedicated thread pool for Google Sheets operations
_sheets_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sheets")


class SheetsError(Exception):
    """Structured error from Google Sheets operations with safe code and message."""

    _SAFE_MESSAGES = {
        "SHEETS_SPREADSHEET_NOT_FOUND": "The configured spreadsheet was not found.",
        "SHEETS_PERMISSION_DENIED": "Permission denied for the configured spreadsheet.",
        "SHEETS_TAB_NOT_FOUND": "The configured worksheet was not found.",
        "SHEETS_RANGE_INVALID": "The configured range is invalid.",
        "SHEETS_COLUMN_COUNT_MISMATCH": "The number of values exceeds the configured column width.",
        "SHEETS_APPEND_FAILED": "The spreadsheet provider rejected the append operation.",
    }

    def __init__(self, code: str, original: Exception = None):
        self.code = code
        self.message_safe = self._SAFE_MESSAGES.get(code, "An unexpected error occurred.")
        self._original = original
        super().__init__(self.message_safe)

    def __str__(self) -> str:
        return self.message_safe


def _col_letter(n: int) -> str:
    """
    Convert a 1-based column number to an Excel-style letter (1=A, 26=Z, 27=AA, etc.).
    """
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _col_number(letter: str) -> int:
    """Convert a column letter (A, B, AA) to a 1-based column number."""
    num = 0
    for ch in letter.upper():
        if not ch.isalpha():
            raise ValueError(f"Invalid column letter: {letter}")
        num = num * 26 + (ord(ch) - ord("A") + 1)
    return num


def _parse_a1_range(range_str: str) -> dict:
    """Parse an A1 range string into sheet title and cell expression.

    Returns:
        {"sheet_title": str | None, "cell_range": str, "start_column": int | None, "end_column": int | None}

    Raises:
        SheetsError: If the range is malformed.
    """
    if not range_str or not range_str.strip():
        raise SheetsError("SHEETS_RANGE_INVALID")

    s = range_str.strip()

    # Reject formulas
    if s.startswith("="):
        raise SheetsError("SHEETS_RANGE_INVALID")

    sheet_title = None
    cell_range = s

    if "!" in s:
        parts = s.split("!")
        if len(parts) > 2:
            raise SheetsError("SHEETS_RANGE_INVALID")
        title_part, cell_part = parts[0], parts[1]

        # Handle quoted sheet titles: 'Patient Records' or 'Owner''s Records'
        if title_part.startswith("'"):
            if not title_part.endswith("'") or len(title_part) < 2:
                raise SheetsError("SHEETS_RANGE_INVALID")
            # Unescape doubled single quotes: '' -> '
            inner = title_part[1:-1].replace("''", "'")
            if not inner.strip():
                raise SheetsError("SHEETS_RANGE_INVALID")
            sheet_title = inner
        else:
            sheet_title = title_part.strip()
            if not sheet_title:
                raise SheetsError("SHEETS_RANGE_INVALID")

        cell_range = cell_part.strip()
        if not cell_range:
            raise SheetsError("SHEETS_RANGE_INVALID")
    # else: no explicit sheet title

    # Parse columns from cell_range (e.g. A:K, A1:K10, A1, A:K)
    start_column = None
    end_column = None
    col_pattern = r"^([A-Z]+)(\d*)?(:([A-Z]+)(\d*)?)?$"
    m = re.match(col_pattern, cell_range.upper())
    if m:
        start_col = m.group(1)
        end_col = m.group(4)
        if start_col:
            start_column = _col_number(start_col)
        if end_col:
            end_column = _col_number(end_col)
            if start_column and end_column < start_column:
                raise SheetsError("SHEETS_RANGE_INVALID")

    return {
        "sheet_title": sheet_title,
        "cell_range": cell_range,
        "start_column": start_column,
        "end_column": end_column,
    }


def _classify_http_error(exc: Exception) -> None:
    """Classify a googleapiclient HttpError into a SheetsError and raise it.

    Examines the HTTP status code and message to map to the correct safe error code.
    The original exception is preserved internally but never exposed to callers.
    """
    status_code = getattr(exc, "resp", None)
    if status_code is not None:
        status_code = getattr(status_code, "status", None)
    if status_code is None:
        try:
            status_code = int(getattr(exc, "status_code", 0))
        except (TypeError, ValueError):
            status_code = 0

    msg = str(exc)

    if status_code == 404:
        raise SheetsError("SHEETS_SPREADSHEET_NOT_FOUND", original=exc)
    if status_code == 403:
        raise SheetsError("SHEETS_PERMISSION_DENIED", original=exc)
    if status_code == 400:
        if "Unable to parse range" in msg:
            raise SheetsError("SHEETS_TAB_NOT_FOUND", original=exc)
        raise SheetsError("SHEETS_RANGE_INVALID", original=exc)

    raise SheetsError("SHEETS_APPEND_FAILED", original=exc)


class GoogleSheetsClient:
    """
    Async-compatible Google Sheets client.
    
    Uses the Google Sheets API v4 via the google-api-python-client
    library. Operations are run in a thread pool since the Google
    client library is synchronous.
    """
    
    def __init__(self, credentials_json: Optional[str], config: dict = None, user_id: int = None, event_callback=None):
        """
        Args:
            credentials_json: Google Cloud service account JSON key (as string).
                              Legacy fallback — prefer OAuth via user_id.
            config: Must contain spreadsheet_id, optional sheet_name
            user_id: User ID for OAuth token lookup. If provided, OAuth is used
                     instead of service account credentials.
            event_callback: Optional async callback for emitting warning events.
        """
        self._credentials_json = credentials_json
        self._config = config or {}
        self._user_id = user_id
        self._event_callback = event_callback
        self._spreadsheet_id = self._config.get("spreadsheet_id")
        self._sheet_name = self._config.get("sheet_name", "Sheet1")
        self._service = None
        self._resolved_sheet_name = None

        if not self._spreadsheet_id:
            raise ValueError("spreadsheet_id is required in config")

    async def _get_service(self):
        """Lazily build the Google Sheets API service using OAuth or service account."""
        if self._service is not None:
            return self._service

        from googleapiclient.discovery import build

        # Try OAuth first (preferred)
        if self._user_id:
            from voice_platform.integrations.google_oauth import GoogleOAuthManager
            creds = await GoogleOAuthManager.get_credentials(self._user_id)
            if creds:
                self._service = build("sheets", "v4", credentials=creds)
                logger.info(f"GoogleSheetsClient: using OAuth for user {self._user_id}")
                return self._service
            # L-5: Improved warning with actionable guidance
            logger.warning(
                f"No valid OAuth token for user {self._user_id}. "
                f"The token may be expired or revoked. "
                f"Please re-authorize at Settings → Integrations → Connect with Google. "
                f"Falling back to service account credentials if available."
            )

        # Fallback to service account
        if not self._credentials_json:
            raise ValueError(
                "Google Sheets not connected. "
                "Go to Settings → Integrations and click 'Connect with Google' to authorize Sheets access."
            )

        from google.oauth2 import service_account
        creds_data = json.loads(self._credentials_json)
        credentials = service_account.Credentials.from_service_account_info(
            creds_data,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        logger.info("GoogleSheetsClient: using service account credentials")
        self._service = build("sheets", "v4", credentials=credentials)
        return self._service
    
    async def _get_sheet_titles(self) -> list[str]:
        """Fetch the list of worksheet tab titles from the spreadsheet metadata."""
        service = await self._get_service()

        def _get_names():
            result = service.spreadsheets().get(
                spreadsheetId=self._spreadsheet_id,
                fields="sheets(properties(title))",
            ).execute()
            return [
                s.get("properties", {}).get("title", "")
                for s in result.get("sheets", [])
            ]

        return await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(_sheets_executor, _get_names),
            timeout=_API_TIMEOUT,
        )

    async def _resolve_sheet_name(self) -> str:
        """Resolve the actual sheet tab name, falling back to the first tab if configured name doesn't exist."""
        if self._resolved_sheet_name is not None:
            return self._resolved_sheet_name

        try:
            actual_names = await self._get_sheet_titles()
            if self._sheet_name in actual_names:
                self._resolved_sheet_name = self._sheet_name
            elif actual_names:
                logger.warning(
                    f"Sheet '{self._sheet_name}' not found in spreadsheet. "
                    f"Falling back to '{actual_names[0]}'. Available: {actual_names}"
                )
                self._resolved_sheet_name = actual_names[0]
                # MEDIUM-10: Emit warning event so frontend/playground can show the mismatch
                if self._event_callback:
                    try:
                        asyncio.ensure_future(self._event_callback({
                            "event": "warning",
                            "text": f"Sheet tab '{self._sheet_name}' not found. Using '{actual_names[0]}' instead.",
                        }))
                    except Exception:
                        pass
            else:
                self._resolved_sheet_name = self._sheet_name
        except Exception as e:
            logger.warning(f"Could not fetch sheet names for resolution: {e}. Using configured name.")
            self._resolved_sheet_name = self._sheet_name

        return self._resolved_sheet_name

    async def test_connection(self) -> dict:
        """Test connection by reading spreadsheet metadata."""
        import asyncio

        service = await self._get_service()

        def _test():
            result = service.spreadsheets().get(
                spreadsheetId=self._spreadsheet_id,
            ).execute()
            
            sheets = result.get("sheets", [])
            return {
                "spreadsheet_title": result.get("properties", {}).get("title", "Unknown"),
                "sheet_count": len(sheets),
                "sheet_names": [
                    s.get("properties", {}).get("title", "Unknown")
                    for s in sheets[:5]
                ],
            }
        
        return await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(_sheets_executor, _test),
            timeout=_API_TIMEOUT,
        )
    
    async def read_rows(
        self,
        cell_range: Optional[str] = None,
        max_rows: int = 100,
    ) -> list[list[str]]:
        """
        Read rows from the spreadsheet.

        Args:
            cell_range: A1 notation range (e.g. "A1:D10"). Defaults to sheet!A:Z.
            max_rows: Maximum rows to return
        """
        service = await self._get_service()

        if cell_range and "!" in cell_range:
            parsed = _parse_a1_range(cell_range)
            explicit_title = parsed["sheet_title"]
            if explicit_title:
                actual_names = await self._get_sheet_titles()
                if explicit_title not in actual_names:
                    raise SheetsError("SHEETS_TAB_NOT_FOUND")
                range_str = f"{explicit_title}!{parsed['cell_range']}"
            else:
                sheet = await self._resolve_sheet_name()
                range_str = f"{sheet}!{parsed['cell_range']}"
        else:
            sheet = await self._resolve_sheet_name()
            range_str = cell_range or f"{sheet}!A1:Z{max_rows}"

        def _read():
            result = service.spreadsheets().values().get(
                spreadsheetId=self._spreadsheet_id,
                range=range_str,
            ).execute()

            rows = result.get("values", [])
            return rows[:max_rows]

        return await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(_sheets_executor, _read),
            timeout=_API_TIMEOUT,
        )
    
    async def append_row(self, values: list[str], range: str = None) -> dict:
        """
        Append a row to the end of the spreadsheet.

        Args:
            values: List of cell values for the new row
            range: Optional range string like "'Sheet1'!A:K". If provided,
                   the sheet name is extracted, validated, and used for the append range.
                   If not provided, falls back to the configured sheet name.

        Raises:
            SheetsError: With a safe error code if preflight validation fails.
        """
        service = await self._get_service()

        # ── Preflight validation ───────────────────────────────────────────
        if range and "!" in range:
            parsed = _parse_a1_range(range)
            explicit_title = parsed["sheet_title"]
            if not explicit_title:
                raise SheetsError("SHEETS_RANGE_INVALID")

            # Verify the worksheet tab exists
            actual_names = await self._get_sheet_titles()
            if explicit_title not in actual_names:
                logger.warning(
                    f"append_row: worksheet tab '{explicit_title}' not found. "
                    f"Available tabs: {actual_names}"
                )
                raise SheetsError("SHEETS_TAB_NOT_FOUND")

            # Validate column count if both start and end columns are known
            if parsed["start_column"] and parsed["end_column"]:
                col_width = parsed["end_column"] - parsed["start_column"] + 1
                if len(values) > col_width:
                    raise SheetsError("SHEETS_COLUMN_COUNT_MISMATCH")

            # Use the validated title — quote if it contains spaces or special chars
            if " " in explicit_title or "'" in explicit_title or not explicit_title.isalnum():
                safe_title = "'" + explicit_title.replace("'", "''") + "'"
            else:
                safe_title = explicit_title
            # Always append from column A of the target sheet. Using A:K as the
            # Sheets "table" range can make Google start the next write at column K
            # (e.g. K2:U2) when row 1 already fills A:K — shifting data sideways.
            append_range = f"{safe_title}!A:A"
            self._resolved_sheet_name = explicit_title
        else:
            sheet = await self._resolve_sheet_name()
            append_range = f"{sheet}!A:A"

        # ── Execute append ─────────────────────────────────────────────────
        def _append():
            try:
                result = service.spreadsheets().values().append(
                    spreadsheetId=self._spreadsheet_id,
                    range=append_range,
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [values]},
                ).execute()
            except Exception as e:
                _classify_http_error(e)

            updated_range = result.get("updates", {}).get("updatedRange", "")
            row_number = None
            m = re.search(r'![A-Z]+(\d+):', updated_range)
            if m:
                row_number = int(m.group(1))
            # Also match single-cell ranges like Sheet1!A3
            if row_number is None:
                m2 = re.search(r'![A-Z]+(\d+)$', updated_range)
                if m2:
                    row_number = int(m2.group(1))

            return {
                "updated_range": updated_range,
                "updated_rows": result.get("updates", {}).get("updatedRows", 0),
                "row_number": row_number,
                "status": "appended",
                "append_range_used": append_range,
            }

        return await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(_sheets_executor, _append),
            timeout=_API_TIMEOUT,
        )
    
    async def update_row(
        self,
        row_number: int,
        values: list[str],
    ) -> dict:
        """
        Update a specific row in the spreadsheet.
        
        Args:
            row_number: 1-based row number
            values: New cell values for the row
        """
        import asyncio

        # LOW-8: Validate row_number before making API call
        if row_number < 1:
            return {"success": False, "error": "row_number must be >= 1"}

        service = await self._get_service()
        sheet = await self._resolve_sheet_name()

        # Calculate range for the row — handles >26 columns (AA, AB, etc.)
        col_count = len(values)
        end_col = _col_letter(col_count)
        range_str = f"{sheet}!A{row_number}:{end_col}{row_number}"

        def _update():
            result = service.spreadsheets().values().update(
                spreadsheetId=self._spreadsheet_id,
                range=range_str,
                valueInputOption="USER_ENTERED",
                body={"values": [values]},
            ).execute()

            return {
                "updated_range": result.get("updatedRange", ""),
                "updated_cells": result.get("updatedCells", 0),
                "status": "updated",
            }

        return await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(_sheets_executor, _update),
            timeout=_API_TIMEOUT,
        )
    
    async def search_rows(
        self,
        column: str,
        query: str,
        max_results: int = 10,
    ) -> list[dict]:
        """
        Search for rows where a specific column contains the query string.
        
        Args:
            column: Column letter (A, B, C, etc.)
            query: Search string (case-insensitive partial match)
            max_results: Maximum matching rows to return
        """
        import asyncio

        service = await self._get_service()
        sheet = await self._resolve_sheet_name()

        def _search():
            # M-9: Cap range to A1:Z10000 to prevent reading entire sheet for large spreadsheets
            result = service.spreadsheets().values().get(
                spreadsheetId=self._spreadsheet_id,
                range=f"{sheet}!A1:Z10000",
            ).execute()

            rows = result.get("values", [])
            if not rows:
                return []

            # Header row
            headers = rows[0] if rows else []
            # Support multi-char columns (A=0, Z=25, AA=26, AB=27, ...)
            col_upper = column.upper()
            col_index = 0
            for ch in col_upper:
                col_index = col_index * 26 + (ord(ch) - ord("A") + 1)
            col_index -= 1  # Convert to 0-based

            matches = []
            for i, row in enumerate(rows[1:], start=2):  # Skip header, 1-based row
                if col_index < len(row):
                    cell_value = str(row[col_index]).lower()
                    if query.lower() in cell_value:
                        row_dict = {}
                        for j, val in enumerate(row):
                            header = headers[j] if j < len(headers) else f"Column {_col_letter(j + 1)}"
                            row_dict[header] = val
                        row_dict["_row_number"] = i
                        matches.append(row_dict)
                        if len(matches) >= max_results:
                            break

            return matches

        return await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(_sheets_executor, _search),
            timeout=_API_TIMEOUT,
        )
    
    async def get_headers(self) -> list[str]:
        """Get the header row (first row) of the sheet."""
        import asyncio

        service = await self._get_service()
        sheet = await self._resolve_sheet_name()

        def _headers():
            result = service.spreadsheets().values().get(
                spreadsheetId=self._spreadsheet_id,
                range=f"{sheet}!1:1",
            ).execute()

            rows = result.get("values", [])
            return rows[0] if rows else []

        return await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(_sheets_executor, _headers),
            timeout=_API_TIMEOUT,
        )
