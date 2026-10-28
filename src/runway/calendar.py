"""Maintenance windows and launch freezes: when the platform may change.

One calendar (config/launch-calendar.yaml) feeds the wave planner, the Argo CD sync windows and
the GitLab CI freeze gate, so the three can never disagree about when a launch campaign is frozen.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from runway.settings import Campaign, Windows

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.start < end and start < self.end


def maintenance_slots(w: Windows, start: datetime, until: datetime) -> Iterator[Slot]:
    """Every maintenance window that starts at or after ``start`` and before ``until``, in order."""
    tz = ZoneInfo(w.timezone)
    day: date = start.astimezone(tz).date()
    while datetime.combine(day, time(0), tz) < until:
        for rule in w.maintenance:
            if DAYS[day.weekday()] not in rule.days:
                continue
            hh, mm = (int(x) for x in rule.start.split(":"))
            s = datetime.combine(day, time(hh, mm), tz)
            if start <= s < until:
                yield Slot(s, s + timedelta(hours=rule.hours))
        day += timedelta(days=1)


def freezes_for(w: Windows, site: str) -> list[Campaign]:
    return [c for c in w.campaigns if not c.sites or site in c.sites]


def frozen_by(w: Windows, site: str, slot: Slot) -> Campaign | None:
    """The campaign whose freeze this slot touches at ``site``, if any."""
    for c in freezes_for(w, site):
        if slot.overlaps(c.freeze_start, c.freeze_end):
            return c
    return None


def active_freezes(w: Windows, at: datetime) -> list[Campaign]:
    return [c for c in w.campaigns if c.freeze_start <= at < c.freeze_end]
