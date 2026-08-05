"""Tests for timeline related calendar events."""

from collections.abc import Awaitable, Callable, Generator
import itertools
import json
import sys
import textwrap
import pathlib
from typing import cast

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient
import pytest
from syrupy import SnapshotAssertion

from ical.exceptions import CalendarFetchError, CalendarParseError
from ical.calendar_stream import CalendarStream, IcsCalendarStream
from ical.store import TodoStore

MAX_ITERATIONS = 30
TESTDATA_PATH = pathlib.Path("tests/testdata/")
TESTDATA_FILES = list(TESTDATA_PATH.glob("*.ics"))
TESTDATA_IDS = [x.stem for x in TESTDATA_FILES]

ICS_CONTENT = textwrap.dedent(
    """\
    BEGIN:VCALENDAR
    PRODID:-//example//1.2.3
    VERSION:2.0
    BEGIN:VEVENT
    UID:1
    DTSTART:20220724T120000
    DTEND:20220724T130000
    SUMMARY:Example Event
    END:VEVENT
    END:VCALENDAR
    """
)


async def _ics_handler(request: web.Request) -> web.Response:
    """Fake server handler that returns a fixed ics payload."""
    return web.Response(text=ICS_CONTENT, content_type="text/calendar")


@pytest.fixture(name="ics_client")
async def mock_ics_client(
    aiohttp_client: Callable[[web.Application], Awaitable[TestClient]],
) -> TestClient:
    """Fixture that fakes a remote server serving an ics file (no real network)."""
    app = web.Application()
    app.router.add_get("/calendar.ics", _ics_handler)
    return await aiohttp_client(app)


def test_empty_ics(mock_prodid: Generator[None, None, None]) -> None:
    """Test serialization of an empty ics file."""
    calendar = IcsCalendarStream.calendar_from_ics("")
    ics = IcsCalendarStream.calendar_to_ics(calendar)
    assert ics == textwrap.dedent(
        """\
            BEGIN:VCALENDAR
            PRODID:-//example//1.2.3
            VERSION:2.0
            END:VCALENDAR"""
    )

    calendar.prodid = "-//example//1.2.4"
    ics = IcsCalendarStream.calendar_to_ics(calendar)
    assert ics == textwrap.dedent(
        """\
            BEGIN:VCALENDAR
            PRODID:-//example//1.2.4
            VERSION:2.0
            END:VCALENDAR"""
    )


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_parse(
    filename: pathlib.Path, snapshot: SnapshotAssertion, json_encoder: json.JSONEncoder
) -> None:
    """Fixture to read golden file and compare to golden output."""
    cal = CalendarStream.from_ics(filename.read_text(encoding="utf-8"))
    data = json.loads(cal.model_dump_json(exclude_unset=True, exclude_none=True))
    assert snapshot == data

    # Re-parse the data object to verify we get the original data values
    # back. This effectively confirms that all fields can be parsed from the
    # python native format in addition to rfc5545.
    cal_reparsed = CalendarStream.model_validate(data)
    data_reparsed = json.loads(
        cal_reparsed.model_dump_json(exclude_unset=True, exclude_none=True)
    )
    assert data_reparsed == data


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_serialize(filename: pathlib.Path, snapshot: SnapshotAssertion) -> None:
    """Fixture to read golden file and compare to golden output."""
    with filename.open() as f:
        cal = IcsCalendarStream.from_ics(f.read())
    assert cal.ics() == snapshot


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_timeline_iteration(filename: pathlib.Path) -> None:
    """Fixture to ensure all calendar events are valid and support iteration."""
    with filename.open() as f:
        cal = IcsCalendarStream.from_ics(f.read())
    for calendar in cal.calendars:
        # Iterate over the timeline to ensure events are valid. There is a max
        # to handle recurring events that may repeat forever.
        for event in itertools.islice(calendar.timeline, MAX_ITERATIONS):
            assert event is not None


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_todo_list_iteration(filename: pathlib.Path) -> None:
    """Fixture to read golden file and compare to golden output."""
    cal = CalendarStream.from_ics(filename.read_text(encoding="utf-8"))
    if not cal.calendars:
        return
    calendar = cal.calendars[0]
    tl = TodoStore(calendar).todo_list()
    for todo in itertools.islice(tl, MAX_ITERATIONS):
        assert todo is not None


@pytest.mark.parametrize(
    "content",
    [
        textwrap.dedent(
            """\
            invalid
            """
        ),
        textwrap.dedent(
            """\
            BEGIN:VCALENDAR
            VERSION:\x007
            END:VCALENDAR
            """
        ),
        textwrap.dedent(
            """\
            BEGIN:VCALENDAR
            PROD\uc27fID://example
            END:VCALENDAR
            """
        ),
        textwrap.dedent(
            """\
            BEGIN:VCALENDAR
            ATTENDEE;MEM\x007ER="mailto:DEV-GROUP@example.com":mailto:joecool@example.com
            END:VCALENDAR
            """
        ),
        textwrap.dedent(
            """\
            BEGIN:VCALENDAR
            ATTENDEE;MEMBER="mailto:DEV-GROUP\x00example.com":mailto:joecool@example.com
            END:VCALENDAR
            """
        ),
    ],
    ids=[
        "invalid",
        "control-char-value",
        "control-char-name",
        "control-param-name",
        "control-param-value",
    ],
)
def test_invalid_ics(content: str) -> None:
    """Test parsing failures for ics content.

    These are tested here so we can add escape sequences. Most other invalid
    encodings are tested in the yaml testdata/ files.
    """
    with pytest.raises(
        CalendarParseError,
        match="^Calendar contents are not valid ICS format, see the detailed_error for more information$",
    ):
        IcsCalendarStream.calendar_from_ics(content)


def test_component_failure() -> None:
    with pytest.raises(
        CalendarParseError,
        match="^Failed to parse calendar EVENT component: Value error, Unexpected dtstart value '2022-07-24 12:00:00' was datetime but dtend value '2022-07-24' was not datetime$",
    ):
        IcsCalendarStream.calendar_from_ics(
            textwrap.dedent(
                """\
                BEGIN:VCALENDAR
                PRODID:-//example//1.2.3
                VERSION:2.0
                BEGIN:VEVENT
                DTSTART:20220724T120000
                DTEND:20220724
                END:VEVENT
                END:VCALENDAR
            """
            )
        )


def test_multiple_calendars() -> None:
    with pytest.raises(CalendarParseError, match="more than one calendar"):
        IcsCalendarStream.calendar_from_ics(
            textwrap.dedent(
                """\
                BEGIN:VCALENDAR
                PRODID:-//example//1.2.3
                VERSION:2.0
                END:VCALENDAR
                BEGIN:VCALENDAR
                PRODID:-//example//1.2.3
                VERSION:2.0
                END:VCALENDAR
            """
            )
        )


async def test_from_url(ics_client: TestClient) -> None:
    """Test fetching and parsing an ics file over http, without a shared session.

    This exercises the code path where `from_url` creates and closes its own
    `aiohttp.ClientSession`. The "remote" server is a local, in-process
    aiohttp test server (no real network traffic).
    """
    url = str(ics_client.make_url("/calendar.ics"))
    stream = await CalendarStream.from_url(url)
    assert len(stream.calendars) == 1
    assert [event.summary for event in stream.calendars[0].events] == ["Example Event"]


async def test_from_url_with_shared_session(ics_client: TestClient) -> None:
    """Test fetching an ics file over http, reusing a caller-provided session."""
    stream = await CalendarStream.from_url(
        "/calendar.ics", session=cast(aiohttp.ClientSession, ics_client)
    )
    assert len(stream.calendars) == 1
    assert stream.calendars[0].events[0].summary == "Example Event"


async def test_calendar_from_url(ics_client: TestClient) -> None:
    """Test the async convenience method that returns a single calendar."""
    calendar = await IcsCalendarStream.calendar_from_url(
        "/calendar.ics", session=cast(aiohttp.ClientSession, ics_client)
    )
    assert calendar.events[0].summary == "Example Event"


async def test_from_url_http_error(
    aiohttp_client: Callable[[web.Application], Awaitable[TestClient]],
) -> None:
    """Test that a non-2xx response is surfaced as a CalendarFetchError."""

    async def not_found_handler(request: web.Request) -> web.Response:
        return web.Response(status=404)

    app = web.Application()
    app.router.add_get("/missing.ics", not_found_handler)
    client = await aiohttp_client(app)

    with pytest.raises(CalendarFetchError, match="Failed to fetch calendar"):
        await CalendarStream.from_url(
            "/missing.ics", session=cast(aiohttp.ClientSession, client)
        )


async def test_from_url_missing_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test the error raised when the optional `ical[async]` extra is missing."""
    monkeypatch.setitem(sys.modules, "aiohttp", None)

    with pytest.raises(ImportError, match=r"ical\[async\]"):
        await CalendarStream.from_url("https://example.com/calendar.ics")
