import asyncio
import json

import httpx
import pytest

from goal_agent.calendar import CalendarClient
from goal_agent.config import CALENDAR_URL

TIMESTAMP = "2026-10-16T08:00:00Z"


async def test_calendar_success_checks_wire_request(settings):
    def handler(request):
        assert str(request.url) == CALENDAR_URL
        assert request.method == "POST"
        assert json.loads(request.content) == {
            "title": "Goal progress check-in",
            "timestamp": TIMESTAMP,
        }
        return httpx.Response(200, json={"event_id": "actual-event-123"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await CalendarClient(http, settings).schedule(TIMESTAMP)
    assert result.status == "scheduled"
    assert result.event_id == "actual-event-123"
    assert result.attempts == 1


@pytest.mark.parametrize("second_status", [200, 503])
async def test_only_one_retry_after_explicit_503(settings, second_status):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={"detail": "Unavailable"})
        return httpx.Response(second_status, json={"event_id": "after-retry"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await CalendarClient(http, settings).schedule(TIMESTAMP)
    assert len(calls) == 2
    assert result.attempts == 2
    assert result.status == ("scheduled" if second_status == 200 else "failed")


@pytest.mark.parametrize("payload", [{}, {"event_id": ""}, {"event_id": 123}, [], None])
async def test_success_without_valid_id_is_unknown_and_not_retried(settings, payload):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await CalendarClient(http, settings).schedule(TIMESTAMP)
    assert result.status == "unknown"
    assert result.event_id is None
    assert len(calls) == 1


@pytest.mark.parametrize("status", [400, 422, 429, 302, 500, 502, 504, 408])
async def test_other_failures_are_not_blindly_retried(settings, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"detail": "failure"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await CalendarClient(http, settings).schedule(TIMESTAMP)
    assert result.status == ("unknown" if status >= 500 or status == 408 else "failed")
    assert len(calls) == 1
    assert result.event_id is None


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError]
)
async def test_uncertain_transport_outcome_is_not_retried(settings, error):
    calls = []

    def handler(request):
        calls.append(request)
        raise error("interrupted", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await CalendarClient(http, settings).schedule(TIMESTAMP)
    assert result.status == "unknown"
    assert len(calls) == 1


async def test_connection_failure_reports_failed(settings):
    def handler(request):
        raise httpx.ConnectError("unreachable", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await CalendarClient(http, settings).schedule(TIMESTAMP)
    assert result.status == "failed"
    assert result.attempts == 1


async def test_total_calendar_budget_bounds_latency(settings):
    async def handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={"event_id": "too-late"})

    settings.calendar_timeout = 0.01
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await CalendarClient(http, settings).schedule(TIMESTAMP)
    assert result.status == "unknown"
    assert result.event_id is None
    assert result.attempts == 1
