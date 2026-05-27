"""Tests for the Obsidian vault adapter."""
from datetime import date
from pathlib import Path
import tempfile

import pytest

from meal_plan import MealPlan
from obsidian.vault import read_meal_plan, write_meal_plan


class TestReadMealPlan:
    """read_meal_plan parses a weekly plan Markdown file correctly."""

    def test_parses_a_real_plan_file(self) -> None:
        """A plan file with planned meals returns a MealPlan with all days."""
        content = """# Week of May 4, 2026

## Monday May 4
**Supper:** 
🧊 Defrost: | 🔪 Prep: 

## Tuesday May 5
**Supper:** 
🧊 Defrost: | 🔪 Prep: 

## Wednesday May 6
**Supper:** [Korean Ground Chicken Lettuce Wraps]()
🧊 Defrost: | 🔪 Prep: 

## Thursday May 7
**Supper:** Hamburgers
🧊 Defrost: | 🔪 Prep: 

## Friday May 8
**Supper:** Taco Salad
🧊 Defrost: | 🔪 Prep: 

## Saturday May 9
**Supper:** 
🧊 Defrost: | 🔪 Prep: 

## Sunday May 10
**Supper:** Donor Kebabs
🧊 Defrost: | 🔪 Prep: 
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_file = Path(tmpdir) / "2026-05-04.md"
            plan_file.write_text(content)

            result = read_meal_plan(plan_file)

        assert result.week_start == date(2026, 5, 4)
        assert len(result.days) == 7

        # Wednesday — Korean Ground Chicken with empty link
        wed = result.days[2]
        assert wed.date == date(2026, 5, 6)
        assert wed.recipe_name == "Korean Ground Chicken Lettuce Wraps"
        assert wed.recipe_link is None

        # Thursday — Hamburger, no link
        thu = result.days[3]
        assert thu.date == date(2026, 5, 7)
        assert thu.recipe_name == "Hamburgers"
        assert thu.recipe_link is None

        # Sunday — Donor Kebabs
        sun = result.days[6]
        assert sun.date == date(2026, 5, 10)
        assert sun.recipe_name == "Donor Kebabs"

    def test_parses_recipe_link(self) -> None:
        """A recipe name with a Markdown link extracts the link."""
        content = """# Week of June 1, 2026

## Monday June 1
**Supper:** [Pasta Primavera](https://example.com/pasta)
🧊 Defrost: | 🔪 Prep: 
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_file = Path(tmpdir) / "2026-06-01.md"
            plan_file.write_text(content)

            result = read_meal_plan(plan_file)

        assert result.days[0].recipe_name == "Pasta Primavera"
        assert result.days[0].recipe_link == "https://example.com/pasta"

    def test_missing_file_returns_none(self) -> None:
        """When the plan file doesn't exist, read_meal_plan returns None gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = read_meal_plan(Path(tmpdir) / "2026-05-04.md")

        assert result is None
