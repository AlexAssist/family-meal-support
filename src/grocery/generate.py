"""Grocery list generation — deep module.

One public function: generate_grocery_list().
All complexity (ingredient merge, pantry subtract, staples, grouping, sorting)
lives behind it.
"""
from __future__ import annotations
import re
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
                category=ingredient.category if ingredient.category is not None
                           else _categorize_ingredient(ingredient.name),
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
    """Normalize an ingredient name for comparison (lowercase, stripped).

    Strips price noise like '($0.05)', parenthetical notes like '(divided)',
    unit prefixes (Tbsp, tsp, cup), and normalizes whitespace. Used for both
    dedup across recipes and pantry matching.
    """
    # Remove price noise like ($0.30), ($0.05), 0.49
    name = re.sub(r'\s*\([$]?[0-9]+(?:\.[0-9]+)?\)', '', name, flags=re.IGNORECASE)
    # Remove parenthetical notes like (divided), (optional), (about 1 inch)
    name = re.sub(r'\s*\([^)]*\)', '', name)
    # Strip unit prefixes (but keep the rest of the quantity)
    name = re.sub(r'^(Tbsp|tsp|Tablespoons?|Teaspoons?|Cup|Cups?|tbsp|ts)\s+', '', name, flags=re.IGNORECASE)
    # Collapse multiple spaces
    name = re.sub(r'\s+', ' ', name)
    return name.lower().strip()


def _key_ingredients(name: str) -> frozenset[str]:
    """Convert ingredient name to a semantic dedup key (frozenset of core words).

    Used to detect duplicates across recipes where the same ingredient is described
    differently (e.g., "garlic cloves (minced)" vs "cloves of garlic, minced").

    - Strips price and parenthetical noise (same as _normalize)
    - Removes determiners, prepositions, and quantity words
    - Splits on non-alphanumeric characters
    - Returns a frozenset of the remaining significant words
    """
    # Apply same noise removal as _normalize
    name = re.sub(r'\s*\([$]?[0-9]+(?:\.[0-9]+)?\)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*\([^)]*\)', '', name)
    name = re.sub(r'^(Tbsp|tsp|Tablespoons?|Teaspoons?|Cup|Cups?|tbsp|ts)\s+', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+', ' ', name).lower().strip()

    # Split on non-alphanumeric
    words = re.split(r'[^a-z0-9]+', name)

    # Core ingredient words (removing common noise)
    noise = {
        'and', 'or', 'of', 'the', 'a', 'an', 'with', 'for', 'to',
        'finely', 'roughly', 'small', 'large', 'medium',
        'diced', 'minced', 'chopped', 'sliced', 'crushed',
        'fresh', 'dried', 'ground', 'whole', 'half',
        'plus', 'more', 'optional',
    }
    return frozenset(w for w in words if len(w) > 1 and w not in noise)


def _merge_ingredients(
    ingredients: list[tuple[str, Ingredient]],
) -> list[tuple[str, Ingredient]]:
    """Merge ingredients with the same normalized name.

    When the same ingredient appears in multiple recipes with different
    descriptions (e.g., "garlic cloves (minced)" vs "cloves of garlic, minced"),
    they are merged via semantic key matching — keeping the first seen.
    """
    seen: dict[str, Ingredient] = {}
    for normalized, ingredient in ingredients:
        if normalized in seen:
            continue
        # Check semantic collision: if any previously seen ingredient has
        # an overlapping word set, treat as duplicate
        item_key = _key_ingredients(normalized)
        duplicate = False
        for existing_norm, _ in seen.items():
            existing_key = _key_ingredients(existing_norm)
            # If keys share significant words, merge
            if item_key & existing_key:
                duplicate = True
                break
        if not duplicate:
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


def _categorize_ingredient(name: str) -> GroceryCategory:
    """Classify an ingredient by keyword matching against known category terms.

    Used as fallback when an ingredient has no explicit category field set.
    Checks against common ingredient names to classify into DAIRY, PRODUCE,
    MEAT_SEAFOOD, BAKERY, PANTRY, CONDIMENTS, or OTHER.
    """
    n = name.lower()

    # Meat / protein
    if any(k in n for k in [
        "chicken", "beef", "pork", "fish", "salmon", "shrimp", "bacon",
        "sausage", "turkey", "ground", "steak", "tenderloin", "breast",
        "thigh", "crab", "lobster", "scallop", "tilapia", "cod", "tuna",
        "meat", "lamb", "veal", "ham", "pepperoni", "prosciutto",
    ]):
        return GroceryCategory.MEAT_SEAFOOD

    # Dairy
    if any(k in n for k in [
        "milk", "cream", "cheese", "butter", "yogurt", "sour cream",
        "parmesan", "mozzarella", "cheddar", "ricotta", "feta", "brie",
        "cream cheese", "half and half", "heavy cream", "buttermilk",
    ]):
        return GroceryCategory.DAIRY

    # Produce
    if any(k in n for k in [
        "onion", "garlic", "pepper", "tomato", "lettuce", "spinach",
        "carrot", "celery", "cucumber", "zucchini", "broccoli",
        "cauliflower", "potato", "mushroom", "avocado", "lime", "lemon",
        "orange", "ginger", "cilantro", "parsley", "basil", "thyme",
        "rosemary", "sage", "mint", "chive", "scallion", "shallot",
        "cabbage", "kale", "arugula", "bok choy", "corn", "peas", "bean",
        "sprout", "jalapeño", "serrano", "habanero", "poblano", "bell pepper",
        "mango", "pineapple", "strawberry", "blueberry", "raspberry",
        "apple", "pear", "peach", "plum", "banana", "grape", "melon",
        "coconut", "garlic clove", "cilantro", "green onion",
    ]):
        return GroceryCategory.PRODUCE

    # Bakery / bread
    if any(k in n for k in [
        "tortilla", "bread", "bun", "roll", "pita", "naan", "bagel",
        "croissant", "baguette", "focaccia", "ciabatta", "tortilla",
    ]):
        return GroceryCategory.BAKERY

    # Condiments / sauces / oils
    if any(k in n for k in [
        "sauce", "oil", "vinegar", "soy sauce", "ketchup", "mustard",
        "mayo", "mayonnaise", "hot sauce", "salsa", "hummus", "pesto",
        "bbq", "teriyaki", "fish sauce", "worcestershire", "oyster sauce",
        "sesame oil", "olive oil", "vegetable oil", "canola", "coconut oil",
        "chili oil", "tahini", "sriracha", "hoisin", "plum sauce",
        "curry paste", "red curry", "coconut milk",
    ]):
        return GroceryCategory.CONDIMENTS

    # Pantry / dry goods
    if any(k in n for k in [
        "rice", "pasta", "noodle", "flour", "sugar", "salt", "pepper",
        "spice", "cumin", "paprika", "cayenne", "turmeric", "cinnamon",
        "nutmeg", "oregano", "bay leaf", "coriander", "cardamom",
        "chickpea", "lentil", "bean", "canned", "tomato sauce",
        "tomato paste", "broth", "stock", "honey", "maple syrup",
        "cornstarch", "baking", "yeast", "breadcrumb", "cracker",
        "nut", "almond", "walnut", "peanut", "cashew", "sesame seed",
        "nori", "vinegar", "mirin", "sake", "shaoxing",
    ]):
        return GroceryCategory.PANTRY

    return GroceryCategory.OTHER