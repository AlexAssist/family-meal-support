"""!sync command — bidirectional sync between Obsidian and Google Sheets."""
from __future__ import annotations

from datetime import date, timedelta

from meal_plan import MealPlan
from meal_plan._sync import confirm_pull, sync_push, sync_pull, _DiscoveryResult
from obsidian.vault import update_plan_meal_link
from obsidian.recipe_saver import save_recipe, RecipeSaveError, _url_to_postfix
from recipes.discovery import discover_recipe
from shared.errors import SheetSyncError
from sheets import SheetsAuth, SheetsClient
from commands.pending_discovery import (
    get_pending_discovery,
    handle_discovery_reply,
    _clear_pending as clear_pending,
)


# -------------------------------------------------------------------
# Pending pull state (for conflict resolution)
# -------------------------------------------------------------------
_pending_pull: dict[str, MealPlan] = {}
_pending_discovery_result: dict[str, _DiscoveryResult] = {}


# -------------------------------------------------------------------
# Command handlers
# -------------------------------------------------------------------

def handle_sync_push(vault, plans_dir) -> str:
    """Handle !sync push — push current week's plan to Sheets."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())

    try:
        client = SheetsAuth.build()
    except SheetSyncError as e:
        return f"❌ {e}"

    result = sync_push(vault, plans_dir, client, monday)
    return f"✅ {result.message}" if result.success else f"❌ {result.message}"


def handle_sync_pull(vault, plans_dir, user_id: str) -> str:
    """Handle !sync pull — pull plan from Sheets into Obsidian.

    Handles conflict detection interactively. Returns a message for
    Discord (including prompts when user confirmation is needed).
    For discovery flows, returns a prompt that requires a yes/no reply.
    """
    today = date.today()
    monday = today - timedelta(days=today.weekday())

    # Check for pending discovery reply from this user
    pending = get_pending_discovery(user_id)
    if pending:
        # The pending state is handled by the skill routing layer
        # Return a sentinel that tells the skill to route this as a discovery reply
        return "_PENDING_DISCOVERY_"

    try:
        client = SheetsAuth.build()
    except SheetSyncError as e:
        return f"❌ {e}"

    result, conflict = sync_pull(vault, plans_dir, client, monday)

    if conflict:
        _pending_pull[user_id] = conflict.sheet_plan
        ts = conflict.last_push_timestamp
        return (
            f"⚠️ Sheets has changes since your last push (edited {ts}). "
            f"Pull anyway? (y/n)\n"
            f"Plan: {conflict.sheet_plan.days[0].date.strftime('%b %-d')} - "
            f"{conflict.sheet_plan.days[-1].date.strftime('%b %-d')}, "
            f"{len(conflict.sheet_plan.days)} days"
        )

    # No conflict — write to Obsidian directly
    sheet_plan = client.read_meal_plan(monday)
    write_result, discovery_result = confirm_pull(vault, plans_dir, client, sheet_plan)

    msg = f"✅ {write_result.message}"

    # If discovery is needed, append the prompt to the same message
    if discovery_result:
        _pending_discovery_result[user_id] = discovery_result
        msg += f"\n\n{discovery_result.prompt}"

    return msg


def handle_sync_pull_confirm(vault, plans_dir, user_id: str, confirmed: bool) -> str:
    """Handle user response to conflict prompt.

    Args:
        confirmed: True if user answered "y", False if "n"
    """
    if not confirmed:
        return "❌ Pull cancelled — your local plan is unchanged."

    if user_id not in _pending_pull:
        return "❌ No pending pull to confirm."

    sheet_plan = _pending_pull.pop(user_id)

    try:
        client = SheetsAuth.build()
    except SheetSyncError as e:
        return f"❌ {e}"

    write_result, discovery_result = confirm_pull(vault, plans_dir, client, sheet_plan)
    msg = f"✅ {write_result.message}"

    if discovery_result:
        _pending_discovery_result[user_id] = discovery_result
        msg += f"\n\n{discovery_result.prompt}"

    return msg


def handle_sync_discovery_reply(
    vault: Path,
    user_id: str,
    message: str,
) -> str | None:
    """Handle a user reply to a pending recipe discovery prompt.

    Called by the skill layer when the user replies to a discovery prompt
    from a previous !sync pull.

    Returns a Discord message, or None if the flow is not active.
    """
    pending = get_pending_discovery(user_id)
    if not pending:
        return None

    reply_msg, done = handle_discovery_reply(user_id, vault, message)
    if done:
        # Check if there are more pending discoveries to surface
        _pending_discovery_result.pop(user_id, None)
        # TODO: could iterate through remaining discovery results
    return reply_msg


def has_pending_discovery(user_id: str) -> bool:
    """Return True if user has a pending discovery waiting for reply."""
    return get_pending_discovery(user_id) is not None