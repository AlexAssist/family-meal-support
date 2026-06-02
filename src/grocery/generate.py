"""Grocery list generation — deep module.

One public function: generate_grocery_list().
All complexity (ingredient merge, pantry subtract, staples, grouping, sorting)
lives behind it.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

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
from recipes.lookup import RecipeStore, find_recipe, RecipeNotFoundError, MultipleCandidatesError


# -------------------------------------------------------------------
# Public interface
# -------------------------------------------------------------------

def generate_grocery_list(
    plan: MealPlan,
    pantry: Pantry,
    recipe_store: RecipeStore,
    staples: list[str] | None = None,
) -> GroceryList:
    """Generate a complete, category-grouped grocery list from a meal plan.

    Takes a meal plan, pantry inventory, recipe store, and optional staples
    list — and produces a grocery list covering all ingredients needed for
    the week, minus what you already have, plus any missing staples.

    Processing pipeline (all private):
      1. Extract all ingredients from every planned recipe
      2. Merge duplicate ingredients across meals (case-insensitive)
      3. Subtract items already in pantry (case-insensitive)
      4. Add any staples missing from pantry
      5. Group by GroceryCategory, sort A-Z within each category

    Parameters:
        plan: The weekly meal plan.
        pantry: Current pantry inventory.
        recipe_store: Source of Recipe objects for each planned meal.
        staples: Optional list of staple item names. Staples not found
            in the pantry are added to the grocery list. If None or
            empty, no staples are added.

    Returns:
        GroceryList with items grouped and sorted.
    """
    # 1. Collect all ingredients from planned meals
    all_ingredients: list[tuple[str, Ingredient]] = []  # (normalized_name, Ingredient)
    for meal in plan.days:
        if not meal.recipe_name.strip():
            continue
        try:
            recipe = find_recipe(meal.recipe_name, recipe_store)
        except (RecipeNotFoundError, MultipleCandidatesError):
            # No matching recipe file (or multiple ambiguous matches) — skip gracefully
            continue
        for ingredient in recipe.ingredients:
            normalized = _normalize(ingredient.name)
            all_ingredients.append((normalized, ingredient))

    # If no meals planned, return empty list (graceful no-op)
    if not all_ingredients:
        return GroceryList(week_start=plan.week_start, items=[])

    # 2. Merge duplicates
    merged = _merge_ingredients(all_ingredients)

    # 3. Subtract pantry items (case-insensitive)
    pantry_names = {_normalize(p.name) for p in pantry.items}
    filtered = [(n, ing) for n, ing in merged if n not in pantry_names]

    # 4. Add missing staples (only when there are planned meals)
    staple_names = staples or []
    staple_items = _build_staples_list(pantry_names, staple_names)

    # 5. Build GroceryItem list
    items: list[GroceryItem] = []
    for normalized_name, ingredient in filtered:
        items.append(
            GroceryItem(
                name=ingredient.name,  # preserve original casing
                quantity=ingredient.quantity,
                unit=ingredient.unit,
                category=ingredient.category or GroceryCategory.OTHER,
                source_recipe=_source_recipe(normalized_name, plan, recipe_store),
            )
        )

    # Add staple items (quantity None, category based on staple mapping)
    for staple_name in staple_items:
        items.append(
            GroceryItem(
                name=staple_name,
                quantity=None,
                unit=None,
                category=_category_for_staple(staple_name),
                source_recipe="staples",
            )
        )

    # 6. Group by category and sort A-Z within each group
    grouped: dict[GroceryCategory, list[GroceryItem]] = defaultdict(list)
    for item in items:
        grouped[item.category].append(item)

    sorted_items: list[GroceryItem] = []
    for category in _CATEGORY_ORDER:
        category_items = sorted(grouped.get(category, []), key=lambda i: i.name.lower())
        sorted_items.extend(category_items)

    return GroceryList(week_start=plan.week_start, items=sorted_items)


# -------------------------------------------------------------------
# Private helpers
# -------------------------------------------------------------------

def _normalize(name: str) -> str:
    """Normalize an ingredient name for comparison (lowercase, stripped)."""
    return name.lower().strip()


def _merge_ingredients(
    ingredients: list[tuple[str, Ingredient]],
) -> list[tuple[str, Ingredient]]:
    """Merge ingredients with the same normalized name.

    When the same ingredient appears in multiple recipes, the quantities
    are NOT combined (we don't have a reliable unit system). The first
    ingredient's data is kept.
    """
    seen: dict[str, Ingredient] = {}
    for normalized, ingredient in ingredients:
        if normalized not in seen:
            seen[normalized] = ingredient
    return list(seen.items())


def _source_recipe(
    normalized_name: str,
    plan: MealPlan,
    recipe_store: RecipeStore,
) -> str | None:
    """Return the recipe name that is the source of this ingredient."""
    for meal in plan.days:
        if not meal.recipe_name.strip():
            continue
        try:
            recipe = find_recipe(meal.recipe_name, recipe_store)
        except (RecipeNotFoundError, MultipleCandidatesError):
            continue
        for ing in recipe.ingredients:
            if _normalize(ing.name) == normalized_name:
                return meal.recipe_name
    return None


def _build_staples_list(pantry_names: set[str], staples: list[str]) -> list[str]:
    """Return staples that are missing from pantry."""
    missing: list[str] = []
    for staple in staples:
        if staple not in pantry_names:
            missing.append(staple)
    return missing


# Canonical category ordering for store layout
_CATEGORY_ORDER: list[GroceryCategory] = [
    GroceryCategory.DAIRY,
    GroceryCategory.PRODUCE,
    GroceryCategory.MEAT_SEAFOOD,
    GroceryCategory.BAKERY,
    GroceryCategory.PANTRY,
    GroceryCategory.FROZEN,
    GroceryCategory.CONDIMENTS,
    GroceryCategory.SNACKS,
    GroceryCategory.BEVERAGES,
    GroceryCategory.OTHER,
]


# -------------------------------------------------------------------
# Staple → category mapping
# -------------------------------------------------------------------

def _category_for_staple(name: str) -> GroceryCategory:
    """Return the GroceryCategory for a staple item."""
    mapping: dict[str, GroceryCategory] = {
        "butter": GroceryCategory.DAIRY,
        "eggs": GroceryCategory.DAIRY,
        "milk": GroceryCategory.DAIRY,
        "salt": GroceryCategory.OTHER,
        "black pepper": GroceryCategory.OTHER,
        "garlic": GroceryCategory.PRODUCE,
        "garlic cloves": GroceryCategory.PRODUCE,
        "garlic powder": GroceryCategory.PANTRY,
        "green onions": GroceryCategory.PRODUCE,
        "minced ginger": GroceryCategory.PRODUCE,
        "shaoxing wine": GroceryCategory.CONDIMENTS,
        "chicken broth": GroceryCategory.PANTRY,
        "soy sauce": GroceryCategory.CONDIMENTS,
        "light mayonnaise": GroceryCategory.DAIRY,
        "ground chicken": GroceryCategory.MEAT_SEAFOOD,
        "small flour tortillas": GroceryCategory.BAKERY,
        "bread": GroceryCategory.BAKERY,
        "sugar": GroceryCategory.PANTRY,
    }
    return mapping.get(name, GroceryCategory.OTHER)