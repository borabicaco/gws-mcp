from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

import pytest

from gws_mcp.services import calendar


@pytest.fixture
def service():
    return MagicMock()


def events_list(service):
    return service.events.return_value.list


def test_parse_time_date_and_end_of_day():
    start = dt.datetime.fromisoformat(calendar.parse_time("2026-10-14"))
    end = dt.datetime.fromisoformat(calendar.parse_time("2026-10-14", end_of_day=True))
    assert (start.hour, start.minute) == (0, 0) and start.tzinfo is not None
    assert (end.hour, end.minute) == (23, 59)


def test_parse_time_keeps_explicit_offset():
    assert calendar.parse_time("2026-10-14T09:00:00Z") == "2026-10-14T09:00:00+00:00"
    assert calendar.parse_time("2026-10-14T09:00:00+03:00") == "2026-10-14T09:00:00+03:00"


def test_parse_time_rejects_garbage():
    with pytest.raises(calendar.CalendarError, match="Invalid date"):
        calendar.parse_time("next tuesday")


def test_list_events_defaults_to_next_seven_days(service):
    events_list(service).return_value.execute.return_value = {"items": []}
    calendar.list_events(service)
    kwargs = events_list(service).call_args.kwargs
    span = dt.datetime.fromisoformat(kwargs["timeMax"]) - dt.datetime.fromisoformat(
        kwargs["timeMin"]
    )
    assert span == dt.timedelta(days=7)
    assert kwargs["singleEvents"] is True and kwargs["orderBy"] == "startTime"
    assert kwargs["calendarId"] == "primary"


def test_list_events_maps_fields(service):
    events_list(service).return_value.execute.return_value = {
        "items": [
            {
                "id": "e1",
                "summary": "Standup",
                "start": {"dateTime": "2026-10-14T09:00:00+03:00"},
                "end": {"dateTime": "2026-10-14T09:15:00+03:00"},
                "attendees": [{}, {}],
                "organizer": {"email": "boss@x.com"},
                "htmlLink": "https://cal/e1",
            },
            {
                "id": "e2",
                "summary": "Holiday",
                "start": {"date": "2026-10-29"},
                "end": {"date": "2026-10-30"},
            },
        ]
    }
    result = calendar.list_events(service, time_min="2026-10-14", time_max="2026-10-31")
    assert result[0]["attendee_count"] == 2 and result[0]["organizer"] == "boss@x.com"
    assert result[1]["all_day"] is True and result[1]["start"] == "2026-10-29"


def test_list_events_rejects_inverted_range(service):
    with pytest.raises(calendar.CalendarError, match="after"):
        calendar.list_events(service, time_min="2026-10-14", time_max="2026-10-01")


def test_search_events_passes_query_and_wide_window(service):
    events_list(service).return_value.execute.return_value = {"items": []}
    calendar.search_events(service, "budget review")
    kwargs = events_list(service).call_args.kwargs
    assert kwargs["q"] == "budget review"
    span = dt.datetime.fromisoformat(kwargs["timeMax"]) - dt.datetime.fromisoformat(
        kwargs["timeMin"]
    )
    assert span > dt.timedelta(days=700)


def test_get_event_details(service):
    service.events.return_value.get.return_value.execute.return_value = {
        "id": "e1",
        "summary": "Review",
        "description": "Agenda",
        "start": {"dateTime": "2026-10-14T09:00:00Z"},
        "end": {"dateTime": "2026-10-14T10:00:00Z"},
        "attendees": [{"email": "a@x.com", "responseStatus": "accepted", "organizer": True}],
        "hangoutLink": "https://meet/abc",
    }
    result = calendar.get_event(service, "e1")
    service.events.return_value.get.assert_called_once_with(calendarId="primary", eventId="e1")
    assert result["description"] == "Agenda" and result["meet_link"] == "https://meet/abc"
    assert result["attendees"][0] == {
        "email": "a@x.com",
        "name": None,
        "response": "accepted",
        "organizer": True,
    }


def test_list_calendars(service):
    service.calendarList.return_value.list.return_value.execute.return_value = {
        "items": [
            {"id": "primary@x.com", "summary": "Me", "primary": True, "accessRole": "owner"},
            {"id": "team@x.com", "summary": "Team", "summaryOverride": "My team"},
        ]
    }
    result = calendar.list_calendars(service)
    assert result[0]["primary"] is True and result[1]["summary"] == "My team"
