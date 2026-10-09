from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from google import genai
from google.genai import types

from goal_agent.calendar import CalendarClient
from goal_agent.catalog import Catalog
from goal_agent.config import ROOT, Settings
from goal_agent.errors import DependencyError
from goal_agent.gemini import GeminiPlanner
from goal_agent.schemas import ChatRequest, ErrorResponse, GoalResponse
from goal_agent.service import GoalService


def get_service(request: Request) -> GoalService:
    return request.app.state.goal_service


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        catalog = Catalog(ROOT / "catalog.json")
        sdk = (
            genai.Client(
                api_key=settings.api_key.get_secret_value(),
                http_options=types.HttpOptions(
                    timeout=int(settings.model_timeout * 1000),
                    retry_options=types.HttpRetryOptions(
                        attempts=1, initial_delay=0.1, max_delay=0.2
                    ),
                ),
            )
            if settings.api_key
            else None
        )
        async with httpx.AsyncClient(follow_redirects=False) as calendar_http:
            app.state.goal_service = GoalService(
                GeminiPlanner(sdk.aio if sdk else None, settings, catalog),
                CalendarClient(calendar_http, settings),
                catalog,
                settings,
            )
            try:
                yield
            finally:
                if sdk:
                    await sdk.aio.aclose()
                    sdk.close()

    app = FastAPI(title="Ignitus Assessment - Goal Breakdown Agent", lifespan=lifespan)

    @app.exception_handler(DependencyError)
    async def dependency_error_handler(request: Request, exc: DependencyError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.post(
        "/generate_goal_track",
        response_model=GoalResponse,
        responses={
            502: {"model": ErrorResponse, "description": "Invalid model output"},
            503: {"model": ErrorResponse, "description": "Model unavailable or not configured"},
            504: {"model": ErrorResponse, "description": "Model time budget exceeded"},
        },
    )
    async def generate_goal_track(
        request: ChatRequest, service: Annotated[GoalService, Depends(get_service)]
    ) -> GoalResponse:
        return await service.generate(request.message)

    return app


app = create_app()
