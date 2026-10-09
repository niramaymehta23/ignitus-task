from datetime import UTC, datetime

import pytest

from goal_agent.catalog import Catalog
from goal_agent.config import ROOT, Settings

NOW = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)


@pytest.fixture
def catalog():
    return Catalog(ROOT / "catalog.json")


@pytest.fixture
def settings():
    return Settings(model_timeout=5, calendar_timeout=1, calendar_request_timeout=0.5)


@pytest.fixture
def plan():
    return {
        "disposition": "ready",
        "goal": "Meet important deadlines more consistently",
        "summary": "Identify causes of missed deadlines and prioritize your commitments.",
        "steps": [
            {
                "action": "Review last week's calendar and note what displaced important work.",
                "why": "Identifying recurring interruptions gives you a specific change to try.",
                "resources": [
                    {
                        "resource_id": "goal-110",
                        "why_this_resource": "The audit helps identify where time goes.",
                    }
                ],
            },
            {
                "action": "Rank current commitments by impact, deadline, and dependencies.",
                "why": "Choose what to do first and which commitments need renegotiation.",
                "resources": [
                    {
                        "resource_id": "goal-109",
                        "why_this_resource": "The worksheet compares competing commitments.",
                    }
                ],
            },
        ],
        "clarification": None,
        "check_in": {
            "intent": "not_requested",
            "evidence": None,
            "local_datetime": None,
            "timezone": None,
            "clarification": None,
            "assumptions": [],
        },
    }
