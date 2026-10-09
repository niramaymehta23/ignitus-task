import re
from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from goal_agent.calendar import CalendarClient
from goal_agent.catalog import Catalog
from goal_agent.config import Settings
from goal_agent.gemini import GeminiPlanner
from goal_agent.schemas import CalendarOutcome, CheckInDraft, GoalResponse


def utc_now() -> datetime:
    return datetime.now(UTC)


def resolve_check_in(
    check_in: CheckInDraft, message: str, now: datetime, default_timezone: str
) -> CalendarOutcome:
    if check_in.intent == "not_requested":
        return CalendarOutcome(status="not_requested", message="No check-in was requested.")
    timezone = check_in.timezone or default_timezone
    assumptions = list(check_in.assumptions)
    if not check_in.timezone:
        assumptions.append(f"Using the configured timezone: {default_timezone}.")

    def clarify(question: str) -> CalendarOutcome:
        return CalendarOutcome(
            status="needs_clarification",
            message=question,
            timezone=timezone,
            assumptions=assumptions,
        )

    if not check_in.evidence or check_in.evidence not in message:
        return clarify("Would you like a goal progress check-in? Please specify a date and time.")
    if check_in.clarification or not check_in.local_datetime:
        return clarify(check_in.clarification or "What date and time should the check-in be?")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", check_in.local_datetime):
        return clarify("Please specify a valid date and time for the check-in.")
    try:
        if timezone != "UTC" and "/" not in timezone:
            return clarify("Please specify a city or IANA timezone, such as Europe/London.")
        zone = ZoneInfo(timezone)
        local = datetime.fromisoformat(check_in.local_datetime)
    except (ValueError, ZoneInfoNotFoundError):
        return clarify("Please specify a valid date, time, and timezone for the check-in.")

    instants = {
        local.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        for fold in (0, 1)
        if local.replace(tzinfo=zone, fold=fold)
        .astimezone(UTC)
        .astimezone(zone)
        .replace(tzinfo=None)
        == local
    }
    if not instants:
        return clarify(
            "That local time does not exist because the clocks change. Choose another time."
        )
    if len(instants) > 1:
        return clarify(
            "That local time occurs twice because the clocks change. Choose another time."
        )
    instant = instants.pop()
    if instant <= now:
        return clarify(
            "That check-in time has already passed. What future date and time should I use?"
        )
    return CalendarOutcome(
        status="skipped",
        message="Check-in time validated; scheduling has not yet been attempted.",
        timestamp=instant.isoformat().replace("+00:00", "Z"),
        timezone=timezone,
        assumptions=assumptions,
    )


class GoalService:
    def __init__(
        self,
        planner: GeminiPlanner,
        calendar: CalendarClient,
        catalog: Catalog,
        settings: Settings,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.planner = planner
        self.calendar = calendar
        self.catalog = catalog
        self.settings = settings
        self.clock = clock

    async def generate(self, message: str) -> GoalResponse:
        reference_time = self.clock()
        draft = await self.planner.generate(message, reference_time)
        steps = self.catalog.ground_steps(draft)
        if draft.disposition != "ready":
            calendar = CalendarOutcome(
                status="skipped",
                message="No event was created because the goal needs clarification "
                "or is outside the available coaching scope.",
            )
            status = draft.disposition
        else:
            calendar = resolve_check_in(
                draft.check_in, message, self.clock(), self.settings.timezone
            )
            if calendar.timestamp is not None:
                scheduled = await self.calendar.schedule(calendar.timestamp)
                calendar = scheduled.model_copy(
                    update={"timezone": calendar.timezone, "assumptions": calendar.assumptions}
                )
            status = "completed" if calendar.status in {"not_requested", "scheduled"} else "partial"
        return GoalResponse(
            status=status,
            goal=draft.goal,
            summary=draft.summary,
            steps=steps,
            calendar=calendar,
            clarification=draft.clarification,
            model=self.settings.model,
            reference_time=reference_time.isoformat().replace("+00:00", "Z"),
        )
