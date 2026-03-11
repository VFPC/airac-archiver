"""AIRAC cycle date math — cycle number from date, effective date ranges."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# Known anchor: AIRAC 2401 became effective on 2024-01-25.
_ANCHOR = date(2024, 1, 25)
# [RULE:AIRAC-CYCLE-DAYS] ICAO Annex 15: the AIRAC amendment cycle is exactly 28 days.
_CYCLE_DAYS = 28


@dataclass(frozen=True)
class AiracCycle:
    """A single 28-day AIRAC cycle."""

    year: int
    number: int           # 1-based within the year
    effective_date: date  # inclusive start
    expiry_date: date     # inclusive end (one day before the next effective date)

    @property
    def ident(self) -> str:
        """Short identifier in YYNN format, e.g. '2401' for cycle 1 of 2024."""
        return f"{self.year % 100:02d}{self.number:02d}"

    @property
    def next(self) -> AiracCycle:
        """Return the immediately following cycle."""
        return cycle_for_date(self.effective_date + timedelta(days=_CYCLE_DAYS))

    def __str__(self) -> str:
        return (
            f"AIRAC {self.ident} "
            f"({self.effective_date.isoformat()} – {self.expiry_date.isoformat()})"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _n_for_date(target: date) -> int:
    """0-based index of the cycle (relative to anchor) that contains *target*.

    Python's ``//`` is floor division, so negative deltas are handled correctly:
    a date before the anchor returns the index of the cycle whose effective date
    is on or before that date.
    """
    return (target - _ANCHOR).days // _CYCLE_DAYS


def _effective_date_for_n(n: int) -> date:
    return _ANCHOR + timedelta(days=n * _CYCLE_DAYS)


def _first_cycle_n_of_year(year: int) -> int:
    """0-based anchor index of the first cycle whose effective date falls in *year*."""
    n = _n_for_date(date(year, 1, 1))
    if _effective_date_for_n(n).year < year:
        n += 1
    return n


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def cycle_for_date(target: date) -> AiracCycle:
    """Return the AIRAC cycle that contains *target*."""
    n = _n_for_date(target)
    effective = _effective_date_for_n(n)
    expiry = _effective_date_for_n(n + 1) - timedelta(days=1)

    year = effective.year
    first_n = _first_cycle_n_of_year(year)
    number = n - first_n + 1

    return AiracCycle(
        year=year,
        number=number,
        effective_date=effective,
        expiry_date=expiry,
    )


def current_cycle(as_of: date | None = None) -> AiracCycle:
    """Return the currently active AIRAC cycle.

    Pass *as_of* to pin the calculation to a specific date (useful in tests).
    Defaults to ``date.today()``.
    """
    return cycle_for_date(as_of if as_of is not None else date.today())
