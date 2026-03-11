"""Tests for src/airac.py — AIRAC cycle date math."""

from datetime import date

import pytest

from src.airac import AiracCycle, current_cycle, cycle_for_date


class TestCycleForDate:
    """Known-date assertions verified against published AIRAC tables."""

    def test_anchor_date_is_2401(self):
        c = cycle_for_date(date(2024, 1, 25))
        assert c.ident == "2401"
        assert c.year == 2024
        assert c.number == 1
        assert c.effective_date == date(2024, 1, 25)
        assert c.expiry_date == date(2024, 2, 21)

    def test_last_day_of_2401(self):
        assert cycle_for_date(date(2024, 2, 21)).ident == "2401"

    def test_first_day_of_anchor_and_last_day_same_cycle(self):
        c_first = cycle_for_date(date(2024, 1, 25))
        c_last = cycle_for_date(date(2024, 2, 21))
        assert c_first == c_last

    # --- year 2023 ---

    def test_first_cycle_of_2023(self):
        c = cycle_for_date(date(2023, 1, 26))
        assert c.ident == "2301"
        assert c.number == 1
        assert c.effective_date == date(2023, 1, 26)

    def test_last_cycle_of_2023_effective(self):
        c = cycle_for_date(date(2023, 12, 28))
        assert c.ident == "2313"
        assert c.number == 13
        assert c.effective_date == date(2023, 12, 28)

    def test_last_cycle_of_2023_expiry(self):
        c = cycle_for_date(date(2024, 1, 24))
        assert c.ident == "2313"
        assert c.expiry_date == date(2024, 1, 24)

    def test_day_before_anchor_is_2313(self):
        assert cycle_for_date(date(2024, 1, 24)).ident == "2313"

    # --- today's date ---

    def test_2026_03_10_is_2602(self):
        c = cycle_for_date(date(2026, 3, 10))
        assert c.ident == "2602"
        assert c.effective_date == date(2026, 2, 19)
        assert c.expiry_date == date(2026, 3, 18)

    def test_2026_03_18_still_2602(self):
        assert cycle_for_date(date(2026, 3, 18)).ident == "2602"

    def test_2026_03_19_is_2603(self):
        assert cycle_for_date(date(2026, 3, 19)).ident == "2603"


class TestCycleDuration:
    """Every cycle must be exactly 28 days long."""

    @pytest.mark.parametrize("sample_date", [
        date(2020, 3, 15),
        date(2023, 1, 1),
        date(2023, 12, 31),
        date(2024, 2, 29),   # leap day
        date(2025, 6, 1),
        date(2026, 3, 10),
    ])
    def test_cycle_is_28_days(self, sample_date):
        c = cycle_for_date(sample_date)
        # [RULE:AIRAC-CYCLE-DAYS]
        assert (c.expiry_date - c.effective_date).days + 1 == 28

    def test_no_gap_between_consecutive_cycles(self):
        for year in range(2022, 2028):
            for month in [1, 3, 6, 9, 12]:
                c = cycle_for_date(date(year, month, 1))
                nxt = c.next
                # [RULE:AIRAC-CYCLE-DAYS]
                assert nxt.effective_date == c.expiry_date + __import__("datetime").timedelta(days=1)


class TestNextCycle:
    def test_next_from_2401_is_2402(self):
        c = cycle_for_date(date(2024, 1, 25))
        assert c.next.ident == "2402"
        assert c.next.effective_date == date(2024, 2, 22)

    def test_next_at_year_boundary(self):
        last_of_2023 = cycle_for_date(date(2023, 12, 28))  # 2313
        assert last_of_2023.ident == "2313"
        assert last_of_2023.next.ident == "2401"

    def test_next_is_28_days_later(self):
        c = cycle_for_date(date(2025, 7, 1))
        from datetime import timedelta
        # [RULE:AIRAC-CYCLE-DAYS]
        assert c.next.effective_date == c.effective_date + timedelta(days=28)

    def test_chained_next(self):
        c = cycle_for_date(date(2024, 1, 25))  # 2401
        assert c.next.next.ident == "2403"


class TestIdent:
    def test_ident_is_four_chars(self):
        assert len(cycle_for_date(date(2024, 1, 25)).ident) == 4

    def test_ident_year_two_digits(self):
        c = cycle_for_date(date(2024, 1, 25))
        assert c.ident[:2] == "24"

    def test_ident_number_zero_padded(self):
        c = cycle_for_date(date(2024, 1, 25))
        assert c.ident[2:] == "01"

    def test_str_contains_ident_and_dates(self):
        c = cycle_for_date(date(2024, 1, 25))
        s = str(c)
        assert "2401" in s
        assert "2024-01-25" in s
        assert "2024-02-21" in s


class TestCurrentCycle:
    def test_returns_airac_cycle(self):
        assert isinstance(current_cycle(), AiracCycle)

    def test_as_of_known_date(self):
        assert current_cycle(as_of=date(2026, 3, 10)).ident == "2602"

    def test_as_of_none_uses_today(self):
        c = current_cycle()
        today = date.today()
        assert c.effective_date <= today <= c.expiry_date


class TestFrozen:
    def test_airac_cycle_is_immutable(self):
        c = cycle_for_date(date(2024, 1, 25))
        with pytest.raises((AttributeError, TypeError)):
            c.year = 9999  # type: ignore[misc]
