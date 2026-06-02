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
        # Clean the ingredient name for display (remove prep adjectives)
        clean_name = _clean_ingredient_name(ingredient.name)
        if clean_name is None:
            # Skip purely numeric / noise entries (nutrition lines, etc.)
            continue
        items.append(
            GroceryItem(
                name=clean_name,
                quantity=None,  # quantities aren't reliable; show clean ingredient only
                unit=None,
                category=ingredient.category if ingredient.category is not None
                           else _categorize_ingredient(clean_name),
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


def _clean_ingredient_name(name: str) -> str | None:
    """Strip preparation adjectives for clean grocery display.

    Removes: price noise, unit/quantity prefixes, preparation descriptors,
    trailing noise, and parenthetical content. Returns None to skip pure noise.
    """
    # Remove price patterns first
    name = re.sub(r'\$[0-9]+(?:\.[0-9]+)?', '', name)

    # Step 1: Remove leading unit patterns (with or without quantity prefix)
    for q in [
        r'^[0-9]+(?:\s*/\s*[0-9]+)?\s*(?:cups?|c)\s+',           # 2 cups, 1/2 cups
        r'^(?:cups?|c)\s+',                                          # bare cups, c
        r'^[0-9]+(?:\s*/\s*[0-9]+)?\s*(?:tbsp|tablespoons?)\s+', # 1 tbsp
        r'^(?:tbsp|tablespoons?)\s+',                                # bare tbsp
        r'^[0-9]+(?:\s*/\s*[0-9]+)?\s*(?:tsp|teaspoons?)\s+',    # 1 tsp
        r'^(?:tsp|teaspoons?)\s+',                                   # bare tsp
        r'^(?:oz|ounce|ounces)\s+',                                 # oz, ounce
        r'^[0-9]+(?:\s*/\s*[0-9]+)?\s*(?:pounds?|lbs?)\s+',       # 1 pound
        r'^(?:handful|bunch)\s+',                                    # handful, bunch
        r'^(?:can|cans|jar|jars?|bottle|bottles?|package|packages?)\s+',  # can, jar
        r'^(?:sheet|sheets|piece|pieces|slice|slices)\s+',           # sheet, piece, slice
        r'^(?:box|boxes)\s+',                                       # box of, boxes of
        r'^[0-9]+-[a-z]+\s+',                                   # "6-inch tortillas" → strip prefix
        r'^lb\.?\s+',                                               # "lb. chicken breast" → "chicken breast"
        r'^lbs?\.?\s+',                                            # "lbs. chicken breast" → "chicken breast"
    ]:
        name = re.sub(q, '', name, flags=re.IGNORECASE)

    # Strip common size descriptors like "6-inch", "8-inch", etc. before step 2
    name = re.sub(r'^[0-9]+-[a-z]+\s+', '', name, flags=re.IGNORECASE)

    # Remove trailing "any color" type phrases
    name = re.sub(r'\s+,?\s*any\s+color\s*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+,?\s*small\s*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+,?\s*(?:optional|about|approx)\s+.*$', '', name, flags=re.IGNORECASE)

    # Step 2: Remove leading preposition "of" (from "can of X", "box of X")
    name = re.sub(r'^of\s+', '', name, flags=re.IGNORECASE)

    # Step 3: Remove preparation descriptors at the start (includes "chopped" at start)
    for p in [
        r'^steamed\s+', r'^diced\s+', r'^minced\s+', r'^chopped\s+',
        r'^sliced\s+', r'^crushed\s+', r'^cubed\s+', r'^shredded\s+',
        r'^grated\s+', r'^thinly\s+', r'^roughly\s+', r'^finely\s+',
        r'^small\s+', r'^large\s+', r'^medium\s+',
        r'^fresh\s+', r'^dried\s+', r'^cold\s+', r'^warm\s+',
        r'^softened\s+', r'^melted\s+',
        r'^leaf\s+', r'^head\s+', r'^sprig\s+', r'^stalk\s+',
        r'^piece\s+', r'^pieces\s+',
    ]:
        name = re.sub(p, '', name, flags=re.IGNORECASE)

    # Step 4: Remove trailing descriptors (single words AND compounds, with leading whitespace)
    # Do compounds first to avoid partial matches leaving ghost words.
    # (?:^|\s+) matches start of string OR whitespace before the pattern,
    # so patterns work both at string start and after a preceding word.
    for t in [
        # Compound trailing: "chopped matchstick carrots", "diced English cucumber"
        r'(?:^|\s+)chopped\s+matchstick\s+carrots?\s*$',
        r'(?:^|\s+)diced\s+(?:English\s+)?cucumber\s*$',
        r'(?:^|\s+)minced\s+finely$',
        r'(?:^|\s+)diced\s+finely$',
        r'(?:^|\s+)chopped\s+finely$',
        r'\s+for garnish$', r'\s+to serve$', r'\s+garnish$',
        r'\s+or\s+.*$',
    ]:
        name = re.sub(t, '', name, flags=re.IGNORECASE)

    # Step 5: Remove single-word trailing descriptors
    for t in [
        r'\s+diced$', r'\s+minced$', r'\s+sliced$', r'\s+chopped$',
        r'\s+peeled$', r'\s+drained$', r'\s+rinse[ds]?$',
        r'\s+cooked$', r'\s+steamed$', r'\s+baked$',
        r'\s+roasted$', r'\s+fried$', r'\s+grilled$',
        r'\s+ground$', r'\s+whole$',
    ]:
        name = re.sub(t, '', name, flags=re.IGNORECASE)

    # Step 6: Now strip matchstick as standalone (already handled in compounds above)
    name = re.sub(r'^matchstick\s+', '', name, flags=re.IGNORECASE)

    # Step 7: Remove compound "diced finely" / "minced finely" patterns
    name = re.sub(r'\s+diced\s+finely$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+minced\s+finely$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+chopped\s+finely$', '', name, flags=re.IGNORECASE)

    # Step 8: Remove parenthetical content
    name = re.sub(r'\s*\([^)]*\)', '', name)   # (for garnish, etc.)
    name = re.sub(r'\s*\([^)]*$', '', name)      # unclosed (at end)

    # Step 9: Clean up remaining pasta type names ("pipe rigate", "rigate")
    name = re.sub(r'\b(?:pipe\s+)?rigate\b', '', name, flags=re.IGNORECASE)

    # Step 10: Remove any commas and trailing punctuation
    name = re.sub(r',\s*', ' ', name)   # commas → spaces
    name = re.sub(r'\s+-$', '', name)            # trailing dash
    name = re.sub(r'^\(*', '', name)             # leading open paren

    # Step 11: Collapse whitespace and strip
    name = re.sub(r'\s+', ' ', name).strip()

    # Step 12: Skip purely numeric content (465, 554, etc.) or nutrition (10.0g, 15.0g)
    if re.match(r'^[0-9]+(?:\.[0-9]+)?(?:\s*[a-z]+)?$', name, re.IGNORECASE):
        return None
    if re.match(r'^[0-9]+$', name):
        return None

    # Skip if too short or pure punctuation
    if not name or len(name) <= 1 or re.match(r'^[0-9.,]+$', name):
        return None

    return name

    # Final check: if name is empty or pure whitespace, skip entirely
    if not name or not name.strip():
        return None

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
        'steamed', 'cooked', 'raw', 'baked', 'fried', 'roasted',
        'peeled', 'cored', 'trimmed', 'sliced', 'diced',
        'roughly', 'finely', 'thinly', 'lightly',
        'about', 'inch', 'inches', 'piece', 'pieces',
        'oz', 'ounce', 'ounces', 'can', 'cans', 'jar', 'jars',
        'cup', 'cups', 'tbsp', 'tsp', 'tablespoon', 'teaspoon',
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