"""Save a discovered recipe to the Obsidian meals collection.

Public interface:
    save_recipe(candidate: RecipeCandidate, vault: Path) -> Recipe
        Fetches the recipe page, parses it, saves to meals/ as Markdown,
        returns the saved Recipe object.

    save_recipe_from_candidate(candidate: RecipeCandidate, vault: Path) -> Recipe
        Alias for save_recipe (named per PRD naming convention).
"""
from __future__ import annotations

import re
from pathlib import Path
from datetime import date

from shared.types import Recipe, Ingredient


def save_recipe(candidate: RecipeCandidate, vault: Path) -> Recipe:
    """Save a recipe candidate to the meals collection.

    Fetches the source URL, parses it for a clean recipe structure,
    writes to `reference/meal-planning/meals/{slug}.md`,
    and returns the saved Recipe.

    Args:
        candidate: A RecipeCandidate from discovery.
        vault: Path to the Obsidian vault.

    Returns:
        A Recipe object representing the saved recipe (in-memory only,
        not re-loaded from disk).

    Raises:
        RecipeSaveError: Fetch or parse failed.
    """
    # Fetch and parse the source page
    try:
        page_text = _fetch_page(candidate.source_url)
    except Exception as e:
        raise RecipeSaveError(f"Failed to fetch {candidate.source_url}: {e}")

    # Try to extract structured recipe data
    recipe_data = _parse_recipe_page(page_text, candidate)

    # Build Markdown in the existing meals/ format
    md = _build_recipe_md(recipe_data, candidate)

    # Write to meals/ directory
    meals_dir = vault / "reference" / "meal-planning" / "meals"
    meals_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(recipe_data["name"])
    file_path = meals_dir / f"{slug}.md"

    # Handle name collision
    if file_path.exists():
        base_slug = slug
        counter = 1
        while file_path.exists():
            slug = f"{base_slug}-{counter}"
            file_path = meals_dir / f"{slug}.md"
            counter += 1

    file_path.write_text(md)

    # Build and return the Recipe object
    ingredients = [
        Ingredient(name=name.strip())
        for name in recipe_data.get("ingredients", [])
        if name.strip()
    ]

    return Recipe(
        name=recipe_data["name"],
        ingredients=ingredients,
        link=candidate.source_url,
        calories=recipe_data.get("calories"),
        protein_g=recipe_data.get("protein_g"),
        carbs_g=recipe_data.get("carbs_g"),
        fat_g=recipe_data.get("fat_g"),
    )


def _slugify(name: str) -> str:
    """Convert a recipe name to a kebab-case slug."""
    name = name.lower()
    name = re.sub(r"[^a-z0-9\s]", "", name)
    name = re.sub(r"\s+", "-", name)
    return name.strip("-")


def _fetch_page(url: str) -> str:
    """Fetch a recipe page, return clean text."""
    import requests

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.text


def _parse_recipe_page(html: str, candidate: RecipeCandidate) -> dict:
    """Parse a recipe page to extract structured data.

    Tries JSON-LD (schema.org/Recipe) first, then falls back to
    heuristic extraction of ingredients and nutrition.
    """
    # Try JSON-LD first (most reliable for major recipe sites)
    jsonld = _extract_jsonld(html)
    if jsonld:
        return jsonld

    # Fallback: heuristic extraction
    return _heuristic_parse(html, candidate)


def _extract_jsonld(html: str) -> dict | None:
    """Extract Recipe from JSON-LD structured data."""
    pattern = re.compile(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.DOTALL,
    )
    for match in pattern.finditer(html):
        try:
            import json
            data = json.loads(match.group(1))

            # Handle arrays
            if isinstance(data, list):
                for item in data:
                    if _is_recipe(item):
                        return _normalize_jsonld(item)
            elif _is_recipe(data):
                return _normalize_jsonld(data)
        except Exception:
            continue
    return None


def _is_recipe(item: dict) -> bool:
    """Check if a JSON-LD node is a Recipe."""
    return item.get("@type") in ("Recipe", ["Recipe", "recipe"])


def _normalize_jsonld(data: dict) -> dict:
    """Normalize a JSON-LD Recipe dict into our internal format."""
    name = data.get("name", "Unknown Recipe")

    # Ingredients
    raw_ingredients = data.get("recipeIngredient", [])
    ingredients = [
        ing.strip()
        for ing in raw_ingredients
        if isinstance(ing, str) and ing.strip()
    ]

    # Nutrition
    nutrition = data.get("nutrition", {}) or {}
    calories = _extract_calories(nutrition.get("calories"))
    protein = _parse_number(nutrition.get("proteinContent"))
    carbs = _parse_number(nutrition.get("carbohydContent"))
    fat = _parse_number(nutrition.get("fatContent"))

    return {
        "name": name,
        "ingredients": ingredients,
        "calories": calories,
        "protein_g": protein,
        "carbs_g": carbs,
        "fat_g": fat,
    }


def _extract_calories(value: str | None) -> int | None:
    """Extract integer calories from a string like '542 kcal' or '542'."""
    if value is None:
        return None
    value = str(value).strip()
    # e.g. "542 kcal" or "542 calories" or just "542"
    match = re.match(r"(\d+)", value)
    if match:
        return int(match.group(1))
    return None


def _parse_number(value: str | None) -> float | None:
    """Parse a nutrition number string like '34g' into a float."""
    if value is None:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", str(value))
    return float(match.group(1)) if match else None


def _heuristic_parse(html: str, candidate: RecipeCandidate) -> dict:
    """Fallback parser when no JSON-LD is available.

    Attempts to extract name, ingredients, and nutrition from raw HTML.
    """
    # Strip HTML tags for text extraction
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)

    name = candidate.name

    # Try to find an ingredients list
    ingredients: list[str] = []
    ing_patterns = [
        r'(?:ingredients|you\'ll need)[:\s]+(.*?)(?:\d+\s+(?:serving|cup|tbsp|tsp|tablespoon|teaspoon)|instructions|preparation)',
    ]
    for pattern in ing_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            raw = match.group(1)
            # Extract bullet-like items
            items = re.findall(r'(?:^|\n)\s*[-*]\s*(.+?)(?=\n[-*]|\n\n)', raw, re.DOTALL)
            if items:
                ingredients = [item.strip() for item in items if len(item.strip()) > 3]
                break

    return {
        "name": name,
        "ingredients": ingredients,
        "calories": None,
        "protein_g": None,
        "carbs_g": None,
        "fat_g": None,
    }


def _build_recipe_md(data: dict, candidate: RecipeCandidate) -> str:
    """Build a recipe Markdown file in the existing format."""
    lines = [
        f"# {data['name']}",
        "",
        f"**Type:** main",
        f"**Servings:** 4",
        f"**Added:** {date.today().isoformat()}",
        "**Nutrition Source:** Estimated" if not data.get("calories") else "**Nutrition Source:** From recipe",
        "",
        "## Ingredients",
    ]

    # Add ingredients
    if data.get("ingredients"):
        for ing in data["ingredients"]:
            lines.append(f"- {ing}")
    else:
        lines.append("- (ingredients not available — please add manually)")

    # Add nutrition section if available
    has_nutrition = any([
        data.get("calories"),
        data.get("protein_g"),
        data.get("carbs_g"),
        data.get("fat_g"),
    ])
    if has_nutrition:
        lines.extend(["", "## Nutrition (per serving)"])
        if data.get("calories"):
            lines.append(f"- **Calories:** {data['calories']}")
        if data.get("protein_g"):
            lines.append(f"- **Protein:** {data['protein_g']}g")
        if data.get("carbs_g"):
            lines.append(f"- **Carbs:** {data['carbs_g']}g")
        if data.get("fat_g"):
            lines.append(f"- **Fat:** {data['fat_g']}g")

    # Source link
    lines.extend(["", f"[Source]({candidate.source_url})"])

    return "\n".join(lines)


# -------------------------------------------------------------------
# Errors
# -------------------------------------------------------------------

class RecipeSaveError(Exception):
    """Failed to save a recipe to the vault."""
    pass


# -------------------------------------------------------------------
# Module-level exports (per PRD public interface)
# -------------------------------------------------------------------
from recipes.discovery import RecipeCandidate

__all__ = [
    "save_recipe",
    "save_recipe_from_candidate",
    "RecipeSaveError",
]