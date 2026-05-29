"""Pantry photo review command — Discord-side handler.

This module bridges the OpenClaw Discord event layer and the photo
analysis pipeline. It manages:
  1. Photo accumulation across multiple Discord messages
  2. Trigger detection ("done", "review pantry", etc.)
  3. Calling the image tool for each photo URL
  4. Presenting the suggestion list to Discord
  5. Processing corrections and confirmations
  6. Writing updated pantry to pantry-items.md

Integration: OpenClaw Discord events call these functions when
attachment or message events fire in the DM channel. The caller is
responsible for routing; this module handles only the logic.

State machine (per-user, persisted to disk):
    IDLE          → waiting for photo attachments
    AWAITING_CONFIRM → suggestion posted, waiting for corrections/confirm
    (IDLE clears after confirm)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable

from pantry._photo import analyze_pantry_photos, format_suggestion
from pantry.inventory import add_items, read_pantry, write_pantry
from shared.types import (
    Confidence,
    GroceryCategory,
    ItemStatus,
    Pantry,
    PantrySuggestion,
    PantryItem,
    SuggestedItem,
)


# -------------------------------------------------------------------
# State persistence
# -------------------------------------------------------------------

_STATE_DIR = Path.home() / ".config" / "family-meal-support"
_STATE_FILE = _STATE_DIR / "pantry-review-state.json"


def _load_state() -> dict:
    if not _STATE_FILE.exists():
        return {}
    try:
        return json.loads(_STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state))


# -------------------------------------------------------------------
# Trigger patterns
# -------------------------------------------------------------------

_PHOTO_TRIGGER_PATTERNS = [
    re.compile(r"^done\s*$", re.IGNORECASE),
    re.compile(r"^review\s+pantry\s*$", re.IGNORECASE),
    re.compile(r"^analyze\s+pantry\s*$", re.IGNORECASE),
    re.compile(r"^check\s+pantry\s*$", re.IGNORECASE),
]

# Patterns that arrive as text (not photo triggers)
_CORRECTION_CHANGE = re.compile(
    r"^change\s+(.+?)\s+to\s+(.+)$",
    re.IGNORECASE,
)
_CORRECTION_REMOVE = re.compile(
    r"^remove\s+(.+)$",
    re.IGNORECASE,
)
_CONFIRM_PATTERNS = [
    re.compile(r"^confirm\s*$", re.IGNORECASE),
    re.compile(r"^looks\s+good\s*$", re.IGNORECASE),
    re.compile(r"^that.?s?\s+right\s*$", re.IGNORECASE),
    re.compile(r"^yep[.!?]*\s*$", re.IGNORECASE),
]


def is_review_trigger(message: str) -> bool:
    """Return True if the message signals end of photo submission."""
    msg = message.strip()
    return any(p.match(msg) for p in _PHOTO_TRIGGER_PATTERNS)


def is_confirm(message: str) -> bool:
    """Return True if the message is a plain confirmation."""
    msg = message.strip()
    return any(p.match(msg) for p in _CONFIRM_PATTERNS)


def parse_correction(message: str) -> tuple[str, str] | list[str] | None:
    """Parse a correction message.

    Returns:
      ("change", "old_name", "new_name") for "change X to Y"
      ("remove", "item_name") for "remove X"
      None if the message is not a correction.
    """
    msg = message.strip()

    change_match = _CORRECTION_CHANGE.match(msg)
    if change_match:
        return ("change", change_match.group(1).strip(), change_match.group(2).strip())

    remove_match = _CORRECTION_REMOVE.match(msg)
    if remove_match:
        return ("remove", remove_match.group(1).strip())

    return None


# -------------------------------------------------------------------
# State machine helpers
# -------------------------------------------------------------------

def accumulate_photo(user_id: str, image_url: str) -> None:
    """Add a photo URL to the pending review for this user."""
    state = _load_state()
    user_state = state.get(user_id, {})
    photos = user_state.get("pending_photos", [])
    if image_url not in photos:
        photos.append(image_url)
    user_state["pending_photos"] = photos
    state[user_id] = user_state
    _save_state(state)


def get_pending_photos(user_id: str) -> list[str]:
    """Return the list of accumulated photo URLs for this user."""
    state = _load_state()
    return state.get(user_id, {}).get("pending_photos", [])


def clear_pending(user_id: str) -> None:
    """Clear all pending state for this user (after confirm or cancel)."""
    state = _load_state()
    if user_id in state:
        del state[user_id]
        _save_state(state)


def set_awaiting_confirm(user_id: str, suggestion: PantrySuggestion) -> None:
    """Persist the suggestion so corrections can reference it."""
    state = _load_state()
    user_state = state.get(user_id, {})
    user_state["suggestion"] = {
        "items": [
            {
                "name": i.name,
                "confidence": i.confidence.value,
                "status": i.status.value,
                "category": i.category.value,
                "quantity": i.quantity,
            }
            for i in suggestion.items
        ],
        "unclear_photos": suggestion.unclear_photos,
    }
    user_state["pending_photos"] = []  # Clear photos — they're being processed
    state[user_id] = user_state
    _save_state(state)


def get_awaiting_suggestion(user_id: str) -> PantrySuggestion | None:
    """Retrieve the last suggestion for this user, if any."""
    state = _load_state()
    user_state = state.get(user_id, {})
    suggestion_data = user_state.get("suggestion")
    if not suggestion_data:
        return None
    try:
        items = [
            SuggestedItem(
                name=d["name"],
                confidence=Confidence(d["confidence"]),
                status=ItemStatus(d["status"]),
                category=GroceryCategory(d["category"]),
                quantity=d.get("quantity"),
            )
            for d in suggestion_data["items"]
        ]
        return PantrySuggestion(
            items=items,
            unclear_photos=suggestion_data.get("unclear_photos", []),
        )
    except (KeyError, ValueError):
        return None


# -------------------------------------------------------------------
# Image analysis integration
# -------------------------------------------------------------------

ImageToolFunc = Callable[[str], dict]
"""Signature: call_image_tool(image_url: str) -> dict

The dict must contain:
  {
      "items": [{"name": str, "quantity": str|None, "confidence": float}],
      "unclear": bool,
      "photo_url": str,
  }

Callers pass the actual OpenClaw image-tool invoker here. Tests pass a mock.
"""


def run_analysis(
    user_id: str,
    pantry_file: Path,
    call_image_tool: ImageToolFunc,
) -> tuple[str, bool]:
    """Run full photo analysis for a user.

    Reads accumulated photo URLs, calls `call_image_tool` for each,
    merges results, compares with pantry, and returns a formatted
    Discord message.

    After calling this, the bot is in AWAITING_CONFIRM state.

    Args:
        user_id: Discord user id, used for state key.
        pantry_file: Path to pantry-items.md.
        call_image_tool: A callable that takes an image URL and returns
            a photo result dict (see _photo.py module docstring).

    Returns:
        (discord_message: str, success: bool)
        success is False if no photos were accumulated.
    """
    photo_urls = get_pending_photos(user_id)
    if not photo_urls:
        return "_No photos accumulated. Send fridge/pantry photos first, then `done`._", False

    # Analyze each photo
    photo_results: list[dict] = []
    for url in photo_urls:
        try:
            result = call_image_tool(url)
            result["photo_url"] = url
            photo_results.append(result)
        except Exception:
            # Treat a failed analysis as unclear
            photo_results.append({"photo_url": url, "items": [], "unclear": True})

    # Load current pantry
    pantry = read_pantry(pantry_file)

    # Run the analysis pipeline
    suggestion = analyze_pantry_photos(photo_results, pantry)

    # Persist suggestion for corrections
    set_awaiting_confirm(user_id, suggestion)

    # Format and return Discord message
    if not suggestion.items and not suggestion.unclear_photos:
        clear_pending(user_id)
        return (
            "_Couldn't identify many items in these photos — try retaking with better lighting._"
        ), False

    # If ALL photos were unclear (e.g. image tool threw an exception for all),
    # treat as a failure so the caller knows to retry.
    if not suggestion.items and suggestion.unclear_photos:
        return (
            "_Couldn't identify many items in these photos — try retaking with better lighting._"
        ), False

    msg = format_suggestion(suggestion)
    return msg, True


# -------------------------------------------------------------------
# Correction handling
# -------------------------------------------------------------------

def handle_correction(
    user_id: str,
    message: str,
) -> tuple[str, bool | None]:
    """Handle a correction or confirmation message.

    Parses the message for "change X to Y", "remove X", or confirm
    patterns, applies the change to the stored suggestion, and returns
    an updated Discord message.

    Args:
        user_id: Discord user id.
        message: The user's reply to the suggestion list.

    Returns:
        (updated_discord_message, confirmed: bool | None)
        confirmed is True if the user just confirmed.
        confirmed is None if the message wasn't a correction either.
        confirmed is False if no suggestion is pending.
    """
    suggestion = get_awaiting_suggestion(user_id)
    if suggestion is None:
        return "", None  # Not in confirm state — ignore

    # Check for confirm first
    if is_confirm(message):
        return _confirm(user_id, suggestion)

    # Parse correction
    correction = parse_correction(message)
    if correction is None:
        return "", None  # Not a recognized correction — ignore

    if correction[0] == "change":
        _, old_name, new_name = correction
        return _apply_change(user_id, suggestion, old_name, new_name)
    elif correction[0] == "remove":
        _, item_name = correction
        return _apply_remove(user_id, suggestion, item_name)

    return "", None


def _apply_change(
    user_id: str,
    suggestion: PantrySuggestion,
    old_name: str,
    new_name: str,
) -> tuple[str, bool | None]:
    """Apply a "change X to Y" correction."""
    old_lower = old_name.lower()
    new_items = []
    found = False
    for item in suggestion.items:
        if item.name.lower() == old_lower:
            new_items.append(
                SuggestedItem(
                    name=new_name,
                    confidence=item.confidence,
                    status=item.status,
                    category=item.category,
                    quantity=item.quantity,
                )
            )
            found = True
        else:
            new_items.append(item)

    if not found:
        return f"_Couldn't find `{old_name}` in the suggestion list. Check the spelling and try again._", None

    updated = PantrySuggestion(
        items=new_items,
        unclear_photos=suggestion.unclear_photos,
    )
    set_awaiting_confirm(user_id, updated)
    return format_suggestion(updated), None


def _apply_remove(
    user_id: str,
    suggestion: PantrySuggestion,
    item_name: str,
) -> tuple[str, bool | None]:
    """Apply a "remove X" correction."""
    name_lower = item_name.lower()
    new_items = [i for i in suggestion.items if i.name.lower() != name_lower]
    if len(new_items) == len(suggestion.items):
        return f"_Couldn't find `{item_name}` in the suggestion list. Check the spelling and try again._", None

    updated = PantrySuggestion(
        items=new_items,
        unclear_photos=suggestion.unclear_photos,
    )
    set_awaiting_confirm(user_id, updated)
    return format_suggestion(updated), None


def _confirm(user_id: str, suggestion: PantrySuggestion) -> tuple[str, True]:
    """Apply confirmed suggestion to pantry and return summary message."""
    new_items = [
        PantryItem(name=i.name, quantity=i.quantity, location=None)
        for i in suggestion.items
        if i.status == ItemStatus.NEW
    ]

    if not new_items:
        clear_pending(user_id)
        return "✅ No new items to add — pantry is up to date.", True

    current_pantry = read_pantry(Path.home() / "Documents" / "Obsidian" / "reference" / "grocery-lists" / "pantry-items.md")
    updated_pantry = add_items(current_pantry, new_items)

    pantry_file = Path.home() / "Documents" / "Obsidian" / "reference" / "grocery-lists" / "pantry-items.md"
    categories = list(GroceryCategory)
    write_pantry(pantry_file, updated_pantry, categories)

    clear_pending(user_id)

    # Format summary
    names = [i.name for i in new_items]
    if len(names) == 1:
        msg = f"✅ Pantry updated: added **{names[0]}**"
    else:
        msg = f"✅ Pantry updated: added **{len(names)} items** — {', '.join(names[:-1])}, and {names[-1]}"
    msg += f"\n📋 [View pantry](file://{pantry_file})"

    return msg, True
