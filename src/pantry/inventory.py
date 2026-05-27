"""Pantry inventory — reads from Obsidian pantry-items.md."""
from __future__ import annotations

import re
from pathlib import Path

from shared.types import GroceryCategory, Pantry, PantryItem


# Category mapping from the emoji-prefixed section headers in pantry-items.md
_CATEGORY_MAP: dict[str, GroceryCategory] = {
    "dairy / refrigerated": GroceryCategory.DAIRY,
    "produce": GroceryCategory.PRODUCE,
    "bakery / bread": GroceryCategory.BAKERY,
    "pantry / dry goods": GroceryCategory.PANTRY,
    "condiments / sauces": GroceryCategory.CONDIMENTS,
    "snacks": GroceryCategory.SNACKS,
    "beverages / other": GroceryCategory.BEVERAGES,
    "meat & seafood": GroceryCategory.MEAT_SEAFOOD,
    "frozen": GroceryCategory.FROZEN,
    "other": GroceryCategory.OTHER,
    # Excluded/already-have section not treated as a category
    "already have / excluded": GroceryCategory.OTHER,
}


def read_pantry(pantry_file: Path) -> Pantry:
    """Read pantry inventory from a Markdown file.

    Parses the pantry-items.md format which has emoji-prefixed category
    headers and bullet-list items.

    Returns an empty Pantry if the file does not exist.
    """
    if not pantry_file.exists():
        return Pantry(items=[])

    text = pantry_file.read_text()
    items: list[PantryItem] = []
    current_category: str | None = None

    for line in text.split("\n"):
        line = line.strip()

        # Category header: ## 🧀 Dairy / Refrigerated
        header_match = re.match(r"^##\s+[^\w\s]\S*\s+(.+)$", line)
        if header_match:
            current_category = header_match.group(1).lower()
            continue

        # Skip non-bullet lines
        if not line.startswith("- "):
            continue

        # Item line: "- Lactantia Salted Cultured Butter"
        raw = line[2:].strip()
        # Remove quantity in parens: "Eggs (3 dozen)" → "Eggs"
        name = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
        if not name:
            continue

        items.append(PantryItem(name=name, location=None))

    return Pantry(items=items)


def read_staples(pantry_file: Path) -> list[str]:
    """Read the Staples list from pantry-items.md.

    Returns items from the "## ✅ Already Have / Excluded" section
    that are considered always-have baseline items.
    """
    if not pantry_file.exists():
        return []

    text = pantry_file.read_text()
    staples: list[str] = []

    # Find the "Already Have / Excluded" section
    in_staples = False
    for line in text.split("\n"):
        line = line.strip()

        # Section header
        header_match = re.match(r"^##\s+[^\w\s]\S*\s+(.+)$", line)
        if header_match:
            section_name = header_match.group(1).lower()
            if "already have" in section_name or "excluded" in section_name:
                in_staples = True
            else:
                in_staples = False
            continue

        if not in_staples:
            continue

        if not line.startswith("- "):
            continue

        raw = line[2:].strip()
        name = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
        if name:
            staples.append(name.lower())

    return staples