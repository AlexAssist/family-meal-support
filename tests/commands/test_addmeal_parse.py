"""Tests for addmeal day parser."""
from datetime import date

from commands.addmeal import parse_day


class TestParseDay:
    """parse_day converts day specification to a date."""

    def test_full_weekday_name(self):
        """Monday → this week's Monday."""
        result = parse_day("Monday", date(2026, 5, 4))  # May 4 is Monday
        assert result == date(2026, 5, 4)

    def test_abbreviated_weekday_name(self):
        """Mon → this week's Monday."""
        result = parse_day("Mon", date(2026, 5, 4))
        assert result == date(2026, 5, 4)

    def test_lowercase_weekday(self):
        """lowercase weekday names work."""
        result = parse_day("tuesday", date(2026, 5, 4))
        assert result == date(2026, 5, 5)

    def test_case_insensitive(self):
        """Weekday parsing is case-insensitive."""
        result = parse_day("WEDNESDAY", date(2026, 5, 4))
        assert result == date(2026, 5, 6)

    def test_date_format_yyyy_mm_dd(self):
        """YYYY-MM-DD is parsed directly."""
        result = parse_day("2026-05-15", date(2026, 5, 4))
        assert result == date(2026, 5, 15)

    def test_colon_separator_stripped(self):
        """Colon after day name is stripped."""
        result = parse_day("Tuesday:", date(2026, 5, 4))
        assert result == date(2026, 5, 5)

    def test_day_in_past_week(self):
        """A day name for a past day in the same week works."""
        # Thursday May 7, today is Monday May 4
        result = parse_day("Thursday", date(2026, 5, 4))
        assert result == date(2026, 5, 7)

    def test_unknown_day_name_raises(self):
        """An unrecognized day name raises ValueError."""
        try:
            parse_day("Foobar", date(2026, 5, 4))
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "Foobar" in str(e)