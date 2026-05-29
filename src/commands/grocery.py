"""!grocery command — generate a grocery list from the current meal plan."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone

from pathlib import Path

from grocery.generate import generate_grocery_list
from meal_plan import MealPlan
from obsidian.vault import read_meal_plan
from obsidian.recipes import ObsidianRecipeStore
from pantry.inventory import read_pantry, read_staples
from sheets import SheetsAuth, SheetsClient
from shared.errors import SheetSyncError

# -------------------------------------------------------------------
# Status tracking
# -------------------------------------------------------------------
_STATUS_DIR = Path.expanduser(Path("~/.config/family-meal-support"))
_STATUS_FILE = _STATUS_DIR / "grocery-status.json"


def _get_status_path() -> Path:
    return _STATUS_DIR / "grocery-status.json"


def _load_status() -> dict:
    path = _get_status_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_status(data: dict) -> None:
    path = _get_status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _get_week_monday(today: date) -> date:
    return today - timedelta(days=today.weekday())


def _build_grocery_list(
    vault: Path,
    plans_dir: Path,
    pantry_file: Path,
    today: date,
) -> tuple[MealPlan, list]:
    """Build the grocery list and return (plan, grocery_items)."""
    monday = _get_week_monday(today)
    plan_file = plans_dir / f"{monday.strftime('%Y-%m-%d')}.md"

    plan = read_meal_plan(plan_file)
    if plan is None:
        return MealPlan(week_start=monday, days=[]), []

    pantry = read_pantry(pantry_file)
    store = ObsidianRecipeStore(vault / "reference" / "meal-planning" / "meals")
    staples = read_staples(pantry_file)
    grocery_list = generate_grocery_list(plan, pantry, store, staples=staples)
    return plan, grocery_list.items


# -------------------------------------------------------------------
# !grocery status
# -------------------------------------------------------------------

def handle_grocery_status(vault: Path) -> str:
    """Return a quick count without generating."""
    status = _load_status()
    if not status:
        return "No grocery list generated yet. Run `!grocery` to generate one."

    generated = status.get("generated_at", "never")
    count = status.get("item_count", 0)
    categories = status.get("categories", 0)

    # Parse and format the timestamp
    try:
        dt = datetime.fromisoformat(generated)
        formatted = dt.strftime("%A %-I:%M %p").replace("AM", "AM").replace("PM", "PM")
    except Exception:
        formatted = generated

    return f"📋 **{count} items** across **{categories} categories**, last generated {formatted}"


# -------------------------------------------------------------------
# !grocery (full generation)
# -------------------------------------------------------------------

def handle_grocery_generate(
    vault: Path,
    plans_dir: Path,
    pantry_file: Path,
) -> str:
    """Generate the grocery list and write to Google Sheets.

    Returns a message for Discord.
    """
    today = date.today()
    monday = _get_week_monday(today)

    plan, items = _build_grocery_list(vault, plans_dir, pantry_file, today)

    if not items:
        return "🍽️ No meals planned this week — can't generate a grocery list."

    # Write to Sheets
    try:
        client = SheetsAuth.build()
    except SheetSyncError as e:
        return f"❌ Google Sheets error: {e.details}"

    from shared.types import GroceryList as GL
    grocery_list = GL(week_start=monday, items=items)

    try:
        client.write_grocery_list(grocery_list)
    except SheetSyncError as e:
        return f"❌ Failed to write grocery list to Sheets: {e.details}"

    # Count unique categories represented
    categories = len({item.category for item in items if item.source_recipe != "staples"})
    category_count = len({item.category for item in items})

    # Save status
    _save_status({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "item_count": len(items),
        "categories": category_count,
        "week_start": monday.isoformat(),
    })

    spreadsheet_id = os.environ.get("SHEETS_SPREADSHEET_ID", "")
    sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}" if spreadsheet_id else ""

    msg = f"✅ Grocery list generated: **{len(items)} items** across **{category_count} categories**"
    if sheet_url:
        msg += f"\n🔗 [Open Sheet]({sheet_url})"

    return msg
