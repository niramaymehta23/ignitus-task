from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from goal_agent.calendar import CalendarClient
from goal_agent.errors import DependencyError
from goal_agent.schemas import CalendarOutcome, GoalDraft
from goal_agent.service import GoalService
from main import create_app, get_service
from tests.conftest import NOW


def api(catalog, settings, plan, calendar_result=None):
    planner = AsyncMock()
    planner.generate.return_value = GoalDraft.model_validate(plan)
    calendar = AsyncMock(spec=CalendarClient)
    calendar.schedule.return_value = calendar_result
    service = GoalService(planner, calendar, catalog, settings, clock=lambda: NOW)
    app = create_app(settings)
    app.dependency_overrides[get_service] = lambda: service
    return TestClient(app), planner, calendar


def test_plan_grounded_in_catalog_without_calendar(catalog, settings, plan):
    client, planner, calendar = api(catalog, settings, plan)
    with client:
        response = client.post(
            "/generate_goal_track", json={"message": "I keep missing deadlines."}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert [step["order"] for step in body["steps"]] == [1, 2]
    for step in body["steps"]:
        for resource in step["resources"]:
            canonical = catalog.by_id[resource["id"]].model_dump()
            assert {key: resource[key] for key in canonical} == canonical
    assert body["calendar"]["status"] == "not_requested"
    calendar.schedule.assert_not_awaited()
    planner.generate.assert_awaited_once()


@pytest.mark.parametrize("calendar_status", ["scheduled", "failed", "unknown"])
def test_requested_check_in_returns_real_calendar_outcome(catalog, settings, plan, calendar_status):
    message = "I keep missing deadlines. Let's check in next Friday morning."
    plan["check_in"].update(
        intent="requested",
        evidence="Let's check in next Friday morning.",
        local_datetime="2026-10-16T09:00:00",
        assumptions=["Morning means 09:00 in Europe/London."],
    )
    calendar_result = CalendarOutcome(
        status=calendar_status,
        message="Calendar test result",
        event_id="event-from-service" if calendar_status == "scheduled" else None,
        timestamp="2026-10-16T08:00:00Z",
        attempts=1,
    )
    client, _, calendar = api(catalog, settings, plan, calendar_result)
    with client:
        response = client.post("/generate_goal_track", json={"message": message})
    body = response.json()
    assert body["status"] == ("completed" if calendar_status == "scheduled" else "partial")
    assert len(body["steps"]) == 2
    assert body["calendar"]["status"] == calendar_status
    assert body["calendar"]["event_id"] == calendar_result.event_id
    assert body["calendar"]["timezone"] == "Europe/London"
    calendar.schedule.assert_awaited_once_with("2026-10-16T08:00:00Z")


def test_unclear_calendar_time_keeps_plan_without_booking(catalog, settings, plan):
    message = "I keep missing deadlines. Check in sometime next week."
    plan["check_in"].update(
        intent="requested",
        evidence="Check in sometime next week.",
        clarification="Which day and time next week should I use?",
    )
    client, _, calendar = api(catalog, settings, plan)
    with client:
        body = client.post("/generate_goal_track", json={"message": message}).json()
    assert body["status"] == "partial"
    assert len(body["steps"]) == 2
    assert body["calendar"]["status"] == "needs_clarification"
    assert body["calendar"]["attempts"] == 0
    calendar.schedule.assert_not_awaited()


@pytest.mark.parametrize("disposition", ["needs_clarification", "out_of_scope"])
def test_unclear_or_unsupported_goal_does_not_book(catalog, settings, plan, disposition):
    plan.update(
        disposition=disposition,
        goal=None,
        steps=[],
        clarification="What workplace challenge would you like to work on?"
        if disposition == "needs_clarification"
        else None,
    )
    client, _, calendar = api(catalog, settings, plan)
    with client:
        body = client.post("/generate_goal_track", json={"message": "Help me."}).json()
    assert body["status"] == disposition
    assert body["steps"] == []
    assert body["calendar"]["status"] == "skipped"
    calendar.schedule.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": ""},
        {"message": "   "},
        {"message": "x" * 4001},
        {"message": 42},
        {"message": "Help me", "extra": True},
    ],
)
def test_invalid_request_rejected_before_model(catalog, settings, plan, payload):
    client, planner, calendar = api(catalog, settings, plan)
    with client:
        response = client.post("/generate_goal_track", json=payload)
    assert response.status_code == 422
    planner.generate.assert_not_awaited()
    calendar.schedule.assert_not_awaited()


def test_provider_error_has_safe_json_and_no_calendar(catalog, settings, plan):
    client, planner, calendar = api(catalog, settings, plan)
    planner.generate.side_effect = DependencyError("model_timeout", "Model timed out.", 504)
    with client:
        response = client.post("/generate_goal_track", json={"message": "I miss deadlines."})
    assert response.status_code == 504
    assert response.json() == {"error": {"code": "model_timeout", "message": "Model timed out."}}
    calendar.schedule.assert_not_awaited()


def test_app_starts_without_key_but_does_not_fake_a_plan(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/docs").status_code == 200
        response = client.post("/generate_goal_track", json={"message": "I miss deadlines."})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_not_configured"
