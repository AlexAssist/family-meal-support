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

import json
import re
from pathlib import Path

from pantry.inventory import add_items, read_pantry, write_pantry
from sheets import SheetsClient
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
# Category inference
# -------------------------------------------------------------------

# Approximate category inference for new items (simple keyword matching)
_CATEGORY_KEYWORDS: dict[GroceryCategory, list[str]] = {
    GroceryCategory.DAIRY: [
        "milk", "cream", "cheese", "butter", "yogurt", "sour cream",
        "egg", "deli meat", "lunch meat", "cheddar", "mozzarella",
        "parmesan", "cream cheese", "cottage cheese",
    ],
    GroceryCategory.PRODUCE: [
        "tomato", "lettuce", "spinach", "kale", "pepper", "onion",
        "carrot", "celery", "broccoli", "cauliflower", "cucumber",
        "apple", "banana", "berry", "grape", "lemon", "lime",
        "garlic", "ginger", "potato", "mushroom", "avocado",
        "salad", "greens", "herbs", "cilantro", "parsley",
    ],
    GroceryCategory.MEAT_SEAFOOD: [
        "chicken", "beef", "pork", "fish", "salmon", "shrimp",
        "turkey", "bacon", "sausage", "ground beef", "steak",
        "meatball", "ham", "lamb", "veal", "crab", "lobster",
    ],
    GroceryCategory.BAKERY: [
        "bread", "bun", "roll", "tortilla", "pita", "bagel",
        "croissant", "muffin", "biscuit", "naan", "chapatti",
    ],
    GroceryCategory.PANTRY: [
        "pasta", "rice", "flour", "sugar", "oil", "vinegar",
        "cereal", "oat", "quinoa", "lentil", "bean", "broth",
        "stock", "soup", "canned", "dried", "pasta sauce",
        "noodle",
    ],
    GroceryCategory.FROZEN: [
        "frozen", "ice cream", "pizza", "fish stick", "waffle",
        "fries", "popsicle",
    ],
    GroceryCategory.CONDIMENTS: [
        "ketchup", "mustard", "mayo", "mayonnaise", "sauce",
        "soy sauce", "hot sauce", "salad dressing", "relish",
        "jam", "jelly", "honey", "syrup", "chocolate syrup",
        "barbecue", "bbq", "buffalo", "peanut butter",
    ],
    GroceryCategory.SNACKS: [
        "chip", "crisp", "cracker", "pretzel", "popcorn",
        "cookie", "candy", "chocolate", "nut", "trail mix",
    ],
    GroceryCategory.BEVERAGES: [
        "soda", "juice", "water", "tea", "coffee", "drink",
        "sports drink", "energy drink", "wine", "beer",
    ],
}


def _infer_category(item_name: str) -> GroceryCategory:
    """Infer a GroceryCategory from an item name using keyword matching."""
    name_lower = item_name.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return category
    return GroceryCategory.OTHER


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
        client = _get_sheets_client(vault)
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
            category = _infer_category(name)
            new_items.append(PantryItem(name=name, location=None))

    # Add new items to pantry
    updated_pantry = add_items(pantry, new_items)

    # Write back to pantry file
    categories = list(GroceryCategory)
    write_pantry(pantry_file, updated_pantry, categories, infer_category=_infer_category)

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


# -------------------------------------------------------------------
# Sheets auth (same pattern as grocery.py)
# -------------------------------------------------------------------

def _get_sheets_client(vault: Path) -> SheetsClient:
    """Authenticate to Google Sheets and return a SheetsClient."""
    import os

    _CREDS_PATH = Path(os.environ.get("CREDS_PATH", str(vault.parent / ".config" / "family-meal-support" / "credentials.json")))
    _TOKEN_PATH = Path(os.environ.get("TOKEN_PATH", str(vault.parent / ".config" / "family-meal-support" / "sheets-token.json")))
    _SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

    if not _CREDS_PATH.exists():
        raise SheetSyncError("auth", f"credentials.json not found at {_CREDS_PATH}")

    creds = None
    if _TOKEN_PATH.exists():
        cred_data = json.loads(_TOKEN_PATH.read_text())
        from google.oauth2.credentials import Credentials as CredsClass
        creds = CredsClass.from_authorized_user_info(cred_data, _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(str(_CREDS_PATH), _SCOPES)
            creds = flow.run_local_server(port=0)
        _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_PATH.write_text(json.dumps(creds.to_json()))

    from googleapiclient.discovery import build
    service = build("sheets", "v4", credentials=creds)

    spreadsheet_id = os.environ.get("SHEETS_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise SheetSyncError("auth", "SHEETS_SPREADSHEET_ID environment variable not set")

    return SheetsClient(service, spreadsheet_id)