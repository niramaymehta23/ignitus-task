from datetime import UTC, datetime

import pytest

from goal_agent.schemas import CheckInDraft
from goal_agent.service import resolve_check_in
from tests.conftest import NOW

MESSAGE = "I miss deadlines. Check in next Friday morning."


def request(**changes):
    values = {
        "intent": "requested",
        "evidence": "Check in next Friday morning.",
        "local_datetime": "2026-10-16T09:00:00",
        "timezone": None,
        "clarification": None,
        "assumptions": ["Morning means 09:00."],
    }
    return CheckInDraft(**(values | changes))


def test_london_summer_time_converted_to_utc():
    result = resolve_check_in(request(), MESSAGE, NOW, "Europe/London")
    assert result.timestamp == "2026-10-16T08:00:00Z"
    assert result.status != "scheduled"
    assert result.attempts == 0
    assert result.timezone == "Europe/London"


def test_explicit_timezone_is_respected():
    result = resolve_check_in(request(timezone="America/New_York"), MESSAGE, NOW, "Europe/London")
    assert result.timestamp == "2026-10-16T13:00:00Z"


@pytest.mark.parametrize(
    "changes",
    [
        {"evidence": "a request that does not exist"},
        {"evidence": None},
        {"local_datetime": None},
        {"local_datetime": "2026-02-30T09:00:00"},
        {"local_datetime": "2026-10-16T09:00:00Z"},
        {"local_datetime": "2026-10-16T09:00"},
        {"local_datetime": "2026-10-02T09:00:00"},
        {"timezone": "EST"},
        {"timezone": "Invalid/Nowhere"},
        {"clarification": "Which timezone do you mean?"},
    ],
)
def test_invalid_or_unclear_scheduling_never_produces_a_timestamp(changes):
    result = resolve_check_in(request(**changes), MESSAGE, NOW, "Europe/London")
    assert result.status == "needs_clarification"
    assert result.timestamp is None


@pytest.mark.parametrize("local_time", ["2026-03-29T01:30:00", "2026-10-25T01:30:00"])
def test_daylight_saving_gap_and_fold_need_clarification(local_time):
    before = datetime(2026, 1, 1, tzinfo=UTC)
    result = resolve_check_in(request(local_datetime=local_time), MESSAGE, before, "Europe/London")
    assert result.status == "needs_clarification"
    assert result.timestamp is None


def test_no_request_overrides_spurious_time_fields():
    result = resolve_check_in(request(intent="not_requested"), MESSAGE, NOW, "Europe/London")
    assert result.status == "not_requested"
    assert result.timestamp is None
