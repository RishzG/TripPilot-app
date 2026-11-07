"""Bounded London research snapshot, checked against official visitor pages."""

from dataclasses import dataclass
from datetime import date, timedelta
from re import findall

from trippilot.trips.context import TripPlanningContext
from trippilot.trips.plans import ResearchSource

CHECKED_ON = date(2026, 11, 7)


@dataclass(frozen=True)
class Venue:
    title: str
    location: str
    topics: frozenset[str]
    source: ResearchSource
    estimate_cents: int | None
    closed_over_christmas: bool = False


VENUES = (
    Venue(
        'Natural History Museum',
        'Cromwell Road, London SW7 5BD',
        frozenset({'dinosaur', 'dinosaurs', 'science', 'museum', 'wildlife', 'fossils'}),
        ResearchSource(
            title='Natural History Museum visitor information',
            url='https://www.nhm.ac.uk/visit.html',
            checked_on=CHECKED_ON,
            estimate_note='Free general galleries. Special exhibitions may charge.',
        ),
        0,
        closed_over_christmas=True,
    ),
    Venue(
        'V&A South Kensington',
        'Cromwell Road, London SW7 2RL',
        frozenset({'art', 'design', 'fashion', 'museum', 'architecture', 'galleries'}),
        ResearchSource(
            title='V&A South Kensington visitor information',
            url='https://www.vam.ac.uk/south-kensington',
            checked_on=CHECKED_ON,
            estimate_note='Free general admission. Some exhibitions and events may charge.',
        ),
        0,
        closed_over_christmas=True,
    ),
    Venue(
        'Hyde Park lakeside walk',
        'The Serpentine, Hyde Park, London',
        frozenset({'park', 'parks', 'walk', 'walking', 'outdoors', 'lake', 'garden', 'gardens'}),
        ResearchSource(
            title='Hyde Park visitor information',
            url='https://www.royalparks.org.uk/visit/parks/hyde-park',
            checked_on=CHECKED_ON,
            estimate_note='Location sourced. Optional activities and other costs are unpriced.',
        ),
        None,
    ),
)


def supports_destination(destination: str) -> bool:
    return destination.casefold() in {'london', 'london, uk', 'london, england'}


def research(context: TripPlanningContext, messages: list[str]) -> list[tuple[date, Venue]]:
    """Rank curated venues by topic mentions, then place up to two on in-range days."""
    words = set(findall(r'[a-z]+', ' '.join(messages).casefold()))
    ranked = sorted(VENUES, key=lambda venue: -len(venue.topics & words))
    span = (context.end_date - context.start_date).days
    selected: list[tuple[date, Venue]] = []
    for venue in ranked:
        first = min(len(selected), span)
        for offset in range(first, min(span, first + 3) + 1):
            day = context.start_date + timedelta(days=offset)
            if venue.closed_over_christmas and day.month == 12 and 24 <= day.day <= 26:
                continue
            selected.append((day, venue))
            break
        if len(selected) == 2:
            break
    return selected
