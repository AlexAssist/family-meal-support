"""Tests for update_plan_meal_link — updating a day link in an existing plan file."""
from datetime import date
from pathlib import Path
import tempfile

import pytest

from obsidian.vault import update_plan_meal_link, write_meal_plan
from meal_plan import MealPlan, PlannedMeal


def test_update_plan_meal_link_adds_link_to_plain_recipe(tmp_path: Path) -> None:
    """A day with plain text recipe gets a link added by update_plan_meal_link."""
    plan_file = tmp_path / "reference" / "meal-planning" / "plans" / "2026-05-04.md"
    plan_file.parent.mkdir(parents=True)

    # Write a plan with Monday having no link
    plan_file.write_text(
        "# Week of May 4, 2026\n\n"
        "## Monday May 4\n"
        "**Supper:** Chicken Tacos\n"
        "🧊 Defrost: | 🔪 Prep:\n\n"
        "## Tuesday May 5\n"
        "**Supper:** Pasta\n"
        "🧊 Defrost: | 🔪 Prep:\n"
    )

    updated = update_plan_meal_link(plan_file, date(2026, 5, 4), "https://www.allrecipes.com/chicken-tacos")

    assert updated is True
    content = plan_file.read_text()
    # The Monday line should now have a link
    assert "[Chicken Tacos](https://www.allrecipes.com/chicken-tacos)" in content
    # Tuesday should be unchanged
    assert "Pasta" in content
    assert "[Pasta](" not in content


def test_update_plan_meal_link_updates_existing_link(tmp_path: Path) -> None:
    """A day that already has a link gets it replaced."""
    plan_file = tmp_path / "reference" / "meal-planning" / "plans" / "2026-05-04.md"
    plan_file.parent.mkdir(parents=True)

    plan_file.write_text(
        "# Week of May 4, 2026\n\n"
        "## Monday May 4\n"
        "**Supper:** [Chicken Tacos](https://old-site.com/tacos)\n"
        "🧊 Defrost: | 🔪 Prep:\n"
    )

    updated = update_plan_meal_link(plan_file, date(2026, 5, 4), "https://www.allrecipes.com/chicken-tacos")

    assert updated is True
    content = plan_file.read_text()
    assert "https://www.allrecipes.com/chicken-tacos" in content
    assert "old-site.com" not in content


def test_update_plan_meal_link_returns_false_for_nonexistent_day(tmp_path: Path) -> None:
    """Returns False when the day doesn't exist in the plan file."""
    plan_file = tmp_path / "reference" / "meal-planning" / "plans" / "2026-05-04.md"
    plan_file.parent.mkdir(parents=True)

    plan_file.write_text("# Week of May 4, 2026\n\n## Monday May 4\n**Supper:** Tacos\n")

    updated = update_plan_meal_link(plan_file, date(2026, 5, 10), "https://example.com/sunday")

    assert updated is False


def test_update_plan_meal_link_handles_iso_date_header(tmp_path: Path) -> None:
    """Works with the new ISO-date header format (e.g. ## Monday (2026-05-04))."""
    plan_file = tmp_path / "reference" / "meal-planning" / "plans" / "2026-05-04.md"
    plan_file.parent.mkdir(parents=True)

    plan_file.write_text(
        "# Week of May 4, 2026\n\n"
        "## Monday (2026-05-04)\n"
        "**Supper:** Salmon\n"
        "🧊 Defrost: | 🔪 Prep:\n"
    )

    updated = update_plan_meal_link(plan_file, date(2026, 5, 4), "https://example.com/salmon")

    assert updated is True
    assert "[Salmon](https://example.com/salmon)" in plan_file.read_text()