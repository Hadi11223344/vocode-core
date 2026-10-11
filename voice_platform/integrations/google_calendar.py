"""
Voice Platform — Google Calendar Integration
================================================

Wraps the Google Calendar API for use during voice calls.
Supports creating, listing, updating, and deleting events.

Usage:
    client = GoogleCalendarClient(credentials_json, config)
    events = await client.list_events(max_results=5)
    event = await client.create_event(
        summary="Meeting with client",
        start="2024-01-15T10:00:00",
        end="2024-01-15T11:00:00",
    )

Authentication:
    Users provide a Google Cloud service account JSON key via /api/keys.
    The key is stored in user_api_keys.api_key as a JSON string.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from loguru import logger


class GoogleCalendarClient:
    """
    Async-compatible Google Calendar client.
    
    Uses the Google Calendar API v3 via the google-api-python-client
    library. Operations are run in a thread pool since the Google
    client library is synchronous.
    """
    
    def __init__(self, credentials_json: Optional[str], config: dict = None, user_id: int = None):
        """
        Args:
            credentials_json: Google Cloud service account JSON key (as string).
                              Legacy fallback — prefer OAuth via user_id.
            config: Integration config. For OAuth, calendar_id defaults to "primary"
                    (the user's own calendar). For service account, must be shared.
            user_id: User ID for OAuth token lookup. If provided, OAuth is used
                     instead of service account credentials.
        """
        self._credentials_json = credentials_json
        self._config = config or {}
        self._user_id = user_id
        self._calendar_id = self._config.get("calendar_id", "primary")
        self._timezone = self._config.get("timezone", "America/New_York")
        self._service = None

        if not user_id and self._config.get("calendar_id") == "primary":
            logger.warning(
                "GoogleCalendarClient: service account mode with calendar_id='primary'. "
                "Service accounts cannot access 'primary'. Use OAuth (recommended) or "
                "share a specific calendar with the service account."
            )

    async def _get_service(self):
        """Lazily build the Google Calendar API service using OAuth or service account."""
        if self._service is not None:
            return self._service

        from googleapiclient.discovery import build

        # Try OAuth first (preferred)
        if self._user_id:
            from voice_platform.integrations.google_oauth import GoogleOAuthManager
            creds = await GoogleOAuthManager.get_credentials(self._user_id)
            if creds:
                # Check if Calendar scope is present in the granted scopes
                granted_scopes = creds.scopes or []
                has_calendar_scope = any(
                    "calendar" in s for s in granted_scopes
                )
                if not has_calendar_scope:
                    logger.warning(
                        f"GoogleCalendarClient: OAuth token for user {self._user_id} "
                        f"lacks Calendar scope. Granted scopes: {granted_scopes}. "
                        f"User must re-authorize at Settings → Integrations → Connect with Google."
                    )
                    raise ValueError(
                        "Google Calendar not authorized. Your Google account is connected "
                        "but Calendar access was not granted. Please re-connect at "
                        "Settings → Integrations → Connect with Google to grant Calendar access."
                    )
                self._service = build("calendar", "v3", credentials=creds)
                logger.info(f"GoogleCalendarClient: using OAuth for user {self._user_id}")
                return self._service
            logger.warning(f"No OAuth token for user {self._user_id}, falling back to service account")

        # Fallback to service account
        if not self._credentials_json:
            raise ValueError(
                "Google Calendar not connected. "
                "Go to Settings → Integrations and click 'Connect with Google' to authorize Calendar access."
            )

        from google.oauth2 import service_account
        creds_data = json.loads(self._credentials_json)
        credentials = service_account.Credentials.from_service_account_info(
            creds_data,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        sa_email = creds_data.get("client_email", "unknown")
        logger.info(
            f"GoogleCalendarClient: using service account '{sa_email}' "
            f"for calendar {self._calendar_id}"
        )
        self._service = build("calendar", "v3", credentials=credentials)
        return self._service


    async def test_connection(self) -> dict:
        """Test the connection by listing calendars."""
        import asyncio

        service = await self._get_service()

        def _test():
            result = service.calendarList().list(maxResults=3).execute()
            calendars = result.get("items", [])
            return {
                "calendars_found": len(calendars),
                "calendar_names": [c.get("summary", "Unknown") for c in calendars[:3]],
            }

        return await asyncio.to_thread(_test)
    
    async def list_events(
        self,
        max_results: int = 10,
        time_min: Optional[str] = None,
    ) -> list[dict]:
        """
        List upcoming events from the calendar.
        
        Args:
            max_results: Maximum number of events to return
            time_min: ISO datetime string — only events after this time
        """
        import asyncio

        service = await self._get_service()

        def _list():
            if not time_min:
                now = datetime.now(timezone.utc).isoformat()
            else:
                now = time_min
            
            result = service.events().list(
                calendarId=self._calendar_id,
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            
            events = result.get("items", [])
            return [
                {
                    "id": e.get("id"),
                    "summary": e.get("summary", "No title"),
                    "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date")),
                    "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date")),
                    "description": e.get("description", ""),
                    "location": e.get("location", ""),
                    "status": e.get("status"),
                }
                for e in events
            ]
        
        return await asyncio.to_thread(_list)
    
    async def create_event(
        self,
        summary: str,
        start: str,
        end: Optional[str] = None,
        description: str = "",
        location: str = "",
        attendees: list[str] = None,
        duration_minutes: int = 60,
    ) -> dict:
        """
        Create a new calendar event.
        
        Args:
            summary: Event title
            start: Start datetime (ISO format)
            end: End datetime (ISO format). Defaults to start + duration_minutes.
            description: Event description
            location: Event location
            attendees: List of email addresses
            duration_minutes: Duration in minutes when end is not provided. Defaults to 60.
        """
        import asyncio

        service = await self._get_service()

        def _create():
            if not isinstance(start, str) or not start.strip():
                raise ValueError(
                    f"Google Calendar create_event requires a non-empty 'start' datetime string. "
                    f"Received {start!r} (type: {type(start).__name__}). "
                    f"Check that the flow passes a valid date/time to this node."
                )

            # Parse start time and calculate end if not provided
            if not end:
                start_dt = datetime.fromisoformat(start)
                end_dt = start_dt + timedelta(minutes=duration_minutes)
                end_str = end_dt.isoformat()
            else:
                end_str = end

            # Determine the timezone to send to Google Calendar.
            # If the datetime string already has a UTC offset (e.g. +05:00),
            # extract the IANA timezone name from it; otherwise fall back to
            # the configured timezone.  This prevents 400 errors when the
            # agent timezone (Asia/Karachi) differs from the integration
            # config timezone (e.g. America/New_York).
            from zoneinfo import ZoneInfo
            try:
                parsed = datetime.fromisoformat(start)
                if parsed.utcoffset() is not None:
                    # Use the parsed datetime's tzinfo name, or derive it
                    tz_to_use = self._timezone
                    # Try to match the offset to a known timezone
                    if parsed.tzinfo and hasattr(parsed.tzinfo, 'key'):
                        tz_to_use = parsed.tzinfo.key
                    elif self._timezone:
                        # Verify config timezone matches the offset
                        config_tz = ZoneInfo(self._timezone)
                        config_offset = datetime.now(config_tz).utcoffset()
                        if config_offset != parsed.utcoffset():
                            # Timezone mismatch — use the datetime's own offset
                            # Google accepts offset-based timeZone like "+05:00"
                            offset = parsed.utcoffset()
                            total_min = int(offset.total_seconds() / 60)
                            sign = "+" if total_min >= 0 else "-"
                            total_min = abs(total_min)
                            tz_to_use = f"{sign}{total_min // 60:02d}:{total_min % 60:02d}"
                else:
                    tz_to_use = self._timezone
            except Exception:
                tz_to_use = self._timezone

            event_body: dict[str, Any] = {
                "summary": summary,
                "description": description,
                "location": location,
                "start": {"dateTime": start, "timeZone": tz_to_use},
                "end": {"dateTime": end_str, "timeZone": tz_to_use},
            }
            
            if attendees:
                import re as _re
                _EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
                valid = [e for e in attendees if _EMAIL_RE.match(e)]
                if valid:
                    event_body["attendees"] = [{"email": email} for email in valid]

            logger.info(
                f"create_event: calendarId={self._calendar_id!r}, "
                f"start={start!r}, end={end_str!r}, tz={tz_to_use!r}, "
                f"summary={summary!r}"
            )
            
            event = service.events().insert(
                calendarId=self._calendar_id,
                body=event_body,
            ).execute()
            
            return {
                "id": event.get("id"),
                "summary": event.get("summary"),
                "start": event.get("start", {}).get("dateTime"),
                "end": event.get("end", {}).get("dateTime"),
                "html_link": event.get("htmlLink"),
                "status": "created",
            }
        
        return await asyncio.to_thread(_create)
    
    async def update_event(
        self,
        event_id: str,
        summary: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        """Update an existing calendar event."""
        import asyncio

        service = await self._get_service()

        def _update():
            
            # Fetch existing event
            event = service.events().get(
                calendarId=self._calendar_id,
                eventId=event_id,
            ).execute()
            
            if summary:
                event["summary"] = summary
            if description is not None:
                event["description"] = description
            if start:
                event["start"] = {"dateTime": start, "timeZone": self._timezone}
            if end:
                event["end"] = {"dateTime": end, "timeZone": self._timezone}
            
            updated = service.events().update(
                calendarId=self._calendar_id,
                eventId=event_id,
                body=event,
            ).execute()
            
            return {
                "id": updated.get("id"),
                "summary": updated.get("summary"),
                "status": "updated",
            }
        
        return await asyncio.to_thread(_update)
    
    async def delete_event(self, event_id: str) -> dict:
        """Delete a calendar event."""
        import asyncio

        service = await self._get_service()

        def _delete():
            service.events().delete(
                calendarId=self._calendar_id,
                eventId=event_id,
            ).execute()
            return {"event_id": event_id, "status": "deleted"}
        
        return await asyncio.to_thread(_delete)
    
    async def check_availability(
        self,
        date: str,
        duration_minutes: int = 60,
        business_hours_start: str = "09:00",
        business_hours_end: str = "17:00",
    ) -> dict:
        """
        Check available time slots on a given date.

        Computes free slots by subtracting busy events from the business hours
        window. Returns both ``busy_slots`` and ``available_slots`` so callers
        (and the LLM) don't have to mentally compute free time.

        Args:
            date: Date in YYYY-MM-DD format
            duration_minutes: Desired meeting duration — slots shorter than
                              this are filtered out of ``available_slots``.
            business_hours_start: Start of business hours (HH:MM, 24h).
            business_hours_end: End of business hours (HH:MM, 24h).
        """
        import asyncio
        import re as _re
        from datetime import datetime, timedelta

        service = await self._get_service()
        tz_suffix = _tz_offset(self._timezone)

        # Validate date format
        if not _re.match(r"^\d{4}-\d{2}-\d{2}$", str(date).strip()):
            return {
                "date": date,
                "busy_slots": [],
                "available_slots": [],
                "total_events": 0,
                "error": f"Invalid date format '{date}'. Expected YYYY-MM-DD.",
            }

        def _check():
            start_of_day = f"{date}T{business_hours_start}:00"
            end_of_day = f"{date}T{business_hours_end}:00"

            logger.info(
                f"check_availability: calendar={self._calendar_id}, date={date}, "
                f"hours={business_hours_start}-{business_hours_end}, duration={duration_minutes}"
            )

            result = service.events().list(
                calendarId=self._calendar_id,
                timeMin=f"{start_of_day}{tz_suffix}",
                timeMax=f"{end_of_day}{tz_suffix}",
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            events = result.get("items", [])
            busy_slots = []
            for e in events:
                start_obj = e.get("start", {})
                end_obj = e.get("end", {})
                # Handle both datetime events and all-day events
                s = start_obj.get("dateTime") or f"{start_obj.get('date')}T00:00:00"
                en = end_obj.get("dateTime") or f"{end_obj.get('date')}T00:00:00"
                if s and en:
                    busy_slots.append({"start": s, "end": en, "summary": e.get("summary", "Busy")})

            # ── Compute available slots ───────────────────────────────
            # Subtract busy periods from the business hours window.
            window_start = datetime.fromisoformat(f"{start_of_day}{tz_suffix}")
            window_end = datetime.fromisoformat(f"{end_of_day}{tz_suffix}")
            min_duration = timedelta(minutes=duration_minutes)

            # Sort busy slots by start time
            sorted_busy = sorted(busy_slots, key=lambda b: b["start"])
            available_slots = []
            cursor = window_start
            for b in sorted_busy:
                try:
                    b_start = datetime.fromisoformat(b["start"])
                    b_end = datetime.fromisoformat(b["end"])
                except (ValueError, TypeError):
                    continue
                # Clamp busy slot to the business window
                b_start = max(b_start, window_start)
                b_end = min(b_end, window_end)
                if b_start > cursor:
                    gap_end = b_start
                    if gap_end - cursor >= min_duration:
                        available_slots.append({
                            "start": cursor.isoformat(),
                            "end": gap_end.isoformat(),
                        })
                cursor = max(cursor, b_end)

            # Remaining gap after last busy slot
            if window_end - cursor >= min_duration:
                available_slots.append({
                    "start": cursor.isoformat(),
                    "end": window_end.isoformat(),
                })

            logger.info(
                f"check_availability: found {len(events)} events, "
                f"{len(busy_slots)} busy slots, {len(available_slots)} available slots"
            )

            return {
                "date": date,
                "busy_slots": busy_slots,
                "available_slots": available_slots,
                "total_events": len(events),
            }

        return await asyncio.to_thread(_check)


def _tz_offset(timezone_name: str) -> str:
    """
    Get the current UTC offset for a timezone name, accounting for DST.
    
    Uses Python's zoneinfo (3.9+) for accurate DST-aware offsets.
    Falls back to a static lookup if the timezone name is unknown.
    """
    try:
        from datetime import datetime
        from datetime import timezone as _tz
        from zoneinfo import ZoneInfo
        
        tz = ZoneInfo(timezone_name)
        now = datetime.now(tz)
        offset = now.utcoffset()
        total_seconds = int(offset.total_seconds())
        sign = "+" if total_seconds >= 0 else "-"
        hours, remainder = divmod(abs(total_seconds), 3600)
        minutes = remainder // 60
        return f"{sign}{hours:02d}:{minutes:02d}"
    except Exception:
        # Fallback for unknown timezone names
        return "+00:00"
