"""Tests for recipe lookup: find_recipe()."""
from datetime import date

from meal_plan import MealPlan, PlannedMeal
from recipes.lookup import find_recipe, RecipeNotFoundError, MultipleCandidatesError


class InMemoryRecipeStore:
    """Fake recipe store for testing."""

    def __init__(self, recipes: dict[str, "Recipe"]) -> None:
        self._recipes = recipes

    def get(self, name: str) -> "Recipe | None":
        """Return recipe by exact lowercase name, or None."""
        key = name.lower()
        return self._recipes.get(key)

    def list_all(self) -> list[tuple[str, "Recipe"]]:
        """Return all (lowercase_key, recipe) pairs."""
        return list(self._recipes.items())



# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def make_recipe(name: str) -> "Recipe":
    from shared.types import Recipe
    return Recipe(name=name, ingredients=[])


# -------------------------------------------------------------------
# Test: exact match on lowercase filename
# -------------------------------------------------------------------

def test_exact_match_returns_recipe():
    """Lowercase filename exact match → recipe found."""
    store = InMemoryRecipeStore({
        "baked-salmon-with-broccoli-and-garlic-pasta": make_recipe("Baked Salmon with Broccoli and Garlic Pasta"),
        "beef-donair": make_recipe("Beef Donair"),
        "breakfast-burritos-delish": make_recipe("Breakfast Burritos Delish"),
    })

    # Exact match on the lowercase filename form
    recipe = find_recipe("baked-salmon-with-broccoli-and-garlic-pasta", store)
    assert recipe is not None
    assert recipe.name == "Baked Salmon with Broccoli and Garlic Pasta"


def test_exact_match_case_insensitive():
    """Exact match is case-insensitive."""
    store = InMemoryRecipeStore({
        "beef-donair": make_recipe("Beef Donair"),
    })

    recipe = find_recipe("Beef-Donair", store)
    assert recipe is not None
    assert recipe.name == "Beef Donair"


def test_no_exact_match_raises_not_found():
    """No exact match raises RecipeNotFoundError."""
    store = InMemoryRecipeStore({
        "beef-donair": make_recipe("Beef Donair"),
    })

    try:
        find_recipe("grilled-salmon", store)
        assert False, "Expected RecipeNotFoundError"
    except RecipeNotFoundError as e:
        assert "grilled-salmon" in str(e)


class TestSubstringMatch:
    """Tier 2: substring match when no exact match."""

    def test_single_substring_match_returns_recipe(self):
        """Exactly one filename contains search term → recipe returned."""
        store = InMemoryRecipeStore({
            "baked-salmon-with-broccoli-and-garlic-pasta": make_recipe("Baked Salmon with Broccoli and Garlic Pasta"),
            "beef-donair": make_recipe("Beef Donair"),
            "breakfast-burritos-delish": make_recipe("Breakfast Burritos Delish"),
        })

        # "salmon" appears in exactly one filename
        recipe = find_recipe("salmon", store)
        assert recipe is not None
        assert recipe.name == "Baked Salmon with Broccoli and Garlic Pasta"

    def test_case_insensitive_substring_match(self):
        """Substring search is case-insensitive."""
        store = InMemoryRecipeStore({
            "mcchicken-smash-tacos": make_recipe("McChicken Smash Tacos"),
        })

        recipe = find_recipe("TACOS", store)
        assert recipe is not None
        assert recipe.name == "McChicken Smash Tacos"

    def test_multiple_substring_matches_raises_multiple_candidates(self):
        """Search term in multiple filenames raises MultipleCandidatesError."""
        store = InMemoryRecipeStore({
            "chicken-tacos": make_recipe("Chicken Tacos"),
            "beef-tacos": make_recipe("Beef Tacos"),
            "grilled-salmon": make_recipe("Grilled Salmon"),
        })

        try:
            find_recipe("tacos", store)
            assert False, "Expected MultipleCandidatesError"
        except MultipleCandidatesError as e:
            assert e.name == "tacos"
            assert set(e.candidates) == {"chicken-tacos", "beef-tacos"}

    def test_zero_substring_matches_raises_not_found(self):
        """No filename contains search term → RecipeNotFoundError."""
        store = InMemoryRecipeStore({
            "beef-donair": make_recipe("Beef Donair"),
        })

        try:
            find_recipe("pizza", store)
            assert False, "Expected RecipeNotFoundError"
        except RecipeNotFoundError as e:
            assert "pizza" in str(e)
