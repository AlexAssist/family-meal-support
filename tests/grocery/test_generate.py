"""Tests for grocery list generation."""
from __future__ import annotations

from datetime import date

import pytest

from shared.types import (
    GroceryCategory,
    GroceryItem,
    GroceryList,
    Ingredient,
    MealPlan,
    Pantry,
    PantryItem,
    PlannedMeal,
    Recipe,
)
from grocery.generate import generate_grocery_list


class InMemoryRecipeStore:
    """Fake recipe store for testing."""

    def __init__(self, recipes: dict[str, Recipe]) -> None:
        self._recipes = {k.lower(): v for k, v in recipes.items()}

    def get(self, key: str) -> Recipe | None:
        return self._recipes.get(key.lower())

    def list_all(self) -> list[tuple[str, Recipe]]:
        return list(self._recipes.items())


# -------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------

@pytest.fixture
def store_empty() -> InMemoryRecipeStore:
    return InMemoryRecipeStore({})


@pytest.fixture
def store_one_recipe() -> InMemoryRecipeStore:
    return InMemoryRecipeStore({
        "Chicken Tacos": Recipe(
            name="Chicken Tacos",
            ingredients=[
                Ingredient(name="chicken breast", quantity="1", unit="lb", category=GroceryCategory.MEAT_SEAFOOD),
                Ingredient(name="taco shells", quantity="8", unit="pcs", category=GroceryCategory.PANTRY),
                Ingredient(name="cheddar cheese", quantity="1", unit="cup", category=GroceryCategory.DAIRY),
                Ingredient(name="lettuce", quantity="1", unit="cup", category=GroceryCategory.PRODUCE),
                Ingredient(name="tomatoes", quantity="2", unit="medium", category=GroceryCategory.PRODUCE),
            ],
        ),
    })


@pytest.fixture
def store_two_shared() -> InMemoryRecipeStore:
    """Two recipes that share some ingredients (chicken breast appears in both)."""
    return InMemoryRecipeStore({
        "Chicken Tacos": Recipe(
            name="Chicken Tacos",
            ingredients=[
                Ingredient(name="chicken breast", quantity="1", unit="lb", category=GroceryCategory.MEAT_SEAFOOD),
                Ingredient(name="taco shells", quantity="8", unit="pcs", category=GroceryCategory.PANTRY),
                Ingredient(name="cheddar cheese", quantity="1", unit="cup", category=GroceryCategory.DAIRY),
            ],
        ),
        "Grilled Chicken": Recipe(
            name="Grilled Chicken",
            ingredients=[
                Ingredient(name="chicken breast", quantity="2", unit="lb", category=GroceryCategory.MEAT_SEAFOOD),
                Ingredient(name="olive oil", quantity="2", unit="tbsp", category=GroceryCategory.CONDIMENTS),
                Ingredient(name="garlic", quantity="3", unit="cloves", category=GroceryCategory.PRODUCE),
            ],
        ),
    })


@pytest.fixture
def empty_pantry() -> Pantry:
    return Pantry(items=[])


# -------------------------------------------------------------------
# Test: empty plan → graceful message
# -------------------------------------------------------------------

def test_empty_plan_returns_empty_grocery_list(empty_pantry, store_empty):
    """An empty meal plan with no days produces an empty grocery list."""
    plan = MealPlan(week_start=date(2026, 6, 1), days=[])
    result = generate_grocery_list(plan, empty_pantry, store_empty)
    assert isinstance(result, GroceryList)
    assert len(result.items) == 0


def test_plan_with_no_recipe_matched(empty_pantry, store_empty):
    """A plan day with no matching recipe produces no ingredients."""
    plan = MealPlan(week_start=date(2026, 6, 1), days=[
        PlannedMeal(date=date(2026, 6, 1), recipe_name=""),
        PlannedMeal(date=date(2026, 6, 2), recipe_name="Unknown Dish"),
    ])
    result = generate_grocery_list(plan, empty_pantry, store_empty)
    assert len(result.items) == 0


# -------------------------------------------------------------------
# Test: basic grocery list from 7-day plan
# -------------------------------------------------------------------

def test_generates_grocery_list_from_7day_plan(empty_pantry, store_one_recipe):
    """A 7-day plan with one known recipe produces correct grocery list."""
    plan = MealPlan(week_start=date(2026, 6, 1), days=[
        PlannedMeal(date=date(2026, 6, 1), recipe_name="Chicken Tacos"),
        PlannedMeal(date=date(2026, 6, 2), recipe_name=""),
        PlannedMeal(date=date(2026, 6, 3), recipe_name=""),
        PlannedMeal(date=date(2026, 6, 4), recipe_name=""),
        PlannedMeal(date=date(2026, 6, 5), recipe_name=""),
        PlannedMeal(date=date(2026, 6, 6), recipe_name=""),
        PlannedMeal(date=date(2026, 6, 7), recipe_name=""),
    ])
    result = generate_grocery_list(plan, empty_pantry, store_one_recipe)

    # Should have 5 ingredients
    item_names = {item.name.lower() for item in result.items}
    assert "chicken breast" in item_names
    assert "taco shells" in item_names
    assert "cheddar cheese" in item_names
    assert "lettuce" in item_names
    assert "tomatoes" in item_names


# -------------------------------------------------------------------
# Test: duplicate ingredients merged across meals
# -------------------------------------------------------------------

def test_duplicate_ingredients_merged_across_meals(empty_pantry, store_two_shared):
    """Same ingredient in 2 meals → single entry (staples excluded, just recipe ingredients)."""
    plan = MealPlan(week_start=date(2026, 6, 1), days=[
        PlannedMeal(date=date(2026, 6, 1), recipe_name="Chicken Tacos"),
        PlannedMeal(date=date(2026, 6, 2), recipe_name="Grilled Chicken"),
        PlannedMeal(date=date(2026, 6, 3), recipe_name=""),
    ])
    result = generate_grocery_list(plan, empty_pantry, store_two_shared)

    # Should have chicken breast once (merged), not twice
    chicken_items = [i for i in result.items if i.name.lower() == "chicken breast"]
    assert len(chicken_items) == 1

    # 5 unique recipe ingredients (chicken breast, taco shells, cheddar cheese,
    # olive oil, garlic) — no staples since all are in empty pantry
    # But staples are ALWAYS added when plan has meals, so count those too
    recipe_items = [i for i in result.items if i.source_recipe != "staples"]
    assert len(recipe_items) == 5


# -------------------------------------------------------------------
# Test: pantry items subtracted (case-insensitive)
# -------------------------------------------------------------------

def test_pantry_items_subtracted_case_insensitive(store_one_recipe):
    """Items in the pantry are excluded from the grocery list (case-insensitive)."""
    pantry = Pantry(items=[
        PantryItem(name="CHICKEN BREAST", location="fridge"),
        PantryItem(name="taco shells", location="pantry"),
    ])
    plan = MealPlan(week_start=date(2026, 6, 1), days=[
        PlannedMeal(date=date(2026, 6, 1), recipe_name="Chicken Tacos"),
    ])
    result = generate_grocery_list(plan, pantry, store_one_recipe)

    item_names = {item.name.lower() for item in result.items}
    assert "chicken breast" not in item_names
    assert "taco shells" not in item_names
    # cheddar cheese, lettuce, tomatoes should still be there
    assert "cheddar cheese" in item_names
    assert "lettuce" in item_names
    assert "tomatoes" in item_names


def test_pantry_item_partial_match_not_subtracted(store_one_recipe):
    """Pantry "chicken" doesn't subtract "chicken breast" (not a full match)."""
    pantry = Pantry(items=[
        PantryItem(name="chicken", location="freezer"),  # partial match
    ])
    plan = MealPlan(week_start=date(2026, 6, 1), days=[
        PlannedMeal(date=date(2026, 6, 1), recipe_name="Chicken Tacos"),
    ])
    result = generate_grocery_list(plan, pantry, store_one_recipe)

    item_names = {item.name.lower() for item in result.items}
    assert "chicken breast" in item_names  # still appears since "chicken" ≠ "chicken breast"


# -------------------------------------------------------------------
# Test: empty pantry → all ingredients listed
# -------------------------------------------------------------------

def test_empty_pantry_lists_all_ingredients(store_one_recipe, empty_pantry):
    """An empty pantry means no subtraction, so all recipe ingredients appear (plus staples)."""
    plan = MealPlan(week_start=date(2026, 6, 1), days=[
        PlannedMeal(date=date(2026, 6, 1), recipe_name="Chicken Tacos"),
    ])
    result = generate_grocery_list(plan, empty_pantry, store_one_recipe)

    # 5 ingredients from Chicken Tacos recipe
    recipe_items = [i for i in result.items if i.source_recipe != "staples"]
    assert len(recipe_items) == 5
    assert result.has_item("chicken breast")
    assert result.has_item("taco shells")
    assert result.has_item("cheddar cheese")
    assert result.has_item("lettuce")
    assert result.has_item("tomatoes")


# -------------------------------------------------------------------
# Test: category grouping
# -------------------------------------------------------------------

def test_items_grouped_by_category(store_one_recipe, empty_pantry):
    """Items are grouped under their GroceryCategory."""
    plan = MealPlan(week_start=date(2026, 6, 1), days=[
        PlannedMeal(date=date(2026, 6, 1), recipe_name="Chicken Tacos"),
    ])
    result = generate_grocery_list(plan, empty_pantry, store_one_recipe)

    categories = {item.category for item in result.items}
    assert GroceryCategory.MEAT_SEAFOOD in categories
    assert GroceryCategory.PANTRY in categories
    assert GroceryCategory.DAIRY in categories
    assert GroceryCategory.PRODUCE in categories


def test_items_sorted_alphabetically_within_category(store_one_recipe, empty_pantry):
    """Items within each category are sorted A-Z."""
    plan = MealPlan(week_start=date(2026, 6, 1), days=[
        PlannedMeal(date=date(2026, 6, 1), recipe_name="Chicken Tacos"),
    ])
    result = generate_grocery_list(plan, empty_pantry, store_one_recipe)

    # Within PRODUCE category: lettuce, tomatoes
    produce_items = [i.name for i in result.items if i.category == GroceryCategory.PRODUCE]
    assert produce_items == sorted(produce_items)


# -------------------------------------------------------------------
# Test: GroceryList helper methods
# -------------------------------------------------------------------

def test_has_item_case_insensitive(store_one_recipe, empty_pantry):
    """has_item is case-insensitive."""
    plan = MealPlan(week_start=date(2026, 6, 1), days=[
        PlannedMeal(date=date(2026, 6, 1), recipe_name="Chicken Tacos"),
    ])
    result = generate_grocery_list(plan, empty_pantry, store_one_recipe)

    assert result.has_item("CHICKEN BREAST")
    assert result.has_item("Chicken Breast")
    assert result.has_item("chicken breast")
    assert not result.has_item("nonexistent item")


def test_category_of_returns_correct_category(store_one_recipe, empty_pantry):
    """category_of returns the correct category for a named item."""
    plan = MealPlan(week_start=date(2026, 6, 1), days=[
        PlannedMeal(date=date(2026, 6, 1), recipe_name="Chicken Tacos"),
    ])
    result = generate_grocery_list(plan, empty_pantry, store_one_recipe)

    assert result.category_of("chicken breast") == GroceryCategory.MEAT_SEAFOOD
    assert result.category_of("taco shells") == GroceryCategory.PANTRY
    assert result.category_of("cheddar cheese") == GroceryCategory.DAIRY
    assert result.category_of("lettuce") == GroceryCategory.PRODUCE


# -------------------------------------------------------------------
# Test: missing staples added to grocery list
# -------------------------------------------------------------------

def test_missing_staples_added(store_one_recipe, empty_pantry):
    """Staples not in pantry appear on the grocery list."""
    pantry = Pantry(items=[
        PantryItem(name="eggs", location="fridge"),  # in staples, in pantry → not added
        PantryItem(name="butter", location="fridge"),  # in staples, in pantry → not added
    ])
    plan = MealPlan(week_start=date(2026, 6, 1), days=[
        PlannedMeal(date=date(2026, 6, 1), recipe_name="Chicken Tacos"),
    ])
    staples = ["eggs", "butter", "milk", "bread"]
    result = generate_grocery_list(plan, pantry, store_one_recipe, staples=staples)

    # Eggs and butter are in pantry → not added
    # Milk and bread are missing from pantry → should be added
    staple_items = [i for i in result.items if i.source_recipe == "staples"]
    assert len(staple_items) == 2
    staple_names = {i.name.lower() for i in staple_items}
    assert "milk" in staple_names
    assert "bread" in staple_names
    assert "eggs" not in staple_names
    assert "butter" not in staple_names


def test_no_staples_when_none_provided(store_one_recipe, empty_pantry):
    """When staples is None, no staples are added to the grocery list."""
    plan = MealPlan(week_start=date(2026, 6, 1), days=[
        PlannedMeal(date=date(2026, 6, 1), recipe_name="Chicken Tacos"),
    ])
    result = generate_grocery_list(plan, empty_pantry, store_one_recipe)

    staple_items = [i for i in result.items if i.source_recipe == "staples"]
    assert len(staple_items) == 0