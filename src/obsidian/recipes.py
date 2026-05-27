"""Obsidian recipe store — loads recipes from the vault's meal-planning directory."""
from __future__ import annotations

import re
from pathlib import Path

from shared.types import Recipe, Ingredient
from shared.errors import RecipeNotFoundError, MultipleCandidatesError
from recipes.lookup import RecipeStore, find_recipe


def _slugify(name: str) -> str:
    """Convert a recipe name to a kebab-case filename slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _deslugify(slug: str) -> str:
    """Convert a kebab-case slug back to a title-case name."""
    return " ".join(word.capitalize() for word in slug.split("-"))


class ObsidianRecipeStore:
    """Recipe store backed by Obsidian meal plan files.

    Keys are kebab-case filenames (e.g. 'mcchicken-smash-tacos').
    The store also maintains a name→key index for title-based lookups.
    """

    def __init__(self, meals_dir: Path) -> None:
        self.meals_dir = meals_dir
        self._recipes: dict[str, Recipe] = {}
        self._name_to_key: dict[str, str] = {}  # lowercase title → kebab key
        self._loaded = False

    def _load(self) -> None:
        """Lazily load all recipe files from the meals directory."""
        if self._loaded:
            return
        self._recipes.clear()
        self._name_to_key.clear()

        if not self.meals_dir.exists():
            self._loaded = True
            return

        for md_file in self.meals_dir.glob("*.md"):
            recipe = _parse_recipe_file(md_file)
            key = md_file.stem.lower()  # e.g. "mcchicken-smash-tacos"
            self._recipes[key] = recipe
            # Index by lowercase title for flexible matching
            if recipe.name:
                self._name_to_key[recipe.name.lower()] = key

        self._loaded = True

    def get(self, key: str) -> Recipe | None:
        """Return recipe by exact lowercase kebab key."""
        self._load()
        return self._recipes.get(key.lower())

    def list_all(self) -> list[tuple[str, Recipe]]:
        """Return all (kebab key, recipe) pairs."""
        self._load()
        return list(self._recipes.items())

    def get_by_title(self, title: str) -> Recipe | None:
        """Return recipe by exact title (case-insensitive)."""
        self._load()
        key = self._name_to_key.get(title.lower())
        if key is None:
            return None
        return self._recipes.get(key)


def _parse_recipe_file(path: Path) -> Recipe:
    """Parse a single recipe Markdown file.

    Extracts: title, link, ingredients.
    Nutrition is parsed if present (FatSecret blocks).
    """
    text = path.read_text()

    # Title: first # heading
    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    name = title_match.group(1).strip() if title_match else path.stem.replace("-", " ").title()

    # Source link
    link_match = re.search(r"\[Source\]\((https?://[^\)]+)\)", text)
    link = link_match.group(1) if link_match else None

    # Ingredients: lines starting with "- "
    ingredients: list[Ingredient] = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            raw = line[2:].strip()
            # Try to split quantity/unit
            parts = re.split(r"\s+", raw, maxsplit=1)
            if len(parts) == 2:
                ingredient = Ingredient(name=parts[1])
            else:
                ingredient = Ingredient(name=raw)
            ingredients.append(ingredient)

    # Nutrition blocks (optional)
    calories = _extract_nutrition(text, "Calories")
    protein = _extract_nutrition(text, "Protein")
    carbs = _extract_nutrition(text, "Carbs")
    fat = _extract_nutrition(text, "Fat")

    return Recipe(
        name=name,
        ingredients=ingredients,
        link=link,
        calories=calories,
        protein_g=protein,
        carbs_g=carbs,
        fat_g=fat,
    )


def _extract_nutrition(text: str, label: str) -> int | None:
    """Extract a nutrition value from recipe text.

    Looks for lines like: **Calories:** 386
    Returns the integer value, or None if not found.
    """
    pattern = rf"\*{label}:\*\s*(\d+)"
    match = re.search(pattern, text)
    if match:
        return int(match.group(1))
    return None