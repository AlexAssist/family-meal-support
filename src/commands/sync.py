"""!sync command — bidirectional sync between Obsidian and Google Sheets."""
from __future__ import annotations

from datetime import date, timedelta

from meal_plan import MealPlan
from meal_plan._sync import confirm_pull, sync_push, sync_pull
from shared.errors import SheetSyncError
from sheets import SheetsAuth, SheetsClient


# -------------------------------------------------------------------
# Pending pull state (for conflict resolution)
# -------------------------------------------------------------------
_pending_pull: dict[str, MealPlan] = {}


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
    """
    today = date.today()
    monday = today - timedelta(days=today.weekday())

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
    write_result = confirm_pull(vault, plans_dir, client, sheet_plan)
    return f"✅ {write_result.message}"


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

    result = confirm_pull(vault, plans_dir, client, sheet_plan)
    return f"✅ {result.message}"