"""Read-only Google Calendar operations. ``service`` is a Calendar v3 resource."""

from __future__ import annotations

import datetime as dt
from typing import Any

MAX_RESULTS_CAP = 250
DEFAULT_WINDOW_DAYS = 7


class CalendarError(Exception):
    """An anticipated Calendar failure with a message safe to show the user."""


def parse_time(value: str, *, end_of_day: bool = False) -> str:
    """Accept '2026-10-14', '2026-10-14T09:00' or full RFC 3339; return RFC 3339.

    Naive values are interpreted in the computer's local time zone.
    """
    try:
        if len(value) == 10:
            day = dt.date.fromisoformat(value)
            moment = dt.datetime.combine(day, dt.time.max if end_of_day else dt.time.min)
        else:
            moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise CalendarError(f"Invalid date/time '{value}'; use YYYY-MM-DD or ISO 8601") from None
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.isoformat()


def _event_summary(event: dict[str, Any]) -> dict[str, Any]:
    start = event.get("start", {})
    end = event.get("end", {})
    return {
        "id": event.get("id"),
        "summary": event.get("summary", ""),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "all_day": "date" in start,
        "location": event.get("location", ""),
        "status": event.get("status"),
        "organizer": (event.get("organizer") or {}).get("email"),
        "attendee_count": len(event.get("attendees", [])),
        "link": event.get("htmlLink"),
    }


def list_calendars(service: Any) -> list[dict[str, Any]]:
    items = service.calendarList().list().execute().get("items", [])
    return [
        {
            "id": c["id"],
            "summary": c.get("summaryOverride") or c.get("summary", ""),
            "primary": bool(c.get("primary")),
            "access_role": c.get("accessRole"),
            "time_zone": c.get("timeZone"),
        }
        for c in items
    ]


def list_events(
    service: Any,
    calendar_id: str = "primary",
    time_min: str | None = None,
    time_max: str | None = None,
    query: str | None = None,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    now = dt.datetime.now().astimezone()
    start = parse_time(time_min) if time_min else now.isoformat()
    end = (
        parse_time(time_max, end_of_day=True)
        if time_max
        else (dt.datetime.fromisoformat(start) + dt.timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat()
    )
    if dt.datetime.fromisoformat(end) <= dt.datetime.fromisoformat(start):
        raise CalendarError("time_max must be after time_min")
    params: dict[str, Any] = {
        "calendarId": calendar_id,
        "timeMin": start,
        "timeMax": end,
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": max(1, min(max_results, MAX_RESULTS_CAP)),
    }
    if query:
        params["q"] = query
    items = service.events().list(**params).execute().get("items", [])
    return [_event_summary(e) for e in items]


def search_events(
    service: Any,
    query: str,
    calendar_id: str = "primary",
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Keyword search; defaults to one year back and one year ahead."""
    today = dt.date.today()
    return list_events(
        service,
        calendar_id=calendar_id,
        time_min=time_min or (today - dt.timedelta(days=365)).isoformat(),
        time_max=time_max or (today + dt.timedelta(days=365)).isoformat(),
        query=query,
        max_results=max_results,
    )


def get_event(service: Any, event_id: str, calendar_id: str = "primary") -> dict[str, Any]:
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    result = _event_summary(event)
    result.update(
        {
            "description": event.get("description", ""),
            "attendees": [
                {
                    "email": a.get("email"),
                    "name": a.get("displayName"),
                    "response": a.get("responseStatus"),
                    "organizer": bool(a.get("organizer")),
                }
                for a in event.get("attendees", [])
            ],
            "meet_link": event.get("hangoutLink"),
            "recurrence": event.get("recurrence", []),
            "recurring_event_id": event.get("recurringEventId"),
        }
    )
    return result
