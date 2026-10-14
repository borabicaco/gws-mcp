"""Calendar write operations: create and update events.

Never sends invitation or update emails (sendUpdates="none"). Deleting and
cancelling are deliberately absent: there is no way to set an event's status.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from gws_mcp.services.calendar import CalendarError, parse_time

SEND_UPDATES = "none"


def _is_date(value: str) -> bool:
    return len(value) == 10


def _times(start: str, end: str | None) -> tuple[dict[str, str], dict[str, str]]:
    if _is_date(start):
        start_day = dt.date.fromisoformat(start)
        # All-day events: the end date is exclusive.
        end_day = dt.date.fromisoformat(end) if end else start_day
        if end_day <= start_day:
            end_day = start_day + dt.timedelta(days=1)
        return {"date": start_day.isoformat()}, {"date": end_day.isoformat()}
    if not end:
        raise CalendarError("end is required for timed events")
    start_rfc, end_rfc = parse_time(start), parse_time(end)
    if dt.datetime.fromisoformat(end_rfc) <= dt.datetime.fromisoformat(start_rfc):
        raise CalendarError("end must be after start")
    return {"dateTime": start_rfc}, {"dateTime": end_rfc}


def _event_result(event: dict[str, Any]) -> dict[str, Any]:
    start, end = event.get("start", {}), event.get("end", {})
    return {
        "id": event.get("id"),
        "summary": event.get("summary"),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "link": event.get("htmlLink"),
        "note": "No invitation emails were sent.",
    }


def create_event(
    service: Any,
    summary: str,
    start: str,
    end: str | None = None,
    calendar_id: str = "primary",
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
) -> dict[str, Any]:
    start_field, end_field = _times(start, end)
    body: dict[str, Any] = {"summary": summary, "start": start_field, "end": end_field}
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    event = (
        service.events()
        .insert(calendarId=calendar_id, body=body, sendUpdates=SEND_UPDATES)
        .execute()
    )
    return _event_result(event)


def update_event(
    service: Any,
    event_id: str,
    calendar_id: str = "primary",
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
) -> dict[str, Any]:
    """Patch only the given fields. ``attendees`` replaces the whole attendee list."""
    body: dict[str, Any] = {}
    if summary is not None:
        body["summary"] = summary
    if description is not None:
        body["description"] = description
    if location is not None:
        body["location"] = location
    if attendees is not None:
        body["attendees"] = [{"email": a} for a in attendees]
    if start is not None or end is not None:
        if start is None or end is None:
            raise CalendarError("pass both start and end to change the time")
        body["start"], body["end"] = _times(start, end)
    if not body:
        raise CalendarError("Nothing to update")
    event = (
        service.events()
        .patch(calendarId=calendar_id, eventId=event_id, body=body, sendUpdates=SEND_UPDATES)
        .execute()
    )
    return _event_result(event)
