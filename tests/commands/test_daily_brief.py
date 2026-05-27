"""Tests for the daily brief command."""
from datetime import date, timedelta
from pathlib import Path
import tempfile

import pytest

from commands.daily_brief import format_daily_brief


def _write_week_plan(vault: Path, week_start: date, extra_content: dict[date, str]) -> None:
    """Write a plan file for a full week starting at week_start.

    Each day gets a **Supper:** line (empty if not in extra_content).
    If extra_content[date] is set, it replaces the **Supper:** line.

    Format: '## <DayName> <MonthName> <DayNum>' matching real plan files.
    """
    plan_file = vault / "reference" / "meal-planning" / "plans" / f"{week_start.strftime('%Y-%m-%d')}.md"
    plan_file.parent.mkdir(parents=True)

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    lines = [f"# Week of {week_start.strftime('%B %-d, %Y')}", ""]
    current = week_start
    for _ in range(7):
        day_name = day_names[current.weekday()]
        lines.append(f"## {day_name} {current.strftime('%B %-d')}")
        extra = extra_content.get(current, "")
        if extra:
            # First line of extra is the **Supper:** line value (may contain defrost/prep on next line)
            parts = extra.split("\n", 1)
            lines.append(f"**Supper:** {parts[0]}")
            if len(parts) > 1:
                lines.append(parts[1])
        else:
            lines.append("**Supper:** ")
            lines.append("🧊 Defrost: | 🔪 Prep:")
        lines.append("")
        current = current + timedelta(days=1)

    plan_file.write_text("\n".join(lines))


class TestFormatDailyBrief:
    """format_daily_brief returns the right message for today's meal."""

    def test_returns_none_when_no_meal_planned(self) -> None:
        """No plan file → None (no meal planned)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            # No plan file at all
            result = format_daily_brief(vault, date(2026, 5, 4))
        assert result is None

    def test_returns_none_when_day_is_empty(self) -> None:
        """Plan exists but today has no meal → None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            monday = date(2026, 5, 4)
            _write_week_plan(vault, monday, {})
            result = format_daily_brief(vault, monday)
        assert result is None

    def test_formats_meal_with_link(self) -> None:
        """Meal with a link includes it in the brief."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            saturday = date(2026, 5, 9)
            _write_week_plan(vault, date(2026, 5, 4), {
                saturday: "[McChicken Smash Tacos](https://example.com/tacos)\n🧊 Defrost: Ground chicken | 🔪 Prep: Mix sauce"
            })
            result = format_daily_brief(vault, saturday)
        assert result is not None
        assert "McChicken Smash Tacos" in result
        assert "https://example.com/tacos" in result
        assert "🧊 Defrost: Ground chicken" in result
        assert "🔪 Prep: Mix sauce" in result

    def test_no_link_when_recipe_has_none(self) -> None:
        """Meal without a link shows just the name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            saturday = date(2026, 5, 9)
            _write_week_plan(vault, date(2026, 5, 4), {
                saturday: "Pizza\n🧊 Defrost: | 🔪 Prep:"
            })
            result = format_daily_brief(vault, saturday)
        assert result is not None
        assert "Pizza" in result
        assert "http" not in result

    def test_includes_defrost_reminder(self) -> None:
        """Defrost reminder appears in the brief."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            saturday = date(2026, 5, 9)
            _write_week_plan(vault, date(2026, 5, 4), {
                saturday: "[McChicken](https://example.com)\n🧊 Defrost: Chicken breasts | 🔪 Prep: Make sauce"
            })
            result = format_daily_brief(vault, saturday)
        assert result is not None
        assert "🧊 Defrost: Chicken breasts" in result
        assert "🔪 Prep: Make sauce" in result

    def test_empty_defrost_prep_not_shown(self) -> None:
        """Defrost/prep lines with empty values don't appear in the brief."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            saturday = date(2026, 5, 9)
            _write_week_plan(vault, date(2026, 5, 4), {
                saturday: "[McChicken](https://example.com)\n🧊 Defrost: | 🔪 Prep:"
            })
            result = format_daily_brief(vault, saturday)
        assert result is not None
        assert "Defrost" not in result
        assert "Prep" not in result
        assert "McChicken" in result