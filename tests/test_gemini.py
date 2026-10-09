import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from google import genai
from google.genai import types

from goal_agent.errors import DependencyError
from goal_agent.gemini import GeminiPlanner
from tests.conftest import NOW


def response(plan):
    return SimpleNamespace(status="completed", output_text=json.dumps(plan))


def fake_client(*responses):
    return SimpleNamespace(interactions=SimpleNamespace(create=AsyncMock(side_effect=responses)))


async def test_invalid_resource_is_repaired_once(catalog, settings, plan):
    invalid = copy.deepcopy(plan)
    invalid["steps"][0]["resources"][0]["resource_id"] = "invented-resource"
    client = fake_client(response(invalid), response(plan))
    result = await GeminiPlanner(client, settings, catalog).generate("I miss deadlines.", NOW)
    assert result.steps[0].resources[0].resource_id == "goal-110"
    assert client.interactions.create.await_count == 2
    first = client.interactions.create.call_args_list[0].kwargs
    assert first["store"] is False
    assert json.loads(first["input"])["reference_time"] == "2026-10-09T11:00:00+01:00"
    schema = first["response_format"]["schema"]
    assert len(schema["$defs"]["ResourceChoice"]["properties"]["resource_id"]["enum"]) == 30


@pytest.mark.parametrize("bad_output", ["not json", "{}", '{"goal": "invented"}'])
async def test_invalid_json_fails_after_two_calls(catalog, settings, bad_output):
    result = SimpleNamespace(status="completed", output_text=bad_output)
    client = fake_client(result, result)
    with pytest.raises(DependencyError) as error:
        await GeminiPlanner(client, settings, catalog).generate("I miss deadlines.", NOW)
    assert error.value.code == "invalid_model_output"
    assert error.value.status_code == 502
    assert client.interactions.create.await_count == 2


async def test_total_model_budget_cancels_slow_call(catalog, settings):
    async def slow(**kwargs):
        await asyncio.sleep(1)

    settings.model_timeout = 0.01
    client = SimpleNamespace(interactions=SimpleNamespace(create=slow))
    with pytest.raises(DependencyError) as error:
        await GeminiPlanner(client, settings, catalog).generate("I miss deadlines.", NOW)
    assert error.value.code == "model_timeout"
    assert error.value.status_code == 504


async def test_slow_model_does_not_block_another_request(catalog, settings, plan):
    entered, release = asyncio.Event(), asyncio.Event()

    async def generate(**kwargs):
        if json.loads(kwargs["input"])["user_message"] == "slow":
            entered.set()
            await release.wait()
        return response(plan)

    client = SimpleNamespace(interactions=SimpleNamespace(create=generate))
    planner = GeminiPlanner(client, settings, catalog)
    slow = asyncio.create_task(planner.generate("slow", NOW))
    await entered.wait()
    try:
        fast = await asyncio.wait_for(planner.generate("fast", NOW), timeout=0.1)
        assert fast.goal == plan["goal"]
        assert not slow.done()
    finally:
        release.set()
        await slow


@pytest.mark.parametrize("http_status", [200, 400, 401, 403, 404, 429, 503])
async def test_actual_sdk_wire_format_and_errors(catalog, settings, plan, http_status):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "POST"
        assert request.url.path == "/v1beta/interactions"
        body = json.loads(request.content)
        assert body["model"] == settings.model
        assert body["store"] is False
        assert body["response_format"]["mime_type"] == "application/json"
        assert body["response_format"]["schema"]["type"] == "object"
        if http_status == 200:
            return httpx.Response(
                200,
                json={
                    "id": "mock-interaction",
                    "status": "completed",
                    "steps": [
                        {
                            "type": "model_output",
                            "content": [{"type": "text", "text": json.dumps(plan)}],
                        }
                    ],
                },
            )
        return httpx.Response(
            http_status,
            json={
                "error": {"code": http_status, "message": "secret provider body must not escape"}
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        sdk = genai.Client(
            api_key="test-key",
            http_options=types.HttpOptions(
                httpx_async_client=http,
                retry_options=types.HttpRetryOptions(attempts=1, initial_delay=0.1, max_delay=0.2),
            ),
        )
        try:
            planner = GeminiPlanner(sdk.aio, settings, catalog)
            if http_status == 200:
                draft = await planner.generate("I miss deadlines.", NOW)
                assert draft.goal == plan["goal"]
            else:
                with pytest.raises(DependencyError) as error:
                    await planner.generate("I miss deadlines.", NOW)
                assert "secret" not in error.value.message
                expected = (
                    "model_access_denied"
                    if http_status in {401, 403}
                    else ("model_rate_limited" if http_status == 429 else "model_unavailable")
                )
                assert error.value.code == expected
            assert len(calls) == (2 if http_status in {429, 503} else 1)
        finally:
            await sdk.aio.aclose()
            sdk.close()


async def test_actual_sdk_timeout_normalized(catalog, settings):
    def handler(request):
        raise httpx.ReadTimeout("secret details", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        sdk = genai.Client(
            api_key="test-key",
            http_options=types.HttpOptions(
                httpx_async_client=http,
                retry_options=types.HttpRetryOptions(attempts=0),
            ),
        )
        try:
            with pytest.raises(DependencyError) as error:
                await GeminiPlanner(sdk.aio, settings, catalog).generate("I miss deadlines.", NOW)
            assert error.value.code == "model_timeout"
            assert error.value.status_code == 504
            assert "secret" not in error.value.message
        finally:
            await sdk.aio.aclose()
            sdk.close()
