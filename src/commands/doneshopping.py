"""!doneshopping command — post-shopping flow.

Triggers:
  - `!doneshopping` (primary)
  - "done shopping", "shopping done", "shopping complete", "finished shopping"

Flow:
  1. Read checked rows from Sheets Grocery tab
  2. For each checked item: case-insensitive lookup against current pantry
  3. If item exists in pantry → skip
  4. If item is new → add to pantry-items.md under its category section
  5. Post summary to Discord: "X items added to pantry (name, name, and N others). Y items were already in stock."
"""
from __future__ import annotations

import re
from pathlib import Path

from pantry._categorize import infer_category
from pantry.inventory import add_items, read_pantry, write_pantry
from sheets import SheetsAuth, SheetsClient
from shared.errors import SheetSyncError
from shared.types import GroceryCategory, PantryItem

# -------------------------------------------------------------------
# Trigger patterns
# -------------------------------------------------------------------

_COMMAND_PATTERNS = [
    re.compile(r"^!doneshopping\s*$", re.IGNORECASE),
]

_PLAIN_PATTERNS = [
    re.compile(r"^done\s+shopping$", re.IGNORECASE),
    re.compile(r"^shopping\s+done$", re.IGNORECASE),
    re.compile(r"^shopping\s+complete$", re.IGNORECASE),
    re.compile(r"^finished\s+shopping$", re.IGNORECASE),
]


def is_doneshopping_trigger(message: str) -> bool:
    """Return True if the message matches a !doneshopping trigger."""
    msg = message.strip()
    if any(p.match(msg) for p in _COMMAND_PATTERNS):
        return True
    if any(p.match(msg) for p in _PLAIN_PATTERNS):
        return True
    return False


# -------------------------------------------------------------------
# Main handler
# -------------------------------------------------------------------

def handle_doneshopping(
    pantry_file: Path,
    vault: Path,
) -> str:
    """Process a done-shopping event.

    Reads checked items from the Google Sheets Grocery tab,
    adds new ones to the pantry, and returns a Discord message.

    Args:
        pantry_file: Path to pantry-items.md.
        vault: Path to the Obsidian vault (for Sheets auth path).

    Returns:
        A message string for Discord.
    """
    # Read checked items from Sheets
    try:
        client = SheetsAuth.build()
    except SheetSyncError as e:
        return f"❌ Google Sheets auth failed: {e.details}"

    try:
        checked_names = client.read_checked_grocery_items()
    except SheetSyncError as e:
        return f"❌ Failed to read grocery list from Sheets: {e.details}"

    if not checked_names:
        return "No items checked off in the grocery list. Check off items in Sheets then run `!doneshopping` again."

    # Read current pantry
    pantry = read_pantry(pantry_file)
    existing_names = {p.name.lower() for p in pantry.items}

    # Separate new vs already-have
    new_items: list[PantryItem] = []
    skipped: list[str] = []

    for name in checked_names:
        if name.lower() in existing_names:
            skipped.append(name)
        else:
            category = infer_category(name)
            new_items.append(PantryItem(name=name, location=None))

    # Add new items to pantry
    updated_pantry = add_items(pantry, new_items)

    # Write back to pantry file
    categories = list(GroceryCategory)
    write_pantry(pantry_file, updated_pantry, categories)

    # Format Discord summary
    return _format_summary(new_items, skipped, pantry_file)


def _format_summary(
    new_items: list[PantryItem],
    skipped: list[str],
    pantry_file: Path,
) -> str:
    """Format a nice Discord summary message."""
    new_count = len(new_items)
    skipped_count = len(skipped)

    # Build item list (cap at 5 for display)
    display_items = new_items[:5]
    display_names = [f"**{item.name}**" for item in display_items]
    remaining = new_count - len(display_names)

    if new_count == 0:
        # Nothing new added — all were already in stock
        msg = f"🛒 All {skipped_count} checked items were already in your pantry."
    elif new_count == 1:
        msg = f"✅ Added 1 item to pantry: {display_names[0]}"
        if skipped_count > 0:
            msg += f" ({skipped_count} already in stock)"
    else:
        if remaining > 0:
            msg = f"✅ Added {new_count} items to pantry ({', '.join(display_names)}, and {remaining} others)"
        else:
            listed = ", ".join(display_names[:-1])
            last = display_names[-1]
            msg = f"✅ Added {new_count} items to pantry ({listed}, and {last})"
        if skipped_count > 0:
            msg += f" — {skipped_count} already in stock"

    # Add link to pantry file
    if pantry_file.exists():
        msg += f"\n📋 [View pantry](file://{pantry_file})"

    return msg

