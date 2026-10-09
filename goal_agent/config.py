import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr, field_validator

ROOT = Path(__file__).resolve().parent.parent
CALENDAR_URL = "https://ignitus-mock-calendar.azurewebsites.net/calendar/schedule"


class Settings(BaseModel):
    api_key: SecretStr | None = Field(default=None, repr=False)
    model: str = "gemini-3.8-flash"
    timezone: str = "Europe/London"
    model_timeout: float = Field(default=35, gt=0, le=120)
    calendar_timeout: float = Field(default=15, gt=0, le=60)
    calendar_request_timeout: float = Field(default=6, gt=0, le=30)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env", override=False)
        key = os.getenv("GEMINI_API_KEY", "").strip()
        return cls(
            api_key=SecretStr(key) if key else None,
            model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
            timezone=os.getenv("GOAL_TIMEZONE", "Europe/London"),
            model_timeout=os.getenv("MODEL_TIMEOUT_SECONDS", "35"),
            calendar_timeout=os.getenv("CALENDAR_TIMEOUT_SECONDS", "15"),
            calendar_request_timeout=os.getenv("CALENDAR_REQUEST_TIMEOUT_SECONDS", "6"),
        )
