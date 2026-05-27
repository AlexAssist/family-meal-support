"""Tests for the !mealplan command."""
from datetime import date
from pathlib import Path
import tempfile

from commands.mealplan import format_meal_plan, get_week_monday


class TestGetWeekMonday:
    """get_week_monday returns the Monday of the week for a given date."""

    def test_monday_returns_same_monday(self) -> None:
        """When date is a Monday, returns that Monday."""
        result = get_week_monday(date(2026, 5, 4))
        assert result == date(2026, 5, 4)

    def test_other_weekday_returns_previous_monday(self) -> None:
        """When date is Tuesday, returns the preceding Monday."""
        result = get_week_monday(date(2026, 5, 5))
        assert result == date(2026, 5, 4)

    def test_sunday_returns_previous_monday(self) -> None:
        """When date is Sunday, returns the preceding Monday."""
        result = get_week_monday(date(2026, 5, 10))
        assert result == date(2026, 5, 4)


class TestFormatMealPlan:
    """format_meal_plan formats a MealPlan for Discord."""

    def _vault_with_plan(self, tmpdir: Path, content: str, monday: str = "2026-05-04") -> Path:
        vault = Path(tmpdir)
        plan_dir = vault / "reference" / "meal-planning" / "plans"
        plan_dir.mkdir(parents=True)
        (plan_dir / f"{monday}.md").write_text(content)
        return vault

    def test_one_day_per_line(self) -> None:
        """Each day appears on its own line with date and meal."""
        content = """# Week of May 4, 2026

## Monday May 4
**Supper:** Pasta Primavera
🧊 Defrost: | 🔪 Prep: 

## Tuesday May 5
**Supper:** 
🧊 Defrost: | 🔪 Prep: 

## Wednesday May 6
**Supper:** [Korean Ground Chicken](https://example.com/korean)
🧊 Defrost: | 🔪 Prep: 

## Thursday May 7
**Supper:** Hamburgers
🧊 Defrost: | 🔪 Prep: 

## Friday May 8
**Supper:** 
🧊 Defrost: | 🔪 Prep: 

## Saturday May 9
**Supper:** Taco Salad
🧊 Defrost: | 🔪 Prep: 

## Sunday May 10
**Supper:** Donor Kebabs
🧊 Defrost: | 🔪 Prep: 
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = self._vault_with_plan(tmpdir, content)

            result = format_meal_plan(vault, date(2026, 5, 4))

        assert result is not None
        lines = result.split("\n")
        assert "Week of May 4" in lines[0]
        assert len(lines) == 8  # header + 7 days
        assert "Mon May 4" in lines[1]
        assert "Pasta Primavera" in lines[1]
        assert "Tue May 5" in lines[2]
        assert "—" in lines[2]
        assert "Wed May 6" in lines[3]
        assert "Korean Ground Chicken" in lines[3]
        assert "https://example.com/korean" in lines[3]  # link included

    def test_empty_days_show_dash(self) -> None:
        """Days with no planned meal show a dash."""
        content = """# Week of May 4, 2026

## Monday May 4
**Supper:** 
🧊 Defrost: | 🔪 Prep: 
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = self._vault_with_plan(tmpdir, content)

            result = format_meal_plan(vault, date(2026, 5, 4))

        assert result is not None
        assert "—" in result

    def test_no_plan_file_returns_none(self) -> None:
        """When no plan file exists, returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            (vault / "reference" / "meal-planning" / "plans").mkdir(parents=True)

            result = format_meal_plan(vault, date(2026, 5, 4))

        assert result is None

    def test_next_week_shows_following_week(self) -> None:
        """!mealplan next shows the week AFTER the current week."""
        current_content = """# Week of May 4, 2026

## Monday May 4
**Supper:** This Week Meal
🧊 Defrost: | 🔪 Prep: 
"""
        next_content = """# Week of May 11, 2026

## Monday May 11
**Supper:** Next Week Special
🧊 Defrost: | 🔪 Prep: 
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plan_dir = vault / "reference" / "meal-planning" / "plans"
            plan_dir.mkdir(parents=True)
            (plan_dir / "2026-05-04.md").write_text(current_content)
            (plan_dir / "2026-05-11.md").write_text(next_content)

            # Today is May 4 (Mon); "next" shows the May 11 week
            result = format_meal_plan(vault, date(2026, 5, 4), next=True)

        assert result is not None
        assert "Week of May 11" in result
        assert "Next Week Special" in result

    def test_date_arg_shows_week_containing_that_date(self) -> None:
        """A date arg shows the week containing that date."""
        content = """# Week of June 1, 2026

## Monday June 1
**Supper:** Monday Meal
🧊 Defrost: | 🔪 Prep: 

## Tuesday June 2
**Supper:** Tuesday Meal
🧊 Defrost: | 🔪 Prep: 
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = self._vault_with_plan(tmpdir, content, monday="2026-06-01")

            # Show week containing June 4 (in June 1 week)
            result = format_meal_plan(vault, date(2026, 6, 4))

        assert result is not None
        assert "Week of June 1" in result
        assert "Monday Meal" in result
