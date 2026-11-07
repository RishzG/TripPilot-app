"""The organiser's shared destination and travel dates."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TripPlanningContext(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    destination: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    timezone: str = Field(min_length=1, max_length=80)

    @model_validator(mode='after')
    def validate_schedule(self) -> TripPlanningContext:
        if self.end_date < self.start_date:
            raise ValueError('End date must be on or after the start date')
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError('Use an IANA timezone such as Europe/London') from exc
        return self
