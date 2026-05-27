"""Tests for the !addmeal command — add a meal to a plan day."""
from datetime import date
from pathlib import Path
import pytest

from commands.addmeal import add_meal_to_plan
from meal_plan import MealPlan, PlannedMeal
from recipes.lookup import RecipeNotFoundError, MultipleCandidatesError


class FakeRecipeStore:
    """Fake store for testing addmeal."""

    def __init__(self, recipes: dict[str, "Recipe"]) -> None:
        self._recipes = recipes

    def get(self, name: str) -> "Recipe | None":
        return self._recipes.get(name.lower())

    def list_all(self) -> list[tuple[str, "Recipe"]]:
        return list(self._recipes.items())


def make_recipe(name: str, link: str | None = None) -> "Recipe":
    from shared.types import Recipe
    return Recipe(name=name, ingredients=[], link=link)


class TestAddMealToPlan:
    """add_meal_to_plan wires day parsing + recipe lookup + plan write."""

    def _make_plan(self, tmp_path: Path, meals: dict[str, str]) -> Path:
        """Create a plan file with given meals (date str -> recipe name).

        Keys are "Monday May 4" format (as written to the plan file).
        """
        vault = tmp_path / "vault"
        plan_dir = vault / "reference" / "meal-planning" / "plans"
        plan_dir.mkdir(parents=True)

        # All in same week (May 4-8 2026 = Mon-Fri)
        plan_file = plan_dir / "2026-05-04.md"
        lines = ["# Week of May 4, 2026\n"]
        day_names = ["Monday May 4", "Tuesday May 5", "Wednesday May 6", "Thursday May 7", "Friday May 8"]
        for day_name in day_names:
            recipe = meals.get(day_name, "")
            lines.append(f"## {day_name}\n")
            lines.append(f"**Supper:** {recipe}\n")
            lines.append("🧊 Defrost: | 🔪 Prep:\n")
        plan_file.write_text("".join(lines))
        return vault

    def test_add_meal_exact_match(self, tmp_path: Path):
        """Exact recipe filename match → meal added to plan."""
        store = FakeRecipeStore({
            "baked-salmon-with-broccoli-and-garlic-pasta": make_recipe("Baked Salmon with Broccoli and Garlic Pasta", "https://example.com/salmon"),
        })
        vault = self._make_plan(tmp_path, {})

        new_meal, was_overwrite = add_meal_to_plan(
            vault=vault,
            day_spec="Monday",
            meal_name="baked-salmon-with-broccoli-and-garlic-pasta",
            recipe_store=store,
        )

        assert new_meal.recipe_name == "Baked Salmon with Broccoli and Garlic Pasta"
        assert new_meal.recipe_link == "https://example.com/salmon"

    def test_add_meal_substring_match(self, tmp_path: Path):
        """Substring match → meal added to plan."""
        store = FakeRecipeStore({
            "baked-salmon-with-broccoli-and-garlic-pasta": make_recipe("Baked Salmon with Broccoli and Garlic Pasta"),
        })
        vault = self._make_plan(tmp_path, {})

        new_meal, _ = add_meal_to_plan(
            vault=vault,
            day_spec="Monday",
            meal_name="salmon",
            recipe_store=store,
        )

        assert "Salmon" in new_meal.recipe_name

    def test_add_meal_date_format(self, tmp_path: Path):
        """YYYY-MM-DD day spec works."""
        store = FakeRecipeStore({
            "beef-donair": make_recipe("Beef Donair"),
        })
        vault = self._make_plan(tmp_path, {})

        new_meal, _ = add_meal_to_plan(
            vault=vault,
            day_spec="2026-05-04",
            meal_name="beef-donair",
            recipe_store=store,
        )

        assert new_meal.recipe_name == "Beef Donair"

    def test_add_meal_colon_syntax(self, tmp_path: Path):
        """Tuesday: Meal Name syntax works."""
        store = FakeRecipeStore({
            "beef-donair": make_recipe("Beef Donair"),
        })
        vault = self._make_plan(tmp_path, {})

        new_meal, _ = add_meal_to_plan(
            vault=vault,
            day_spec="Tuesday:",
            meal_name="beef-donair",
            recipe_store=store,
        )

        assert new_meal.recipe_name == "Beef Donair"

    def test_add_meal_multiple_candidates_raises(self, tmp_path: Path):
        """Multiple substring matches raises MultipleCandidatesError."""
        store = FakeRecipeStore({
            "chicken-tacos": make_recipe("Chicken Tacos"),
            "beef-tacos": make_recipe("Beef Tacos"),
        })
        vault = self._make_plan(tmp_path, {})

        with pytest.raises(MultipleCandidatesError) as exc_info:
            add_meal_to_plan(vault, "Friday", "tacos", store)
        assert set(exc_info.value.candidates) == {"chicken-tacos", "beef-tacos"}

    def test_add_meal_not_found_raises(self, tmp_path: Path):
        """Zero matches raises RecipeNotFoundError."""
        store = FakeRecipeStore({
            "beef-donair": make_recipe("Beef Donair"),
        })
        vault = self._make_plan(tmp_path, {})

        with pytest.raises(RecipeNotFoundError):
            add_meal_to_plan(vault, "Monday", "pizza", store)

    def test_overwrite_existing_meal_returns_overwrite_info(self, tmp_path: Path):
        """Adding to a day that already has a meal returns warning info."""
        store = FakeRecipeStore({
            "beef-donair": make_recipe("Beef Donair"),
            "baked-salmon-with-broccoli-and-garlic-pasta": make_recipe("Baked Salmon"),
        })
        vault = self._make_plan(tmp_path, {"Monday May 4": "Beef Donair"})

        # Adding a different meal to a day that already has one
        # today=May 4 is the Monday of the plan week so Monday resolves to 2026-05-04
        new_meal, was_overwrite = add_meal_to_plan(
            vault=vault,
            day_spec="Monday",
            meal_name="baked-salmon-with-broccoli-and-garlic-pasta",
            recipe_store=store,
            today=date(2026, 5, 4),
        )

        assert was_overwrite is True
        assert new_meal.recipe_name == "Baked Salmon"
