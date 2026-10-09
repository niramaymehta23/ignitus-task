import asyncio
import logging
import random

import httpx

from goal_agent.config import CALENDAR_URL, Settings
from goal_agent.schemas import CalendarOutcome

logger = logging.getLogger(__name__)


class CalendarClient:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client = client
        self.settings = settings

    async def schedule(self, timestamp: str) -> CalendarOutcome:
        attempts = 0

        def outcome(status: str, message: str, event_id: str | None = None) -> CalendarOutcome:
            return CalendarOutcome(
                status=status,
                message=message,
                timestamp=timestamp,
                event_id=event_id,
                attempts=attempts,
            )

        try:
            async with asyncio.timeout(self.settings.calendar_timeout):
                for attempts in range(1, 3):
                    try:
                        response = await self.client.post(
                            CALENDAR_URL,
                            json={"title": "Goal progress check-in", "timestamp": timestamp},
                            timeout=self.settings.calendar_request_timeout,
                        )
                    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
                        return outcome("failed", "Could not connect to the calendar service.")
                    except httpx.RequestError:
                        return outcome(
                            "unknown",
                            "The calendar request was interrupted. An event may exist; "
                            "check before retrying to avoid a duplicate.",
                        )
                    logger.info("Calendar attempt=%s status=%s", attempts, response.status_code)
                    if response.status_code == 503:
                        if attempts == 1:
                            await asyncio.sleep(0.25 + random.uniform(0, 0.1))
                            continue
                        return outcome("failed", "The calendar service remained unavailable.")
                    if response.is_success:
                        try:
                            payload = response.json()
                        except ValueError:
                            payload = None
                        event_id = payload.get("event_id") if isinstance(payload, dict) else None
                        if isinstance(event_id, str) and event_id.strip():
                            return outcome(
                                "scheduled", "Check-in scheduled successfully.", event_id
                            )
                        return outcome(
                            "unknown",
                            "The calendar response did not contain a valid event_id. An event may "
                            "exist; check before retrying.",
                        )
                    if response.status_code >= 500 or response.status_code == 408:
                        return outcome(
                            "unknown",
                            "The calendar returned an unexpected server error. Scheduling "
                            "could not be confirmed; check before retrying.",
                        )
                    return outcome(
                        "failed", "The calendar service rejected the scheduling request."
                    )
        except TimeoutError:
            return outcome(
                "unknown",
                "The calendar time budget expired. An event may exist; check before retrying.",
            )
        return outcome("failed", "The calendar service remained unavailable.")
