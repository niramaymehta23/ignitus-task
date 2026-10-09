import json
from pathlib import Path

from pydantic import TypeAdapter

from goal_agent.schemas import GoalDraft, GoalStep, RecommendedResource, Resource


class Catalog:
    def __init__(self, path: Path):
        self.resources = TypeAdapter(list[Resource]).validate_json(path.read_text(encoding="utf-8"))
        self.by_id = {resource.id: resource for resource in self.resources}
        if not self.resources or len(self.by_id) != len(self.resources):
            raise ValueError("The catalog must be nonempty and contain unique resource IDs")

    def prompt_json(self) -> str:
        return json.dumps(
            [resource.model_dump() for resource in self.resources], ensure_ascii=False
        )

    def validate_draft(self, draft: GoalDraft) -> None:
        for step in draft.steps:
            for choice in step.resources:
                if choice.resource_id not in self.by_id:
                    raise ValueError(f"Unknown catalog resource ID: {choice.resource_id}")

    def ground_steps(self, draft: GoalDraft) -> list[GoalStep]:
        self.validate_draft(draft)
        return [
            GoalStep(
                order=order,
                action=step.action,
                why=step.why,
                resources=[
                    RecommendedResource(
                        **self.by_id[choice.resource_id].model_dump(),
                        why_this_resource=choice.why_this_resource,
                    )
                    for choice in step.resources
                ],
            )
            for order, step in enumerate(draft.steps, start=1)
        ]

    def response_schema(self) -> dict:
        schema = GoalDraft.model_json_schema()
        schema["$defs"]["ResourceChoice"]["properties"]["resource_id"]["enum"] = list(self.by_id)
        return schema
