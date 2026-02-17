"""Calendar-based trip prediction.

Parses family calendar events to predict upcoming driving needs.
Uses the convention:
  - "H: <destination>" = Henning drives
  - "N: <destination>" = Nicole drives
  - No prefix / normal events = no driving (or Nicole's default commute)

Known destinations are mapped to distances. Unknown destinations are
geocoded via OpenStreetMap Nominatim to estimate road distance from home.
For ambiguous Henning trips, the service requests clarification from
the orchestrator (which asks via Telegram).
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import structlog

logger = structlog.get_logger()


@dataclass
class Trip:
    """A predicted trip requiring the EV."""

    date: date
    person: str                      # "Henning" or "Nicole"
    destination: str                 # Raw destination string
    distance_km: float               # One-way distance
    round_trip_km: float             # Total distance (usually 2x one-way)
    energy_kwh: float                # Estimated energy needed
    departure_time: time | None = None
    return_time: time | None = None
    is_commute: bool = False         # Nicole's regular commute
    needs_clarification: bool = False # Unknown distance or Henning ambiguous
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


class GeoDistance:
    """Estimate road distance using OpenStreetMap Nominatim geocoding.

    For destinations not in the known lookup table, this class:
    1. Geocodes the destination name via Nominatim (free, no API key)
    2. Calculates haversine (great-circle) distance from home
    3. Multiplies by a road factor (default 1.3) to estimate driving distance
    """

    NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

    def __init__(
        self,
        home_lat: float,
        home_lon: float,
        road_factor: float = 1.3,
    ) -> None:
        self._home_lat = home_lat
        self._home_lon = home_lon
        self._road_factor = road_factor
        # Cache: destination_lower → distance_km
        self._cache: dict[str, float] = {}

    async def estimate_distance(self, destination: str) -> float | None:
        """Estimate one-way road distance to a destination in km.

        Returns None if geocoding fails.
        """
        key = destination.lower().strip()
        if key in self._cache:
            return self._cache[key]

        coords = await self._geocode(destination)
        if coords is None:
            return None

        lat, lon = coords
        straight_km = self._haversine(self._home_lat, self._home_lon, lat, lon)
        road_km = round(straight_km * self._road_factor, 1)
        self._cache[key] = road_km

        logger.info(
            "geocoded_destination",
            destination=destination,
            lat=lat,
            lon=lon,
            straight_km=round(straight_km, 1),
            road_km=road_km,
        )
        return road_km

    async def _geocode(self, query: str) -> tuple[float, float] | None:
        """Look up coordinates for a place name via Nominatim."""
        # Bias towards Germany for better results
        search_query = query if "," in query else f"{query}, Deutschland"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    self.NOMINATIM_URL,
                    params={
                        "q": search_query,
                        "format": "json",
                        "limit": 1,
                        "countrycodes": "de",
                    },
                    headers={"User-Agent": "homelab-ev-forecast/1.0"},
                )
                resp.raise_for_status()
                results = resp.json()
                if results:
                    return float(results[0]["lat"]), float(results[0]["lon"])
        except Exception:
            logger.debug("geocoding_failed", destination=query)
        return None

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate great-circle distance in km between two points."""
        R = 6371.0  # Earth radius in km
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


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
        henning_train_threshold_km: float = 350.0,
        calendar_prefix_henning: str = "H:",
        calendar_prefix_nicole: str = "N:",
        timezone: str = "Europe/Berlin",
        geo_distance: GeoDistance | None = None,
        learned_destinations: Any = None,
    ) -> None:
        self._destinations = {k.lower(): v for k, v in known_destinations.items()}
        self._consumption = consumption_kwh_per_100km
        self._default_consumption = consumption_kwh_per_100km
        self._nicole_commute_km = nicole_commute_km
        self._nicole_commute_days = nicole_commute_days or ["mon", "tue", "wed", "thu"]
        self._nicole_departure = self._parse_time(nicole_departure_time)
        self._nicole_arrival = self._parse_time(nicole_arrival_time)
        self._henning_train_km = henning_train_threshold_km
        self._prefix_henning = calendar_prefix_henning.lower().strip()
        self._prefix_nicole = calendar_prefix_nicole.lower().strip()
        self._tz = ZoneInfo(timezone)
        self._geo = geo_distance
        self._learned = learned_destinations

        # Pending clarifications: {event_id: Trip}
        self._pending_clarifications: dict[str, Trip] = {}

    @property
    def consumption_kwh_per_100km(self) -> float:
        """Current consumption rate used for energy calculations."""
        return self._consumption

    @consumption_kwh_per_100km.setter
    def consumption_kwh_per_100km(self, value: float) -> None:
        """Update consumption rate (e.g. from dynamic consumption tracker)."""
        self._consumption = value

    async def predict_trips(
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
            calendar_trips = await self._parse_calendar_trips(day_events, current_date)

            # Determine if Nicole has a calendar trip or uses default commute
            nicole_has_calendar_trip = any(
                t.person.lower() == "nicole" for t in calendar_trips
            )
            henning_has_calendar_trip = any(
                t.person.lower() == "henning" for t in calendar_trips
            )

            # Check if Henning is on a multi-day trip (all-day event)
            henning_away = self._is_person_away(calendar_events, current_date, "h")
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
        """Resolve a pending trip clarification (e.g., Henning confirms he drives EV)."""
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

    async def _parse_calendar_trips(
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

            # Look up distance (known table first, then geocoding)
            distance_km = self._lookup_distance(destination)
            needs_clarification = False

            if distance_km is None and self._geo:
                # Try geocoding the destination
                geo_km = await self._geo.estimate_distance(destination)
                if geo_km is not None:
                    distance_km = geo_km
                    # Cache in known destinations for future lookups
                    self._destinations[destination.lower().strip()] = geo_km
                    logger.info(
                        "destination_geocoded",
                        person=person,
                        destination=destination,
                        distance_km=geo_km,
                    )

            if distance_km is None:
                # Geocoding also failed — use conservative default
                distance_km = 50.0
                needs_clarification = True
                logger.info(
                    "unknown_destination",
                    person=person,
                    destination=destination,
                    default_km=distance_km,
                )

            # Henning: check if he takes the train for long distances
            if person.lower() == "henning" and distance_km > self._henning_train_km:
                logger.info(
                    "henning_takes_train",
                    destination=destination,
                    distance_km=distance_km,
                )
                continue  # No EV needed

            # Henning: for medium distances, flag for clarification
            if (
                person.lower() == "henning"
                and distance_km > 100
                and distance_km <= self._henning_train_km
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
        """Parse 'H: Stuttgart' into ('Henning', 'Stuttgart').

        Returns (person, destination) or ('', '') if not a driving event.
        """
        summary_stripped = summary.strip()
        summary_lower = summary_stripped.lower()

        # Try prefix matching: "H: destination" or "N: destination"
        for prefix, person in [
            (self._prefix_henning, "Henning"),
            (self._prefix_nicole, "Nicole"),
        ]:
            if summary_lower.startswith(prefix):
                dest = summary_stripped[len(prefix):].strip()
                if dest:
                    return person, dest

        return "", ""

    def _lookup_distance(self, destination: str) -> float | None:
        """Look up one-way distance for a destination.

        Lookup order:
        1. Config-based known_destinations (static, from env var)
        2. Learned destinations (from orchestrator conversations via MQTT)
        3. Return None → caller falls through to geocoding
        """
        dest_lower = destination.lower().strip()

        # 1. Direct match in config destinations
        if dest_lower in self._destinations:
            return self._destinations[dest_lower]

        # Partial match in config destinations
        for city, distance in self._destinations.items():
            if city in dest_lower or dest_lower in city:
                return distance

        # 2. Check learned destinations (from orchestrator knowledge store)
        if self._learned:
            learned_km = self._learned.lookup(destination)
            if learned_km is not None:
                logger.info(
                    "distance_from_learned",
                    destination=destination,
                    distance_km=learned_km,
                )
                return learned_km

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

        A multi-day event like "H: STR" spanning Mon-Fri means Henning is
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
                    if dist and dist > self._henning_train_km and prefix_initial == "h":
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
        """Return trips that need user clarification (for orchestrator).

        Generates smarter questions when learned destinations provide
        disambiguation options (e.g. "Sarah in Bocholt oder Ibbenbüren?").
        """
        results: list[dict[str, Any]] = []
        for eid, trip in self._pending_clarifications.items():
            question = self._build_clarification_question(trip)
            entry: dict[str, Any] = {
                "event_id": eid,
                "person": trip.person,
                "destination": trip.destination,
                "date": trip.date.isoformat(),
                "estimated_distance_km": trip.distance_km,
                "question": question,
            }

            # Add disambiguation options if available
            if self._learned:
                options = self._learned.lookup_all(trip.destination)
                if len(options) > 1:
                    entry["disambiguation_options"] = [
                        {
                            "name": o.get("name", trip.destination),
                            "distance_km": o.get("distance_km", 0),
                        }
                        for o in options
                    ]

            results.append(entry)
        return results

    def _build_clarification_question(self, trip: Trip) -> str:
        """Build a smart clarification question for a trip.

        If learned destinations have multiple matches for the destination
        name, generates a disambiguation question mentioning all options.
        """
        date_str = trip.date.strftime("%d.%m.")

        # Check for disambiguation options in learned destinations
        if self._learned:
            options = self._learned.lookup_all(trip.destination)
            if len(options) > 1:
                # Multiple known places with this name
                parts = " oder ".join(
                    f"{o.get('name', trip.destination)} ({o.get('distance_km', '?')} km)"
                    for o in options
                )
                return (
                    f"Fährst du am {date_str} zu {parts} mit dem E-Auto?"
                )

        # Default question
        return (
            f"Fährst du am {date_str} nach "
            f"{trip.destination} mit dem E-Auto? "
            f"(geschätzt {trip.distance_km:.0f} km einfach)"
        )
