"""Tests for the weekly email command."""
from datetime import date, timedelta
from pathlib import Path
import tempfile

import pytest

from commands.email import format_weekly_email, is_email_trigger


def _write_plan_with_meals(vault: Path, week_start: date, meals: dict[date, str]) -> None:
    """Write a plan file with given meals on specific dates.

    meals maps date → "Recipe Name\n🧊 Defrost: ... | 🔪 Prep: ..."
    """
    plan_file = (
        vault
        / "reference"
        / "meal-planning"
        / "plans"
        / f"{week_start.strftime('%Y-%m-%d')}.md"
    )
    plan_file.parent.mkdir(parents=True)

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    lines = [f"# Week of {week_start.strftime('%B %-d, %Y')}", ""]
    current = week_start
    for _ in range(7):
        day_name = day_names[current.weekday()]
        lines.append(f"## {day_name} {current.strftime('%B %-d')}")
        meal_text = meals.get(current, "")
        if meal_text:
            parts = meal_text.split("\n", 1)
            lines.append(f"**Supper:** {parts[0]}")
            if len(parts) > 1:
                lines.append(parts[1])
        else:
            lines.append("**Supper:** ")
            lines.append("🧊 Defrost: | 🔪 Prep:")
        lines.append("")
        current = current + timedelta(days=1)

    plan_file.write_text("\n".join(lines))


class TestIsEmailTrigger:
    """is_email_trigger recognizes command and natural language patterns."""

    @pytest.mark.parametrize("msg", [
        "!email",
        "!email",
        "send email",
        "weekly email",
        "email meal plan",
    ])
    def test_positive_matches(self, msg: str) -> None:
        assert is_email_trigger(msg) is True

    @pytest.mark.parametrize("msg", [
        "!grocery",
        "what's for dinner",
        "",
        "send",
        "email",
    ])
    def test_negative_matches(self, msg: str) -> None:
        assert is_email_trigger(msg) is False


class TestFormatWeeklyEmail:
    """format_weekly_email formats the meal plan and grocery list."""

    def test_returns_none_when_no_plan_file(self) -> None:
        """No plan file for the week → None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            result = format_weekly_email(vault, date(2026, 5, 4))
        assert result is None

    def test_returns_none_when_all_days_empty(self) -> None:
        """Plan file exists but no meals planned → None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            monday = date(2026, 5, 4)
            _write_plan_with_meals(vault, monday, {})
            result = format_weekly_email(vault, monday)
        assert result is None

    def test_formats_header_with_week(self) -> None:
        """Email header includes the week of date."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            monday = date(2026, 5, 4)
            _write_plan_with_meals(vault, monday, {
                monday: "Pizza",
            })
            result = format_weekly_email(vault, monday)
        assert result is not None
        assert "Week of May 4, 2026" in result
        assert "THIS WEEK'S MEALS" in result

    def test_includes_recipe_name_and_link(self) -> None:
        """Meal with a link shows name and link."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            tuesday = date(2026, 5, 5)
            _write_plan_with_meals(vault, date(2026, 5, 4), {
                tuesday: "Pasta\n🧊 Defrost: | 🔪 Prep:",
            })
            result = format_weekly_email(vault, date(2026, 5, 4))
        assert result is not None
        assert "Tuesday — Pasta" in result

    def test_includes_defrost_and_prep_in_email(self) -> None:
        """Defrost/prep reminders appear in the email."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            saturday = date(2026, 5, 9)
            _write_plan_with_meals(vault, date(2026, 5, 4), {
                saturday: "Chicken\n🧊 Defrost: Chicken breasts | 🔪 Prep: Make sauce",
            })
            result = format_weekly_email(vault, date(2026, 5, 4))
        assert result is not None
        assert "🧊 Defrost: Chicken breasts" in result
        assert "🔪 Prep: Make sauce" in result

    def test_empty_days_show_no_plan_placeholder(self) -> None:
        """Days with no meal show placeholder text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            monday = date(2026, 5, 4)
            _write_plan_with_meals(vault, monday, {})  # all empty
            result = format_weekly_email(vault, monday)
        assert result is None  # all empty → None

    def test_shows_grocery_list_section(self) -> None:
        """Email includes the grocery list section header."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            monday = date(2026, 5, 4)
            # Write meals and recipes
            _write_plan_with_meals(vault, monday, {
                monday: "Tacos",
            })
            # Create recipe file for Tacos
            recipe_dir = vault / "reference" / "meal-planning" / "meals"
            recipe_dir.mkdir(parents=True)
            recipe_file = recipe_dir / "tacos.md"
            recipe_file.write_text(
                "# Tacos\n\nIngredients:\n- Ground beef\n- Taco seasoning\n"
            )
            result = format_weekly_email(vault, monday)
        assert result is not None
        assert "GROCERY LIST" in result