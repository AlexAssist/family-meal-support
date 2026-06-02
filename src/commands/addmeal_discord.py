"""Discord command handler for !addmeal with discovery flow.

Handles the interactive Discord flow:
  1. Parse day + meal name from input
  2. Try add_meal_to_plan (known recipe path)
  3. On RecipeNotFoundError → trigger web discovery → post candidates
  4. On user selection → save recipe → retry add
  5. On "none"/"cancel" → abort cleanly

Public interface:
    handle_addmeal(message: str, vault: Path) -> str | None
        Main entry point. Returns a message to send to Discord, or None
        if the flow is complete (no more user input needed at this step).

        For the interactive discovery flow, this function is called twice:
        - First call: triggers discovery, returns candidate message
        - Second call (user replies): handles selection, returns confirmation
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Literal

from commands.addmeal import parse_day, add_meal_to_plan
from obsidian.vault import read_meal_plan, write_meal_plan
from obsidian.recipeStore import ObsidianRecipeStore
from obsidian.recipe_saver import save_recipe, RecipeSaveError, _url_to_postfix
from recipes.discovery import discover_recipe, RecipeCandidate
from recipes.lookup import find_recipe, RecipeNotFoundError, MultipleCandidatesError

# -------------------------------------------------------------------
# State tracking for the interactive discovery flow
# -------------------------------------------------------------------
# In a real bot this would be stored in Redis or a DB.
# Here we use a module-level dict keyed by user_id.
# Format: {user_id: {"pending": RecipeCandidate[], "day": str, "meal_name": str}}
_PENDING_DISCOVERY: dict[str, dict] = {}


def handle_addmeal(
    message: str,
    vault: Path,
    user_id: str,
    today: date | None = None,
) -> str | None:
    """Handle !addmeal command with discovery flow.

    Returns a Discord message string to send, or None if the interaction
    is complete (meal added or cancelled). For the interactive discovery
    flow, the caller should store the returned message and call this function
    again with the user's next message.
    """
    if today is None:
        today = date.today()

    # Check for pending discovery selection from this user
    if user_id in _PENDING_DISCOVERY:
        return _handle_discovery_reply(message, vault, user_id, today)

    # Normal command parse: "!addmeal <day>: <meal>"
    # Also handles: "!addmeal <day>: search <meal>"
    cleaned = message.strip()
    if cleaned.lower().startswith("!addmeal"):
        cleaned = cleaned[len("!addmeal"):].strip()
    if cleaned.lower().startswith("addmeal"):
        cleaned = cleaned[len("addmeal"):].strip()

    # Parse day_spec and meal_name
    # Format: "<day>: <meal>" or "<day>: search <meal>"
    colon_pos = cleaned.find(":")
    if colon_pos == -1:
        return "Usage: `!addmeal <day>: <meal>` — e.g. `!addmeal Tuesday: Chicken Tacos`"

    day_spec = cleaned[:colon_pos].strip()
    rest = cleaned[colon_pos + 1:].strip()

    # Check for explicit search trigger
    if rest.lower().startswith("search "):
        meal_name = rest[len("search "):].strip()
        return _trigger_discovery(day_spec, meal_name, vault, user_id, today)

    meal_name = rest

    # Try to add directly (known recipe)
    try:
        store = ObsidianRecipeStore(vault / "reference" / "meal-planning" / "meals")
        new_meal, was_overwrite = add_meal_to_plan(vault, day_spec, meal_name, store, today=today)

        day_str = new_meal.date.strftime("%A %B %-d")
        msg = f"Added **{new_meal.recipe_name}** to {day_str}"
        if was_overwrite:
            msg += " (replaced existing)"
        return msg

    except RecipeNotFoundError:
        # Trigger discovery
        return _trigger_discovery(day_spec, meal_name, vault, user_id, today)

    except MultipleCandidatesError as e:
        # Multiple recipes match in local store — list them for disambiguation
        lines = [f"Multiple recipes match '{e.name}'. Which one?"]
        for i, candidate in enumerate(e.candidates, 1):
            lines.append(f"  {i}. {candidate}")
        lines.append("Reply with a number, or 'cancel'.")
        return "\n".join(lines)


def _trigger_discovery(
    day_spec: str,
    meal_name: str,
    vault: Path,
    user_id: str,
    today: date,
) -> str:
    """Run recipe discovery and post candidates to Discord."""
    candidates = discover_recipe(meal_name)

    if not candidates:
        return (
            f"Couldn't find anything for '{meal_name}'. "
            "Try a different name or add the recipe manually."
        )

    # Store pending state for this user
    _PENDING_DISCOVERY[user_id] = {
        "day_spec": day_spec,
        "meal_name": meal_name,
        "candidates": candidates,
    }

    # Format candidates message
    lines = [f"Found {len(candidates)} candidates for '{meal_name}':"]
    for i, c in enumerate(candidates, 1):
        # Truncate description
        desc = c.description
        if len(desc) > 120:
            desc = desc[:119] + "…"
        lines.append(f"  **{i}.** {c.name}")
        lines.append(f"     {desc}")
        lines.append(f"     <{c.source_url}>")

    lines.append("")
    lines.append("Reply with a number to select, `none` to search again, or `cancel`.")

    return "\n".join(lines)


def _handle_discovery_reply(
    message: str,
    vault: Path,
    user_id: str,
    today: date,
) -> str | None:
    """Handle user reply to discovery candidates."""
    state = _PENDING_DISCOVERY.pop(user_id)
    candidates = state["candidates"]
    day_spec = state["day_spec"]
    meal_name = state["meal_name"]
    cleaned = message.strip().lower()

    # Cancel
    if cleaned in ("cancel", "c"):
        return "Cancelled. No recipe added."

    # Search again — refine terms
    if cleaned in ("none", "n", "search again", "retry"):
        return _trigger_discovery(day_spec, meal_name, vault, user_id, today)

    # Number selection
    try:
        index = int(cleaned) - 1
        if index < 0 or index >= len(candidates):
            return f"Invalid choice ({index + 1}). Pick 1-{len(candidates)}, or `cancel`."
    except ValueError:
        return f"Reply with a number (1-{len(candidates)}), `none`, or `cancel`."

    selected = candidates[index]

    # Extract a short postfix from the source URL to differentiate
    # saved recipes from the same source domain.
    postfix = _url_to_postfix(selected.source_url)

    # Save recipe to vault
    try:
        saved_recipe = save_recipe(selected, vault, postfix=postfix)
    except RecipeSaveError as e:
        return f"Failed to save recipe: {e}. Please try again or add manually."

    # Now re-run add_meal_to_plan with the newly saved recipe
    # We need to reload the recipe store since we added a new file
    store = ObsidianRecipeStore(vault / "reference" / "meal-planning" / "meals")

    # Retry: the recipe should now be found
    try:
        new_meal, was_overwrite = add_meal_to_plan(vault, day_spec, saved_recipe.name, store, today=today)
        day_str = new_meal.date.strftime("%A %B %-d")
        msg = f"**{saved_recipe.name}** saved and added to {day_str}"
        if was_overwrite:
            msg += " (replaced existing)"
        return msg
    except RecipeNotFoundError:
        # Shouldn't happen if save succeeded — but handle gracefully
        return (
            f"Recipe '{saved_recipe.name}' saved to vault but couldn't be added to the plan. "
            "Try adding it again with `!addmeal {day}: {saved_recipe.name}`."
        )