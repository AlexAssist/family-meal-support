"""Recipe lookup with tiered matching."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from shared.types import Recipe
from shared.errors import RecipeNotFoundError, MultipleCandidatesError


@runtime_checkable
class RecipeStore(Protocol):
    """Interface for recipe storage.

    The store maps lowercase filename keys to Recipe objects.
    """

    def get(self, name: str) -> Recipe | None:
        """Return recipe by exact lowercase key, or None if not found."""
        ...

    def list_all(self) -> list[tuple[str, Recipe]]:
        """Return all (lowercase_key, recipe) pairs for scanning."""
        ...


def find_recipe(name: str, store: RecipeStore) -> Recipe:
    """Find a recipe by name using tiered matching.

    1. Exact match (case-insensitive on the key).
    2. Substring match — if exactly one recipe filename contains the term.
    3. Multiple substring matches → MultipleCandidatesError.
    4. Zero matches → RecipeNotFoundError.
    """
    # Step 1: exact match (case-insensitive key lookup)
    recipe = store.get(name.lower())
    if recipe is not None:
        return recipe

    # Step 2: substring search across all recipe keys
    search = name.lower()
    candidates: list[tuple[str, Recipe]] = [
        (key, recipe)
        for key, recipe in store.list_all()
        if search in key
    ]

    if len(candidates) == 1:
        return candidates[0][1]
    elif len(candidates) > 1:
        raise MultipleCandidatesError(
            name,
            [key for key, _ in candidates],
        )

    raise RecipeNotFoundError(name)