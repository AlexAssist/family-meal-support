"""Shared types for family-meal-support."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Annotated


class GroceryCategory(str, Enum):
    """Grocery store layout categories — ADR-001."""

    DAIRY = "Dairy / Refrigerated"
    PRODUCE = "Produce"
    MEAT_SEAFOOD = "Meat & Seafood"
    BAKERY = "Bakery / Bread"
    PANTRY = "Pantry / Dry Goods"
    FROZEN = "Frozen"
    CONDIMENTS = "Condiments / Sauces"
    SNACKS = "Snacks"
    BEVERAGES = "Beverages / Other"
    OTHER = "Other"


@dataclass(frozen=True)
class PlannedMeal:
    """A single planned meal on a day."""

    date: date
    recipe_name: str
    recipe_link: str | None = None
    defrost_reminder: str | None = None
    prep_reminder: str | None = None


@dataclass(frozen=True)
class MealPlan:
    """A weekly meal plan."""

    week_start: date
    days: list[PlannedMeal] = field(default_factory=list)


@dataclass(frozen=True)
class Ingredient:
    """A single ingredient in a recipe."""

    name: str
    quantity: str | None = None
    unit: str | None = None
    category: GroceryCategory | None = None


@dataclass(frozen=True)
class Recipe:
    """A recipe with ingredients and nutrition."""

    name: str
    ingredients: list[Ingredient] = field(default_factory=list)
    link: str | None = None
    calories: int | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None


@dataclass(frozen=True)
class GroceryItem:
    """A single item on a grocery list."""

    name: str
    quantity: str | None = None
    unit: str | None = None
    category: GroceryCategory = GroceryCategory.OTHER
    checked: bool = False
    source_recipe: str | None = None


@dataclass(frozen=True)
class GroceryList:
    """A generated grocery list."""

    week_start: date
    items: list[GroceryItem] = field(default_factory=list)

    def has_item(self, name: str) -> bool:
        """Check if an item is in the list (case-insensitive)."""
        return any(item.name.lower() == name.lower() for item in self.items)

    def category_of(self, name: str) -> GroceryCategory | None:
        """Return the category of a named item, or None."""
        for item in self.items:
            if item.name.lower() == name.lower():
                return item.category
        return None


@dataclass(frozen=True)
class PantryItem:
    """A single item in the pantry inventory."""

    name: str
    quantity: str | None = None
    location: str | None = None  # e.g. "pantry", "fridge", "freezer"


@dataclass(frozen=True)
class Pantry:
    """The household pantry inventory."""

    items: list[PantryItem] = field(default_factory=list)


class Confidence(str, Enum):
    """Confidence level for photo-analysis results.

    Derived from the image model's self-reported confidence score:
    - HIGH:    >= 80% — definitely visible, label clearly legible
    - MEDIUM:  60-79% — visible but uncertain (partially obscured, ambiguous)
    - LOW:     < 60%  — guess territory, shown as [?] in Discord output
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @classmethod
    def from_score(cls, score: float) -> Confidence:
        """Convert a 0.0-1.0 confidence score to a Confidence level."""
        if score >= 0.80:
            return cls.HIGH
        elif score >= 0.60:
            return cls.MEDIUM
        else:
            return cls.LOW


class ItemStatus(str, Enum):
    """Whether an item is already in the pantry or is a new find."""

    NEW = "new"                  # Not currently in pantry — ➕ in Discord
    ALREADY_IN_PANTRY = "already_in_pantry"  # Already listed — ✅ in Discord


@dataclass(frozen=True)
class SuggestedItem:
    """A single item surfaced by photo analysis."""

    name: str
    confidence: Confidence
    status: ItemStatus
    category: GroceryCategory = GroceryCategory.OTHER
    quantity: str | None = None  # e.g. "3", "half carton", "large bag"


@dataclass(frozen=True)
class PantrySuggestion:
    """Result of photo-based pantry review.

    Produced by `analyze_pantry_photos`. Passed to the confirmation
    flow and eventually applied to pantry-items.md.
    """

    items: list[SuggestedItem] = field(default_factory=list)
    unclear_photos: list[str] = field(default_factory=list)  # URLs that were uninterpretable