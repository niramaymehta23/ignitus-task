# Ignitus Goal Breakdown Agent

An asynchronous FastAPI endpoint that turns a workplace message into an ordered action plan,
selects resources from `catalog.json`, and optionally schedules a check-in.

## Setup

Python 3.11 or 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Set `GEMINI_API_KEY` in `.env`, then run:

```bash
.venv/bin/uvicorn main:app --port 8000 --reload
```

Interactive documentation: <http://localhost:8000/docs>.
Restart after changing `.env`; environment variables take precedence.
The default model is `gemini-3.8-flash`, configurable through `GEMINI_MODEL`.
The model must support Interactions and structured output. Without a key, generation returns
503 with `model_not_configured`. Keep `.env` out of Git.

## API

```bash
curl -s http://localhost:8000/generate_goal_track \
  -H 'Content-Type: application/json' \
  -d '{"message":"I keep missing deadlines."}'
```

`message` must be nonblank and at most 4,000 characters. Extra input fields are rejected.
Add a scheduling request to the message to request a check-in.

Illustrative response; this is not a live model result:

```json
{
  "status": "completed",
  "goal": "Meet important deadlines more consistently",
  "summary": "Identify causes of missed deadlines and adjust your working routine.",
  "steps": [
    {
      "order": 1,
      "action": "Review last week's calendar and note what displaced important work.",
      "why": "Identify one recurring pattern to change.",
      "resources": [
        {
          "id": "goal-110",
          "title": "Personal Productivity Audit",
          "type": "exercise",
          "description": "Review a recent working week using your calendar and a simple activity log. Identify patterns in meetings, interruptions, rework, and focused work, then choose one change to try. Useful when you regularly run out of time but cannot explain where your effort is going.",
          "why_this_resource": "The audit helps identify where time goes."
        }
      ]
    }
  ],
  "calendar": {
    "status": "not_requested",
    "message": "No check-in was requested.",
    "event_id": null,
    "timestamp": null,
    "timezone": null,
    "assumptions": [],
    "attempts": 0
  },
  "clarification": null,
  "model": "gemini-3.8-flash",
  "reference_time": "2026-10-09T10:00:00Z"
}
```

| Plan status | Meaning |
| --- | --- |
| `completed` | Valid plan; check-in not requested or scheduling confirmed |
| `partial` | Valid plan; calendar needs clarification, failed, or is uncertain |
| `needs_clarification` | Insufficient information for a useful goal |
| `out_of_scope` | Request unsupported by the workplace coaching catalog |

Calendar statuses: `not_requested`, `scheduled`, `needs_clarification`, `failed`, `unknown`,
and `skipped`. Success requires an external 2xx response with a nonempty string `event_id`.
An `unknown` outcome may mean an event exists; check before retrying to avoid duplicates.

Invalid input returns 422. Model failures return `{"error":{"code":"...","message":"..."}}`:
503 for unavailable configuration/access/quota, 502 for invalid output after repair, and
504 for exceeding the model time budget. Calendar failure preserves the plan as HTTP 200
with `status: partial`.

## Design

- The full 30-resource catalog is provided to Gemini in one structured generation. A retrieval
  service is unnecessary for this dataset.
- Resource IDs are constrained by JSON Schema and validated locally. Titles, types, and
  descriptions come from the catalog. Actions and explanations still need semantic review.
- Invalid output gets one repair attempt. Calendar calls occur only after plan validation.
- The official `google-genai` SDK uses asynchronous Interactions with `store=False`.
  Clients are shared for the application lifespan and closed on shutdown.
- Model requests have a 35-second total budget including repair and retries. The pinned SDK
  allows one transport retry per SDK call, with at most two SDK calls.
- Calendar requests have a 15-second total budget and a 6-second per-request timeout.
  An explicit 503 is retried once with jittered backoff. Timeouts, missing event IDs, and other
  uncertain server responses are not retried automatically. Retrying 503 assumes the supplied
  simulated service has not created an event when reporting that failure.
- Scheduling intent must include an exact quote from the user's message. The application
  validates that evidence and the datetime. Intent extraction remains model-driven;
  matching evidence alone does not prove the user's meaning.

Defaults are configurable in `.env.example`. `GOAL_TIMEZONE` defaults to `Europe/London`;
an explicit user timezone overrides it. Dates are resolved against the request's current time.
`next Friday` means the strictly next Friday after the local reference date. Morning, afternoon,
and evening mean 09:00, 14:00, and 18:00, with assumptions reported in the response.
Missing times, invalid or past dates, unclear timezones, and daylight-saving gaps or repeated
hours require clarification. UTC conversion uses Python's `zoneinfo`.

## Validation

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Observed offline results: **65 tests passed**; lint, formatting, and dependency checks passed.
Tests cover input validation, catalog grounding, repair, partial results, calendar failures
and retries, SDK serialization/error handling, concurrency, and timezone/DST conversion.
They use a fixed clock and mocked network responses, requiring no key or internet.
Starlette's test client emits one HTTPX deprecation warning; the tests still pass.

Run live Gemini evaluation with calendar calls disabled:

```bash
.venv/bin/python -m scripts.evaluate
```

Ten cases cover resource relevance, vague/unsupported goals, scheduling intent, relative dates,
and attempted catalog overrides. Full responses go to ignored `evaluation-results.json`.
Review action quality and explanation faithfulness manually; automated checks are review aids.
Use `--live-calendar` only to intentionally create test events in the supplied mock service.
Live Gemini quality and calendar POST behavior remain unverified in the recorded initial build.

## Scope and submission notes

The initial build took approximately 30 minutes including setup, tests, and documentation.
Include subsequent cleanup, evaluation, and changes in the final time estimate.
Direct dependencies are pinned; transitive dependencies are not fully locked.
There is no UI, database, authentication, deployment, recurring scheduling, or request
deduplication. Clarification is stateless: later requests must include the relevant context.
Repeating a successful scheduling request can create another event.

Next improvements should follow live evaluation findings: improve intent/date extraction,
refine resource explanations, and add idempotency if supported by the calendar service.

Codex was used to inspect the brief and repository, check Gemini docs, implement the backend,
write and run tests, and prepare documentation.

References: [assessment](https://github.com/ignitus-app/ai-engineer-assessment),
[Interactions](https://ai.google.dev/gemini-api/docs/interactions-overview),
[structured output](https://ai.google.dev/gemini-api/docs/structured-output).
Gemini documentation was checked on 9 October 2026.
