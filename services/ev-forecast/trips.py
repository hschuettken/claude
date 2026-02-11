"""Calendar-based trip prediction.

Parses family calendar events to predict upcoming driving needs.
Uses the convention:
  - "H: <destination>" = Hans drives
  - "N: <destination>" = Nicole drives
  - No prefix / normal events = no driving (or Nicole's default commute)

Known destinations are mapped to distances. For unknown destinations
or ambiguous Hans trips, the service can request clarification from
the orchestrator (which asks via Telegram).
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog

logger = structlog.get_logger()


@dataclass
class Trip:
    """A predicted trip requiring the EV."""

    date: date
    person: str                      # "Hans" or "Nicole"
    destination: str                 # Raw destination string
    distance_km: float               # One-way distance
    round_trip_km: float             # Total distance (usually 2x one-way)
    energy_kwh: float                # Estimated energy needed
    departure_time: time | None = None
    return_time: time | None = None
    is_commute: bool = False         # Nicole's regular commute
    needs_clarification: bool = False # Unknown distance or Hans ambiguous
    source: str = ""                 # "calendar" or "default_commute"

    @property
    def label(self) -> str:
        prefix = "commute" if self.is_commute else self.destination
        return f"{self.person}: {prefix} ({self.round_trip_km:.0f} km, {self.energy_kwh:.1f} kWh)"


@dataclass
class DayPlan:
    """All trips planned for a single day."""

    date: date
    trips: list[Trip] = field(default_factory=list)
    earliest_departure: time | None = None
    latest_return: time | None = None

    @property
    def total_energy_kwh(self) -> float:
        return sum(t.energy_kwh for t in self.trips)

    @property
    def total_distance_km(self) -> float:
        return sum(t.round_trip_km for t in self.trips)

    @property
    def has_trips(self) -> bool:
        return len(self.trips) > 0

    @property
    def needs_clarification(self) -> bool:
        return any(t.needs_clarification for t in self.trips)


class TripPredictor:
    """Predicts upcoming trips from calendar events and default patterns."""

    def __init__(
        self,
        known_destinations: dict[str, float],
        consumption_kwh_per_100km: float = 22.0,
        nicole_commute_km: float = 22.0,
        nicole_commute_days: list[str] | None = None,
        nicole_departure_time: str = "07:00",
        nicole_arrival_time: str = "18:00",
        hans_train_threshold_km: float = 350.0,
        calendar_prefix_hans: str = "H:",
        calendar_prefix_nicole: str = "N:",
        timezone: str = "Europe/Berlin",
    ) -> None:
        self._destinations = {k.lower(): v for k, v in known_destinations.items()}
        self._consumption = consumption_kwh_per_100km
        self._nicole_commute_km = nicole_commute_km
        self._nicole_commute_days = nicole_commute_days or ["mon", "tue", "wed", "thu"]
        self._nicole_departure = self._parse_time(nicole_departure_time)
        self._nicole_arrival = self._parse_time(nicole_arrival_time)
        self._hans_train_km = hans_train_threshold_km
        self._prefix_hans = calendar_prefix_hans.lower().strip()
        self._prefix_nicole = calendar_prefix_nicole.lower().strip()
        self._tz = ZoneInfo(timezone)

        # Pending clarifications: {event_id: Trip}
        self._pending_clarifications: dict[str, Trip] = {}

    def predict_trips(
        self,
        calendar_events: list[dict[str, Any]],
        days: int = 3,
    ) -> list[DayPlan]:
        """Generate trip predictions for the next N days.

        Combines calendar events with default commute patterns.
        Returns a DayPlan per day.
        """
        today = datetime.now(self._tz).date()
        plans: list[DayPlan] = []

        for day_offset in range(days):
            current_date = today + timedelta(days=day_offset)
            day_events = self._events_for_date(calendar_events, current_date)

            # Parse calendar events into trips
            calendar_trips = self._parse_calendar_trips(day_events, current_date)

            # Determine if Nicole has a calendar trip or uses default commute
            nicole_has_calendar_trip = any(
                t.person.lower() == "nicole" for t in calendar_trips
            )
            hans_has_calendar_trip = any(
                t.person.lower() == "hans" for t in calendar_trips
            )

            # Check if Hans is on a multi-day trip (all-day event)
            hans_away = self._is_person_away(calendar_events, current_date, "h")
            nicole_away = self._is_person_away(calendar_events, current_date, "n")

            trips: list[Trip] = list(calendar_trips)

            # Add Nicole's default commute if no calendar trip and not away
            if (
                not nicole_has_calendar_trip
                and not nicole_away
                and self._is_commute_day(current_date)
            ):
                commute = self._make_commute_trip(current_date)
                trips.append(commute)

            # Build day plan
            plan = DayPlan(date=current_date, trips=trips)

            # Calculate earliest departure and latest return
            departures = [t.departure_time for t in trips if t.departure_time]
            returns = [t.return_time for t in trips if t.return_time]
            if departures:
                plan.earliest_departure = min(departures)
            if returns:
                plan.latest_return = max(returns)

            plans.append(plan)

        return plans

    def resolve_clarification(self, event_id: str, use_ev: bool, distance_km: float = 0) -> None:
        """Resolve a pending trip clarification (e.g., Hans confirms he drives EV)."""
        trip = self._pending_clarifications.pop(event_id, None)
        if trip and use_ev and distance_km > 0:
            trip.distance_km = distance_km
            trip.round_trip_km = distance_km * 2
            trip.energy_kwh = self._estimate_energy(distance_km * 2)
            trip.needs_clarification = False
            logger.info(
                "trip_clarified",
                destination=trip.destination,
                distance_km=distance_km,
                use_ev=use_ev,
            )

    def _parse_calendar_trips(
        self,
        events: list[dict[str, Any]],
        trip_date: date,
    ) -> list[Trip]:
        """Parse calendar events into Trip objects."""
        trips: list[Trip] = []

        for event in events:
            summary = (event.get("summary") or "").strip()
            if not summary:
                continue

            summary_lower = summary.lower()

            # Determine who drives and where
            person, destination = self._parse_event_summary(summary)
            if not person or not destination:
                continue

            # Look up distance
            distance_km = self._lookup_distance(destination)
            needs_clarification = False

            if distance_km is None:
                # Unknown destination — estimate or flag for clarification
                distance_km = 50.0  # Conservative default
                needs_clarification = True
                logger.info(
                    "unknown_destination",
                    person=person,
                    destination=destination,
                    default_km=distance_km,
                )

            # Hans: check if he takes the train for long distances
            if person.lower() == "hans" and distance_km > self._hans_train_km:
                logger.info(
                    "hans_takes_train",
                    destination=destination,
                    distance_km=distance_km,
                )
                continue  # No EV needed

            # Hans: for medium distances, flag for clarification
            if (
                person.lower() == "hans"
                and distance_km > 100
                and distance_km <= self._hans_train_km
                and not needs_clarification
            ):
                needs_clarification = True

            round_trip_km = distance_km * 2
            energy_kwh = self._estimate_energy(round_trip_km)

            # Determine departure/return times from event
            departure_time = self._extract_time(event.get("start", ""))
            return_time = self._extract_time(event.get("end", ""))

            trip = Trip(
                date=trip_date,
                person=person,
                destination=destination,
                distance_km=distance_km,
                round_trip_km=round_trip_km,
                energy_kwh=energy_kwh,
                departure_time=departure_time or (self._nicole_departure if person.lower() == "nicole" else time(7, 0)),
                return_time=return_time or (self._nicole_arrival if person.lower() == "nicole" else time(18, 0)),
                needs_clarification=needs_clarification,
                source="calendar",
            )
            trips.append(trip)

            if needs_clarification:
                event_id = event.get("id", f"{trip_date}_{destination}")
                self._pending_clarifications[event_id] = trip

        return trips

    def _parse_event_summary(self, summary: str) -> tuple[str, str]:
        """Parse 'H: Stuttgart' into ('Hans', 'Stuttgart').

        Returns (person, destination) or ('', '') if not a driving event.
        """
        summary_stripped = summary.strip()
        summary_lower = summary_stripped.lower()

        # Try prefix matching: "H: destination" or "N: destination"
        for prefix, person in [
            (self._prefix_hans, "Hans"),
            (self._prefix_nicole, "Nicole"),
        ]:
            if summary_lower.startswith(prefix):
                dest = summary_stripped[len(prefix):].strip()
                if dest:
                    return person, dest

        return "", ""

    def _lookup_distance(self, destination: str) -> float | None:
        """Look up one-way distance for a destination."""
        dest_lower = destination.lower().strip()

        # Direct match
        if dest_lower in self._destinations:
            return self._destinations[dest_lower]

        # Try partial match (destination contains a known city)
        for city, distance in self._destinations.items():
            if city in dest_lower or dest_lower in city:
                return distance

        return None

    def _estimate_energy(self, distance_km: float) -> float:
        """Estimate energy needed for a trip (kWh)."""
        return distance_km * self._consumption / 100.0

    def _events_for_date(
        self,
        events: list[dict[str, Any]],
        target_date: date,
    ) -> list[dict[str, Any]]:
        """Filter events that fall on or span a specific date."""
        result: list[dict[str, Any]] = []
        for event in events:
            event_start = event.get("start", "")
            event_end = event.get("end", "")
            is_all_day = event.get("all_day", False)

            try:
                if is_all_day:
                    start_date = date.fromisoformat(event_start[:10])
                    end_date = date.fromisoformat(event_end[:10])
                    if start_date <= target_date < end_date:
                        result.append(event)
                else:
                    start_dt = datetime.fromisoformat(event_start)
                    if start_dt.date() == target_date:
                        result.append(event)
            except (ValueError, TypeError):
                continue

        return result

    def _is_person_away(
        self,
        events: list[dict[str, Any]],
        target_date: date,
        prefix_initial: str,
    ) -> bool:
        """Check if a person is away on a given date (multi-day all-day event).

        A multi-day event like "H: STR" spanning Mon-Fri means Hans is
        gone for the whole week (took the train, car stays home).
        """
        for event in events:
            summary = (event.get("summary") or "").strip().lower()
            if not summary.startswith(f"{prefix_initial}:"):
                continue

            if not event.get("all_day", False):
                continue

            try:
                start_date = date.fromisoformat(event.get("start", "")[:10])
                end_date = date.fromisoformat(event.get("end", "")[:10])
                duration_days = (end_date - start_date).days

                # Multi-day trip — person is away
                if duration_days > 1 and start_date <= target_date < end_date:
                    # Check if this is a train trip (long distance)
                    dest = summary.split(":", 1)[1].strip()
                    dist = self._lookup_distance(dest)
                    if dist and dist > self._hans_train_km and prefix_initial == "h":
                        return True
                    # Nicole multi-day away
                    if prefix_initial == "n" and duration_days > 1:
                        return True
            except (ValueError, TypeError):
                continue

        return False

    def _is_commute_day(self, d: date) -> bool:
        """Check if this is one of Nicole's commute days."""
        day_abbr = d.strftime("%a").lower()[:3]
        return day_abbr in self._nicole_commute_days

    def _make_commute_trip(self, d: date) -> Trip:
        """Create Nicole's default commute trip."""
        round_trip = self._nicole_commute_km * 2
        return Trip(
            date=d,
            person="Nicole",
            destination="Lengerich",
            distance_km=self._nicole_commute_km,
            round_trip_km=round_trip,
            energy_kwh=self._estimate_energy(round_trip),
            departure_time=self._nicole_departure,
            return_time=self._nicole_arrival,
            is_commute=True,
            source="default_commute",
        )

    def _extract_time(self, dt_str: str) -> time | None:
        """Extract time from an ISO datetime string."""
        if not dt_str or len(dt_str) < 11:
            return None
        try:
            dt = datetime.fromisoformat(dt_str)
            return dt.time().replace(second=0, microsecond=0)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_time(time_str: str) -> time:
        parts = time_str.split(":")
        return time(int(parts[0]), int(parts[1]))

    def get_pending_clarifications(self) -> list[dict[str, Any]]:
        """Return trips that need user clarification (for orchestrator)."""
        return [
            {
                "event_id": eid,
                "person": trip.person,
                "destination": trip.destination,
                "date": trip.date.isoformat(),
                "estimated_distance_km": trip.distance_km,
                "question": (
                    f"Fährst du am {trip.date.strftime('%d.%m.')} nach "
                    f"{trip.destination} mit dem E-Auto? "
                    f"(geschätzt {trip.distance_km:.0f} km einfach)"
                ),
            }
            for eid, trip in self._pending_clarifications.items()
        ]
