"""Pending recipe discovery state for HITL sync flows.

When `confirm_pull()` encounters a PlannedMeal without a recipe_link,
it calls `start_discovery()` to record the pending state and return
discovery candidates. The agent surfaces those to Jason via Discord,
then routes the reply back through `handle_discovery_reply()`.

State is persisted to disk so it survives agent restarts.

Public interface:
    start_discovery(user_id, plan_file, day_date, meal_name, candidates)
        Record that we're waiting for user confirmation on a recipe.
        Returns the prompt message to send to the user.

    handle_discovery_reply(user_id, confirmed, selected_candidate, vault)
        Called when the user responds. If confirmed, saves the recipe
        and updates the plan file's recipe_link.

    get_pending_discovery(user_id) -> PendingDiscovery | None
        Check if a user has a pending discovery session.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path

from recipes.discovery import RecipeCandidate
from obsidian.recipe_saver import save_recipe, RecipeSaveError, _url_to_postfix
from obsidian.vault import update_plan_meal_link


# -------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------

_STATE_DIR = Path.home() / ".config" / "family-meal-support"
_STATE_FILE = _STATE_DIR / "pending-discovery.json"


# -------------------------------------------------------------------
# Types
# -------------------------------------------------------------------

@dataclass
class PendingDiscovery:
    """A pending recipe discovery awaiting user confirmation."""
    plan_file_rel: str          # relative path from vault root
    day_date: str               # ISO date string
    meal_name: str
    candidates: list[dict]       # serialized RecipeCandidate list

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> PendingDiscovery:
        return cls(**d)


# -------------------------------------------------------------------
# Persistence
# -------------------------------------------------------------------

def _load_state() -> dict[str, dict]:
    if not _STATE_FILE.exists():
        return {}
    try:
        return json.loads(_STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict[str, dict]) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state))


# -------------------------------------------------------------------
# Public interface
# -------------------------------------------------------------------

def start_discovery(
    user_id: str,
    plan_file: Path,
    vault: Path,
    day_date: date,
    meal_name: str,
    candidates: list[RecipeCandidate],
) -> str:
    """Record pending discovery and return the Discord prompt message.

    The caller (OpenClaw agent) should send this message to Jason
    and then route any reply back through `handle_discovery_reply()`.

    Args:
        user_id: Discord user ID.
        plan_file: Absolute path to the plan file.
        vault: Vault root (used to compute relative path for persistence).
        day_date: The date of the meal needing discovery.
        meal_name: Name of the meal.
        candidates: List of RecipeCandidate from discovery.

    Returns:
        A Discord-formatted message string with candidates and a yes/no prompt.
    """
    # Compute relative path for portability
    try:
        plan_file_rel = str(plan_file.relative_to(vault))
    except ValueError:
        plan_file_rel = str(plan_file)

    state = _load_state()
    state[user_id] = {
        "plan_file_rel": plan_file_rel,
        "day_date": day_date.isoformat(),
        "meal_name": meal_name,
        "candidates": [
            {
                "name": c.name,
                "description": c.description,
                "source_url": c.source_url,
                "score": c.score,
            }
            for c in candidates
        ],
    }
    _save_state(state)

    # Format the prompt
    lines = [f"No recipe found locally for **'{meal_name}'**. Found:"]
    for i, c in enumerate(candidates, 1):
        desc = c.description
        if len(desc) > 100:
            desc = desc[:99] + "…"
        lines.append(f"  **{i}.** {c.name} — {c.source_url}")
        if desc:
            lines.append(f"     _{desc}_")

    lines.append("")
    lines.append(f"Use this recipe? Reply **yes** or **no** (or a number to pick a different one).")

    return "\n".join(lines)


def get_pending_discovery(user_id: str) -> PendingDiscovery | None:
    """Return the pending discovery state for this user, if any."""
    state = _load_state()
    data = state.get(user_id)
    if not data:
        return None
    return PendingDiscovery.from_dict(data)


def handle_discovery_reply(
    user_id: str,
    vault: Path,
    message: str,
) -> tuple[str, bool]:
    """Handle a user's reply to a pending discovery prompt.

    Args:
        user_id: Discord user ID.
        vault: Vault root path.
        message: The user's raw reply (lowercase, stripped by caller).

    Returns:
        (reply_message, flow_complete: bool)
        flow_complete is True when there's nothing more to do.
    """
    pending = get_pending_discovery(user_id)
    if not pending:
        return "", True  # No pending — ignore

    cleaned = message.strip().lower()
    candidates = [
        RecipeCandidate(
            name=c["name"],
            description=c["description"],
            source_url=c["source_url"],
            score=c["score"],
        )
        for c in pending.candidates
    ]

    # "no" / "skip" — clean up and done
    if cleaned in ("no", "n", "skip", "cancel", "skip"):
        _clear_pending(user_id)
        return f"Skipped '{pending.meal_name}' — no recipe linked. `!grocery` will skip it.", True

    # Number selection — pick a specific candidate
    selected: RecipeCandidate | None = None
    if cleaned.isdigit():
        idx = int(cleaned) - 1
        if 0 <= idx < len(candidates):
            selected = candidates[idx]

    # "yes" / "y" / "use this" — use candidate 0 (top/auto-selected)
    if cleaned in ("yes", "y", "yep", "use this", "use", "confirm"):
        if candidates:
            selected = candidates[0]

    if selected is None:
        return (
            f"Reply **yes** to use the top result, **no** to skip, "
            f"or a number 1-{len(candidates)} to pick a different one."
        ), False

    # Save the selected recipe
    postfix = _url_to_postfix(selected.source_url)
    try:
        saved = save_recipe(selected, vault, postfix=postfix)
    except RecipeSaveError as e:
        _clear_pending(user_id)
        return f"❌ Failed to save recipe: {e}. Try again later or add manually.", True

    # Update the plan file with the recipe link
    plan_file = vault / pending.plan_file_rel
    day_date = date.fromisoformat(pending.day_date)
    updated = update_plan_meal_link(plan_file, day_date, saved.link or selected.source_url)

    _clear_pending(user_id)

    if updated:
        return (
            f"✅ Saved **{saved.name}** (`{saved.name.lower().replace(' ', '-')}-{postfix}.md`)"
            f" and updated the plan."
        ), True
    else:
        # Recipe was saved but plan link update failed — still report success
        return (
            f"⚠️ Saved **{saved.name}** but couldn't update the plan file link. "
            f"You may need to re-sync."
        ), True


def _clear_pending(user_id: str) -> None:
    state = _load_state()
    state.pop(user_id, None)
    _save_state(state)