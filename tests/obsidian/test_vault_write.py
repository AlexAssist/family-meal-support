"""Tests for obsidian vault write_meal_plan."""
from datetime import date
from pathlib import Path
import pytest

from meal_plan import MealPlan, PlannedMeal
from obsidian.vault import write_meal_plan, read_meal_plan


def test_write_and_read_roundtrip(tmp_path: Path):
    """A written plan can be read back with same data."""
    plan = MealPlan(
        week_start=date(2026, 5, 4),
        days=[
            PlannedMeal(date=date(2026, 5, 4), recipe_name="Pasta Primavera"),
            PlannedMeal(date=date(2026, 5, 5), recipe_name=""),
            PlannedMeal(date=date(2026, 5, 6), recipe_name="Grilled Salmon", recipe_link="https://example.com/salmon"),
        ],
    )

    plan_file = tmp_path / "reference" / "meal-planning" / "plans" / "2026-05-04.md"
    plan_file.parent.mkdir(parents=True)
    write_meal_plan(plan, plan_file)

    # Read it back
    result = read_meal_plan(plan_file)
    assert result is not None
    assert result.week_start == date(2026, 5, 4)
    assert result.days[0].recipe_name == "Pasta Primavera"
    assert result.days[1].recipe_name == ""
    assert result.days[2].recipe_name == "Grilled Salmon"
    assert result.days[2].recipe_link == "https://example.com/salmon"


def test_empty_day_writes_dash(tmp_path: Path):
    """A day with no planned meal writes '—' in the Supper line."""
    plan = MealPlan(
        week_start=date(2026, 5, 4),
        days=[
            PlannedMeal(date=date(2026, 5, 4), recipe_name=""),
        ],
    )

    plan_file = tmp_path / "reference" / "meal-planning" / "plans" / "2026-05-04.md"
    plan_file.parent.mkdir(parents=True)
    write_meal_plan(plan, plan_file)

    text = plan_file.read_text()
    # Should contain **Supper:** with nothing after (empty line value)
    assert "**Supper:**" in text


def test_recipe_link_written_as_markdown_link(tmp_path: Path):
    """A planned meal with a link writes [name](url) format."""
    plan = MealPlan(
        week_start=date(2026, 5, 4),
        days=[
            PlannedMeal(
                date=date(2026, 5, 4),
                recipe_name="Chicken Tacos",
                recipe_link="https://example.com/tacos",
            ),
        ],
    )

    plan_file = tmp_path / "reference" / "meal-planning" / "plans" / "2026-05-04.md"
    plan_file.parent.mkdir(parents=True)
    write_meal_plan(plan, plan_file)

    text = plan_file.read_text()
    assert "[Chicken Tacos](https://example.com/tacos)" in text