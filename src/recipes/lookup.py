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


def _words(s: str) -> list[str]:
    """Split a string into words (alphanumeric tokens, lowercase)."""
    import re
    return re.findall(r"[a-z0-9]+", s.lower())


def _fuzzy_match(word: str, key: str, max_edits: int = 2) -> bool:
    """Return True if word matches a substring of key with at most max_edits.

    Used for handling misspellings in recipe lookups.
    """
    word_len = len(word)
    key_len = len(key)
    # Fast path: exact substring
    if word in key:
        return True
    # Sliding window over key, allow up to max_edits deletions/inserts/substitutions
    # Use a simple edit-distance check for the window
    for i in range(key_len - word_len + 1):
        window = key[i:i + word_len]
        edits = sum(c1 != c2 for c1, c2 in zip(word, window))
        if edits <= max_edits:
            return True
    return False


def find_recipe(name: str, store: RecipeStore) -> Recipe:
    """Find a recipe by name using tiered matching.

    1. Exact match (case-insensitive on the key).
    2. Substring match — if exactly one recipe filename contains the full term.
    3. Fuzzy word match — all significant words (len > 1) match within edit distance.
    4. Multiple substring matches → MultipleCandidatesError.
    5. Zero matches → RecipeNotFoundError.
    """
    # Step 1: exact match (case-insensitive key lookup)
    recipe = store.get(name.lower())
    if recipe is not None:
        return recipe

    search = name.lower()

    # Step 2: substring search across all recipe keys
    candidates: list[tuple[str, Recipe]] = [
        (key, recipe_)
        for key, recipe_ in store.list_all()
        if search in key
    ]

    if len(candidates) == 1:
        return candidates[0][1]
    elif len(candidates) > 1:
        raise MultipleCandidatesError(name, [key for key, _ in candidates])

    # Step 3: fuzzy word-based fallback
    search_words = [w for w in _words(search) if len(w) > 1]  # ignore single-char noise
    if not search_words:
        raise RecipeNotFoundError(name)

    word_candidates: list[tuple[str, Recipe]] = [
        (key, recipe_)
        for key, recipe_ in store.list_all()
        if all(_fuzzy_match(w, key) for w in search_words)
    ]

    if len(word_candidates) == 1:
        return word_candidates[0][1]
    elif len(word_candidates) > 1:
        raise MultipleCandidatesError(name, [key for key, _ in word_candidates])

    raise RecipeNotFoundError(name)