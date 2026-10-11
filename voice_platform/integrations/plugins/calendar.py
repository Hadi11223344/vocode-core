"""CalendarPlugin — Google Calendar integration.

Encapsulates calendar actions: create_event, list_events, update_event,
delete_event, check_availability, book_appointment.
Includes _normalize_time and _normalize_date helpers.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


def _normalize_time(time_str: str) -> str:
    """Normalize a time string to HH:MM (24h)."""
    s = str(time_str).strip().strip("'\"")
    if not s:
        return ""

    session_map = {
        "morning": "10:00", "afternoon": "14:00", "evening": "18:00",
        "night": "20:00", "mornings": "10:00", "afternoons": "14:00",
        "evenings": "18:00",
    }
    lowered = s.lower().rstrip(".")
    if lowered in session_map:
        return session_map[lowered]

    m = re.match(r'^(\d{1,2}):(\d{2})(?::\d{2})?$', s)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    m = re.match(r'^(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?$', s)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = (m.group(3) or "").upper()
        if ampm == "PM" and hour < 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"
    m = re.search(r'(\d{1,2}):(\d{2})', s)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    return ""


def _normalize_date(date_str: str, agent_timezone: str | None = None) -> str:
    """Normalize a natural-language date string to YYYY-MM-DD."""
    from datetime import timezone as _tz

    s = str(date_str).strip().strip("'\"")
    if not s:
        return ""

    s = re.split(r'\s+(?:at|@|from|in|around|about)\s+', s, maxsplit=1)[0].strip()

    try:
        from zoneinfo import ZoneInfo

        from dateutil import parser as _date_parser
        tz_name = agent_timezone or "UTC"
        tz = ZoneInfo(tz_name)
        parsed = _date_parser.parse(s, fuzzy=True, default=datetime.now(tz))
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        pass

    m = re.match(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$', s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    m = re.match(r'^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})?$', s)
    if m:
        day = int(m.group(1))
        month_str = m.group(2).lower()
        year = int(m.group(3)) if m.group(3) else datetime.now().year
        try:
            month = datetime.strptime(month_str, "%b").month
        except ValueError:
            try:
                month = datetime.strptime(month_str, "%B").month
            except ValueError:
                return ""
        return datetime(year, month, day).strftime("%Y-%m-%d")

    m = re.match(r'^([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})?$', s)
    if m:
        month_str = m.group(1).lower()
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else datetime.now().year
        try:
            month = datetime.strptime(month_str, "%b").month
        except ValueError:
            try:
                month = datetime.strptime(month_str, "%B").month
            except ValueError:
                return ""
        return datetime(year, month, day).strftime("%Y-%m-%d")

    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(agent_timezone or "UTC")
    except Exception:
        tz = _tz.utc
    today = datetime.now(tz).date()
    lower = s.lower()
    if lower in ("today",):
        return today.strftime("%Y-%m-%d")
    if lower in ("tomorrow", "tommorrow", "tomorow"):
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    m = re.match(r'^(next|this)?\s*(' + '|'.join(weekdays) + r')$', lower)
    if m:
        modifier = m.group(1) or ""
        target_day = weekdays.index(m.group(2))
        current_day = today.weekday()
        if modifier == "next":
            days_ahead = (target_day - current_day) % 7 or 7
        else:
            days_ahead = (target_day - current_day) % 7
        return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    return ""


def _requested_time_is_available(
    date: str,
    requested_time: str,
    duration_minutes: int,
    available_slots: list[dict],
) -> bool:
    """Return whether the complete requested interval fits a free calendar slot."""
    normalized_time = _normalize_time(requested_time)
    if not normalized_time:
        return False

    requested_start_naive = datetime.strptime(
        f"{date} {normalized_time}", "%Y-%m-%d %H:%M"
    )
    for slot in available_slots:
        if not isinstance(slot, dict):
            continue
        try:
            slot_start = datetime.fromisoformat(
                str(slot.get("start", "")).replace("Z", "+00:00")
            )
            slot_end = datetime.fromisoformat(
                str(slot.get("end", "")).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            continue

        requested_start = requested_start_naive.replace(tzinfo=slot_start.tzinfo)
        requested_end = requested_start + timedelta(minutes=duration_minutes)
        if slot_start <= requested_start and requested_end <= slot_end:
            return True
    return False


class CalendarPlugin:
    """Google Calendar integration plugin."""

    kinds = ("google_calendar",)

    def __init__(
        self,
        client_factory: Callable[[IntegrationConfiguration], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    def _build_client(self, integration: IntegrationConfiguration) -> Any:
        from voice_platform.integrations.google_calendar import GoogleCalendarClient
        config = dict(integration.config)
        if integration.agent_timezone:
            config["timezone"] = integration.agent_timezone
        return GoogleCalendarClient(
            integration.api_key, config, user_id=integration.user_id,
        )

    async def execute(self, request: PluginExecutionRequest) -> PluginResult[dict]:
        integration = request.integration
        action = request.action
        params = dict(request.params)
        agent_tz = integration.agent_timezone

        client = self._client_factory(integration) if self._client_factory else self._build_client(integration)

        try:
            if action == "create_event":
                summary = params.get("summary") or params.get("title", "Untitled Event")
                start = params.get("start")
                end = params.get("end")
                duration_minutes = int(params.get("duration_minutes", 60))

                if not start and params.get("date"):
                    from zoneinfo import ZoneInfo as _ZI
                    date_str = str(params["date"]).strip().strip("'\"")
                    raw_time = str(params.get("time") or "").strip()
                    time_str = _normalize_time(raw_time)
                    if not time_str:
                        err = (
                            "Google Calendar create_event requires a valid time when date is used. "
                            f"Received time={params.get('time')!r}."
                        )
                        logger.error(err)
                        return PluginResult(
                            success=False,
                            error=err,
                            output={"success": False, "error": err},
                        )
                    tz_name = agent_tz or integration.config.get("timezone") or "Asia/Karachi"
                    try:
                        if "T" in date_str and len(date_str) > 10:
                            _date_part, _time_part = date_str.split("T", 1)
                            _time_part = _normalize_time(_time_part)
                            if not _time_part:
                                _time_part = "09:00"
                            if _date_part and _time_part:
                                date_str = f"{_date_part}T{_time_part}"
                            start = date_str
                        else:
                            _tz = _ZI(tz_name)
                            _start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                            _start_dt = _start_dt.replace(tzinfo=_tz)
                            start = _start_dt.isoformat()
                    except Exception as e:
                        logger.warning(f"create_event: failed to parse date={date_str!r} time={time_str!r}: {e}, using raw concat")
                        start = f"{date_str}T{time_str}"

                logger.info(f"create_event: summary={summary!r}, start={start!r}, end={end!r}")

                if not isinstance(start, str) or not start.strip():
                    missing = []
                    if not params.get("start"):
                        missing.append("start")
                    if not params.get("date"):
                        missing.append("date")
                    if not params.get("time"):
                        missing.append("time")
                    err = (
                        f"Google Calendar create_event is missing a valid datetime. "
                        f"Resolved start={start!r}. "
                        f"Check the node's Date/Time fields and ensure template variables "
                        f"like preferred_date/preferred_time are populated. "
                        f"Missing/empty fields: {', '.join(missing) or 'start'}."
                    )
                    logger.error(err)
                    return PluginResult(success=False, error=err, output={"success": False, "error": err, "details": {"start": start, "params": params}})

                result = await client.create_event(
                    summary=summary, start=start, end=end,
                    description=params.get("description", ""),
                    location=params.get("location", ""),
                    attendees=params.get("attendees"),
                    duration_minutes=duration_minutes,
                )
                if isinstance(result, dict) and result.get("success") is False:
                    return PluginResult(
                        success=False,
                        error=str(result.get("error") or "Google Calendar create_event failed"),
                    )
                output = dict(result) if isinstance(result, dict) else {"output": result}
                output["event_created"] = True
                return PluginResult(success=True, output=output)

            elif action == "list_events":
                result = {"events": await client.list_events(
                    max_results=int(params.get("max_results", 5)),
                    time_min=params.get("time_min"),
                )}
                return PluginResult(success=True, output=result)

            elif action == "update_event":
                result = await client.update_event(
                    event_id=params["event_id"],
                    summary=params.get("summary"),
                    start=params.get("start"),
                    end=params.get("end"),
                    description=params.get("description"),
                )
                return PluginResult(success=True, output=result)

            elif action == "delete_event":
                result = await client.delete_event(event_id=params["event_id"])
                return PluginResult(success=True, output=result)

            elif action == "check_availability":
                date = params.get("date")
                requested_time = str(params.get("time") or params.get("preferred_time") or "").strip()
                duration_minutes = int(params.get("duration_minutes", 60))
                if not date or not str(date).strip():
                    err = "Google Calendar check_availability requires a non-empty 'date' (e.g. {{preferred_date}})."
                    logger.error(err)
                    return PluginResult(success=False, error=err, output={"success": False, "error": err, "available_slots": [], "requested_time_available": False, "details": {"date": date}})

                normalized_date = _normalize_date(str(date).strip(), agent_tz)
                if not normalized_date:
                    err = f"Google Calendar check_availability could not parse the date '{date}'. Please provide a specific date like '2024-07-15' or 'tomorrow'."
                    logger.error(err)
                    return PluginResult(success=False, error=err, output={"success": False, "error": err, "available_slots": [], "requested_time_available": False, "details": {"date": date}})

                logger.info(f"check_availability: normalized date '{date}' -> '{normalized_date}'")
                result = await client.check_availability(
                    date=normalized_date,
                    duration_minutes=duration_minutes,
                    business_hours_start=str(params.get("business_hours_start", "10:00")).strip().strip("'\""),
                    business_hours_end=str(params.get("business_hours_end", "21:00")).strip().strip("'\""),
                )
                if isinstance(result, dict) and result.get("success") is False:
                    return PluginResult(
                        success=False,
                        error=str(result.get("error") or "Google Calendar availability check failed"),
                    )
                if not isinstance(result, dict):
                    result = {}
                available_slots = result.get("available_slots")
                if not isinstance(available_slots, list):
                    available_slots = []
                result["available_slots"] = available_slots
                result["available_slot_count"] = len(available_slots)
                if requested_time:
                    result["requested_time"] = _normalize_time(requested_time)
                    result["requested_time_available"] = _requested_time_is_available(
                        normalized_date,
                        requested_time,
                        duration_minutes,
                        available_slots,
                    )
                    result["available"] = bool(result["requested_time_available"])
                else:
                    result["requested_time_available"] = False
                    result["available"] = bool(available_slots)
                return PluginResult(success=True, output=result)

            elif action == "book_appointment":
                from zoneinfo import ZoneInfo as _ZI

                date = str(params.get("date", ""))
                time_str = str(params.get("time") or "")
                duration = int(params.get("duration_minutes", 30))
                purpose = str(params.get("purpose", params.get("summary", "Appointment")))

                logger.info(f"book_appointment params: date={date!r}, time={time_str!r}, duration={duration}, purpose={purpose!r}")

                date = date.strip().strip("'\"")
                time_str = time_str.strip().strip("'\"")

                time_match = re.match(r'^(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?$', time_str)
                if time_match:
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2) or 0)
                    ampm = (time_match.group(3) or "").upper()
                    if ampm == "PM" and hour < 12:
                        hour += 12
                    elif ampm == "AM" and hour == 12:
                        hour = 0
                    time_str = f"{hour:02d}:{minute:02d}"
                else:
                    time_match2 = re.search(r'(\d{1,2}):(\d{2})', time_str)
                    if time_match2:
                        time_str = f"{int(time_match2.group(1)):02d}:{int(time_match2.group(2)):02d}"
                    else:
                        err = f"Invalid appointment time: {time_str!r}"
                        logger.error(f"book_appointment: {err}")
                        return PluginResult(success=False, error=err)

                tz_name = agent_tz or integration.config.get("timezone") or "Asia/Karachi"
                try:
                    agent_tz_obj = _ZI(tz_name)
                except Exception:
                    agent_tz_obj = _ZI("Asia/Karachi")

                try:
                    start_dt = datetime.strptime(f"{date} {time_str}", "%Y-%m-%d %H:%M")
                    start_dt = start_dt.replace(tzinfo=agent_tz_obj)
                except ValueError as e:
                    logger.error(f"book_appointment: failed to parse date={date!r} time={time_str!r}: {e}")
                    return PluginResult(success=False, error=f"Invalid date/time format: date={date}, time={time_str}")

                end_dt = start_dt + timedelta(minutes=duration)
                start_iso = start_dt.isoformat()
                end_iso = end_dt.isoformat()

                logger.info(f"book_appointment: start_iso={start_iso}, end_iso={end_iso}, tz={tz_name}")

                try:
                    avail = await client.check_availability(date=date, duration_minutes=duration)
                    busy = avail.get("busy_slots", [])
                    for slot in busy:
                        s = datetime.fromisoformat(slot["start"].replace("Z", "+00:00"))
                        e = datetime.fromisoformat(slot["end"].replace("Z", "+00:00"))
                        if start_dt < e and end_dt > s:
                            return PluginResult(success=False, error=f"Time conflict: {slot.get('summary', 'Busy')}", output={"success": False, "error": f"Time conflict: {slot.get('summary', 'Busy')}", "date": date, "time": time_str})
                except Exception as e:
                    err = f"Availability check failed; appointment was not created: {e}"
                    logger.error(f"book_appointment: {err}")
                    return PluginResult(success=False, error=err)

                result = await client.create_event(
                    summary=purpose, start=start_iso, end=end_iso,
                    description=params.get(
                        "description",
                        f"Booked via voice agent. Purpose: {purpose}",
                    ),
                    location=params.get("location", ""),
                    attendees=params.get("attendees"),
                )
                if isinstance(result, dict) and result.get("success") is False:
                    return PluginResult(
                        success=False,
                        error=str(result.get("error") or "Google Calendar appointment creation failed"),
                    )
                output = dict(result) if isinstance(result, dict) else {"output": result}
                output["event_created"] = True
                return PluginResult(success=True, output=output)

            else:
                return PluginResult(success=False, error=f"Unknown calendar action: {action}")
        except Exception as e:
            logger.error(f"Calendar action {action} failed: {e}")
            return PluginResult(success=False, error=str(e))
