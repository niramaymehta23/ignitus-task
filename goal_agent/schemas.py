from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=800)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=4000)


class Resource(StrictModel):
    id: Text
    title: Text
    type: Literal["video", "exercise", "reading"]
    description: str = Field(min_length=1, max_length=2000)


class ResourceChoice(StrictModel):
    resource_id: Text
    why_this_resource: Text


class StepDraft(StrictModel):
    action: Text
    why: Text
    resources: list[ResourceChoice] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def unique_resources(self) -> "StepDraft":
        ids = [choice.resource_id for choice in self.resources]
        if len(set(ids)) != len(ids):
            raise ValueError("Do not repeat a resource within a step")
        return self


class CheckInDraft(StrictModel):
    intent: Literal["not_requested", "requested"]
    evidence: str | None = Field(max_length=4000)
    local_datetime: str | None = Field(
        max_length=40,
        description="Local wall time as YYYY-MM-DDTHH:MM:SS, without an offset; null if unclear",
    )
    timezone: str | None = Field(
        max_length=100, description="IANA timezone, or UTC; null to use the configured default"
    )
    clarification: str | None = Field(max_length=800)
    assumptions: list[Text] = Field(max_length=5)


class GoalDraft(StrictModel):
    disposition: Literal["ready", "needs_clarification", "out_of_scope"]
    goal: Text | None
    summary: Text
    steps: list[StepDraft] = Field(max_length=5)
    clarification: Text | None
    check_in: CheckInDraft

    @model_validator(mode="after")
    def consistent_plan(self) -> "GoalDraft":
        if self.disposition == "ready":
            if not self.goal or not self.steps or self.clarification:
                raise ValueError("A ready plan needs a goal, 1-5 steps, and no goal clarification")
        elif self.steps or self.goal:
            raise ValueError("An unclear or out-of-scope message must not invent a goal or steps")
        if self.disposition == "needs_clarification" and not self.clarification:
            raise ValueError("An unclear goal requires a clarification question")
        return self


class RecommendedResource(Resource):
    why_this_resource: Text


class GoalStep(StrictModel):
    order: int = Field(ge=1, le=5)
    action: Text
    why: Text
    resources: list[RecommendedResource]


class CalendarOutcome(StrictModel):
    status: Literal[
        "not_requested", "scheduled", "needs_clarification", "failed", "unknown", "skipped"
    ]
    message: str
    event_id: str | None = None
    timestamp: str | None = None
    timezone: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    attempts: int = Field(default=0, ge=0, le=2)


class GoalResponse(StrictModel):
    status: Literal["completed", "partial", "needs_clarification", "out_of_scope"]
    goal: str | None
    summary: str
    steps: list[GoalStep]
    calendar: CalendarOutcome
    clarification: str | None = None
    model: str
    reference_time: str


class ErrorDetail(StrictModel):
    code: str
    message: str


class ErrorResponse(StrictModel):
    error: ErrorDetail
