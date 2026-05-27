"""Tests for the !tonight command."""
from datetime import date
from pathlib import Path
import tempfile

import pytest

from commands.tonight import get_tonight_meal


class TestGetTonightMeal:
    """get_tonight_meal returns the planned meal for today."""

    def test_returns_planned_meal_when_found(self) -> None:
        """When a meal is planned for tonight, returns the PlannedMeal."""
        content = """# Week of May 4, 2026

## Monday May 4
**Supper:** [Korean Ground Chicken Lettuce Wraps](https://example.com/korean)
🧊 Defrost: | 🔪 Prep: 

## Tuesday May 5
**Supper:** Pasta Primavera
🧊 Defrost: | 🔪 Prep: 
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plan_dir = vault / "reference" / "meal-planning" / "plans"
            plan_dir.mkdir(parents=True)
            (plan_dir / "2026-05-04.md").write_text(content)

            # Simulate "today" being Tuesday May 5
            result = get_tonight_meal(vault, today=date(2026, 5, 5))

        assert result is not None
        assert result.recipe_name == "Pasta Primavera"
        assert result.date == date(2026, 5, 5)
        assert result.recipe_link is None

    def test_returns_none_when_no_meal_planned(self) -> None:
        """When the slot is empty, returns None."""
        content = """# Week of May 4, 2026

## Monday May 4
**Supper:** [Korean Ground Chicken Lettuce Wraps]()
🧊 Defrost: | 🔪 Prep: 

## Tuesday May 5
**Supper:** 
🧊 Defrost: | 🔪 Prep: 
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plan_dir = vault / "reference" / "meal-planning" / "plans"
            plan_dir.mkdir(parents=True)
            (plan_dir / "2026-05-04.md").write_text(content)

            result = get_tonight_meal(vault, today=date(2026, 5, 5))

        assert result is None

    def test_returns_none_when_no_plan_file(self) -> None:
        """When no plan file exists for the week, returns None gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            # No plan file written — directory is empty
            result = get_tonight_meal(vault, today=date(2026, 5, 5))

        assert result is None

    def test_returns_none_when_today_not_in_any_week(self) -> None:
        """When today falls in a week with no plan file, returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plan_dir = vault / "reference" / "meal-planning" / "plans"
            plan_dir.mkdir(parents=True)
            # Only a plan for May 4 week, today is June 1
            (plan_dir / "2026-05-04.md").write_text("# Week of May 4, 2026\n")

            result = get_tonight_meal(vault, today=date(2026, 6, 1))

        assert result is None
