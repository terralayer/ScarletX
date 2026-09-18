"""Daily transfer quiet hours. Manual job state is never changed by the schedule."""

from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


class DownloadSchedule(BaseModel):
    enabled: bool = False
    timezone: str = "UTC"
    start: str = Field(default="22:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(default="07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    mode: Literal["pause", "limit"] = "pause"
    speed_limit_mb_s: float = Field(default=5, gt=0, le=10000, allow_inf_nan=False)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Choose a valid IANA timezone, for example America/Los_Angeles") from exc
        return value

    @model_validator(mode="after")
    def distinct_times(self):
        if self.start == self.end:
            raise ValueError("Quiet-hours start and end must differ")
        return self


def schedule_state(rule: DownloadSchedule, now=None, *, base_limit=0):
    local = (now or datetime.now(UTC)).astimezone(ZoneInfo(rule.timezone))
    clock = local.strftime("%H:%M")
    inside = (
        rule.start <= clock < rule.end if rule.start < rule.end else clock >= rule.start or clock < rule.end
    )
    active = bool(rule.enabled and inside)
    limit = max(0, float(base_limit))
    if active and rule.mode == "limit":
        limit = min(limit, rule.speed_limit_mb_s) if limit else rule.speed_limit_mb_s
    return dict(
        active=active,
        paused=active and rule.mode == "pause",
        speed_limit_mb_s=limit,
        timezone=rule.timezone,
        local_time=local.isoformat(),
    )


def configured_schedule(settings):
    return DownloadSchedule.model_validate_json(getattr(settings, "download_schedule_json", "{}"))
