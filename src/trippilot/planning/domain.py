"""Validated itinerary contracts and deterministic integer-cent allocation."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class TripContext(BaseModel):
    """Leader-edited shared context; optimistic revision prevents lost edits."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    destination: str = Field(max_length=160)
    start_date: date | None = None
    end_date: date | None = None
    timezone: str = 'UTC'
    revision: int = Field(ge=0)

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        """Accept IANA timezone names, including DST rules."""
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('Use an IANA timezone such as America/Chicago') from exc
        return value

    @model_validator(mode='after')
    def ordered_dates(self) -> 'TripContext':
        """Dates must be supplied together and in chronological order."""
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError('Set both trip dates, or clear both')
        if (
            self.start_date
            and self.end_date
            and not 0 <= (self.end_date - self.start_date).days <= 30
        ):
            raise ValueError('Trip must be between one and 31 days')
        return self


class Source(BaseModel):
    """Reference evidence; estimates never assert a live booking or availability."""

    url: HttpUrl
    label: str = Field(min_length=1, max_length=200)
    checked_at: datetime


class PlanItem(BaseModel):
    """Immutable activity input. Shares and totals are always calculated by code."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: uuid.UUID
    title: str = Field(min_length=1, max_length=160)
    day: date
    starts_at: time
    duration_minutes: int = Field(ge=1, le=1440)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    location: str = Field(min_length=1, max_length=200)
    evidence: str = Field(default='', max_length=3000)
    total_cents: int = Field(strict=True, ge=0, le=100_000_000)
    currency: Literal['USD'] = 'USD'
    participants: list[uuid.UUID] = Field(min_length=1, max_length=12)
    sources: list[Source] = Field(min_length=1, max_length=8)
    cost_basis: Literal['estimate'] = 'estimate'

    @field_validator('participants')
    @classmethod
    def distinct_participants(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        """Reject duplicate shares rather than charging a participant twice."""
        if len(set(value)) != len(value):
            raise ValueError('Participants must be unique')
        return sorted(value, key=str)


class Draft(BaseModel):
    """One bounded, structured draft from Pilot or the clearly marked sample."""

    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=160)
    items: list[PlanItem] = Field(min_length=1, max_length=60)

    @model_validator(mode='after')
    def unique_items(self) -> 'Draft':
        """Stable item IDs identify one activity within a revision."""
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError('Duplicate item ID')
        return self


def shares(total_cents: int, participants: list[str]) -> dict[str, int]:
    """Split exact cents; the stable account-ID order receives remainder cents."""
    members = sorted(set(participants))
    if total_cents < 0 or not members or len(members) != len(participants):
        raise ValueError('Nonnegative cents and unique participants are required')
    quotient, remainder = divmod(total_cents, len(members))
    return {member: quotient + (index < remainder) for index, member in enumerate(members)}


def validate_schedule(draft: Draft, context: TripContext, *, complete: bool = True) -> None:
    """Reject missing days, overlapping activities and nonexistent local DST times."""
    if not context.start_date or not context.end_date:
        raise ValueError('Trip dates are required')
    zone = ZoneInfo(context.timezone)
    intervals: dict[uuid.UUID, list[tuple[datetime, datetime]]] = {}
    for item in draft.items:
        if not context.start_date <= item.day <= context.end_date or item.starts_at.tzinfo:
            raise ValueError('Items must use local wall times within trip dates')
        start = datetime.combine(item.day, item.starts_at).replace(tzinfo=zone)
        if start.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != start.replace(
            tzinfo=None
        ):
            raise ValueError('Activity uses a nonexistent local DST time')
        end = start + timedelta(minutes=item.duration_minutes)
        if end.date() > context.end_date:
            raise ValueError('Activity ends after the trip')
        for member in item.participants:
            intervals.setdefault(member, []).append((start, end))
    for periods in intervals.values():
        periods.sort()
        if any(
            end > next_start
            for (_, end), (next_start, _) in zip(periods, periods[1:], strict=False)
        ):
            raise ValueError('Activities overlap for a participant')
    expected_days = {
        context.start_date + timedelta(days=i)
        for i in range((context.end_date - context.start_date).days + 1)
    }
    if complete and {item.day for item in draft.items} != expected_days:
        raise ValueError('A complete draft must include each trip day')
