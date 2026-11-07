"""Explicit Chicago demonstration data; never a live quote or availability claim."""

import uuid
from datetime import UTC, date, datetime, time

from trippilot.planning.domain import Draft, PlanItem, Source


def sample_plan(day: date, members: list[uuid.UUID], *, alternative: bool = False) -> Draft:
    """Public-place coordinates and illustrative USD totals for a demo only."""
    activities = [
        (
            'Millennium Park walk',
            'Millennium Park',
            41.8826,
            -87.6226,
            0,
            'https://www.chicago.gov/city/en/depts/dca/supp_info/millennium_park.html',
        ),
        (
            'Chicago Cultural Center' if alternative else 'Art Institute visit',
            'Chicago Cultural Center' if alternative else 'Art Institute of Chicago',
            41.8839 if alternative else 41.8796,
            -87.6247 if alternative else -87.6237,
            0 if alternative else 3200 * len(members),
            'https://www.chicago.gov/city/en/depts/dca/supp_info/chicago_culturalcenter.html'
            if alternative
            else 'https://www.artic.edu/visit',
        ),
    ]
    return Draft(
        title='Chicago sample alternative' if alternative else 'Chicago sample day',
        items=[
            PlanItem(
                id=uuid.uuid4(),
                title=title,
                day=day,
                starts_at=time(10 + index * 3),
                duration_minutes=90,
                latitude=lat,
                longitude=lon,
                location=location,
                total_cents=cents,
                participants=members,
                sources=[
                    Source(
                        url=url, label='Official visitor information', checked_at=datetime.now(UTC)
                    )
                ],
            )
            for index, (title, location, lat, lon, cents, url) in enumerate(activities)
        ],
    )
