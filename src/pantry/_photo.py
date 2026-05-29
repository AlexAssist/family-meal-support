"""Pantry photo analysis — private module.

This is an internal detail of the pantry module. The public interface
for photo-based review is `analyze_pantry_photos`.

Image analysis (the actual call to the OpenClaw `image` tool) happens
in the OpenClaw agent context. This module operates on already-parsed
results — a list of per-photo dicts produced by the image model.

Raw photo result shape:
    {
        "photo_url": str,
        "items": [
            {
                "name": str,          # e.g. "Lactantia Salted Butter"
                "quantity": str | None,  # e.g. "1 stick", "half carton"
                "confidence": float,  # 0.0 – 1.0
            },
            ...
        ],
        "unclear": bool,  # True if photo quality was too poor to interpret
    }

All functions here are pure — no I/O, no network calls.
"""
from __future__ import annotations

from pantry.inventory import read_pantry
from shared.types import (
    Confidence,
    GroceryCategory,
    ItemStatus,
    Pantry,
    PantrySuggestion,
    SuggestedItem,
)

# Confidence threshold below which items get a [?] marker in Discord output
_CONFIDENCE_THRESHOLD = 0.80


# -------------------------------------------------------------------
# Category inference (same keyword map as doneshopping.py)
# -------------------------------------------------------------------

_CATEGORY_KEYWORDS: dict[GroceryCategory, list[str]] = {
    GroceryCategory.DAIRY: [
        "milk", "cream", "cheese", "butter", "yogurt", "sour cream",
        "egg", "deli meat", "lunch meat", "cheddar", "mozzarella",
        "parmesan", "cream cheese", "cottage cheese", "half and half",
        "whipping cream", "ricotta", "feta", "brie", "gouda",
    ],
    GroceryCategory.PRODUCE: [
        "tomato", "lettuce", "spinach", "kale", "pepper", "onion",
        "carrot", "celery", "broccoli", "cauliflower", "cucumber",
        "apple", "banana", "berry", "grape", "lemon", "lime", "orange",
        "garlic", "ginger", "potato", "mushroom", "avocado",
        "salad", "greens", "herbs", "cilantro", "parsley", "basil",
        "zucchini", "squash", "asparagus", "cabbage", "corn", "pea",
        "bean sprout", "bok choy", "jalapeño", "poblano",
    ],
    GroceryCategory.MEAT_SEAFOOD: [
        "chicken", "beef", "pork", "fish", "salmon", "shrimp",
        "turkey", "bacon", "sausage", "ground beef", "steak",
        "meatball", "ham", "lamb", "veal", "crab", "lobster",
        "tilapia", "cod", "tuna", "trout", "anchovy", "sardine",
        "ribeye", "sirloin", "tenderloin", "chuck", "brisket",
        "pork chop", "pork loin", "bacon", "prosciutto", "pepperoni",
    ],
    GroceryCategory.BAKERY: [
        "bread", "bun", "roll", "tortilla", "pita", "bagel",
        "croissant", "muffin", "biscuit", "naan", "chapatti",
        "focaccia", "ciabatta", "sourdough", "baguette", "brioche",
    ],
    GroceryCategory.PANTRY: [
        "pasta", "rice", "flour", "sugar", "oil", "vinegar",
        "cereal", "oat", "quinoa", "lentil", "bean", "broth",
        "stock", "soup", "canned", "dried", "pasta sauce",
        "noodle", "noodles", "cookie", "chocolate",
        "cocoa", "baking", "yeast", "cornstarch", "breadcrumb",
        "maple syrup", "jam",
        "coconut milk", "tomato paste", "tomato sauce",
    ],
    GroceryCategory.FROZEN: [
        "frozen", "ice cream", "pizza", "fish stick", "waffle",
        "fries", "popsicle", "frozen dinner", "frozen vegetable",
        "frozen fruit", "frozen berry",
    ],
    GroceryCategory.CONDIMENTS: [
        "ketchup", "mustard", "mayo", "mayonnaise", "sauce",
        "soy sauce", "hot sauce", "salad dressing", "relish",
        "jam", "jelly", "honey", "syrup", "chocolate syrup",
        "barbecue", "bbq", "buffalo", "peanut butter",
        "teriyaki", "salsa", "guacamole", "tahini", "hummus",
        "worcestershire", "fish sauce", "oyster sauce",
    ],
    GroceryCategory.SNACKS: [
        "chip", "crisp", "cracker", "pretzel", "popcorn",
        "cookie", "candy", "chocolate", "nut", "trail mix",
        "granola bar", "energy bar", "fruit snack", "gummy",
    ],
    GroceryCategory.BEVERAGES: [
        "orange juice", "apple juice", "cranberry juice", "grape juice",
        "tomato juice", "vegetable juice", "mango juice",
        "soda", "juice", "water", "tea", "coffee", "drink",
        "sports drink", "energy drink", "wine", "beer",
        "sparkling water", "flavored water", "kombucha",
    ],
}


def _infer_category(item_name: str) -> GroceryCategory:
    """Infer a GroceryCategory from an item name using keyword matching.

    The keyword with the most characters wins, regardless of which
    category it belongs to. This prevents short keywords (e.g. "butter")
    from shadowing longer ones (e.g. "peanut butter").
    """
    name_lower = item_name.lower()
    best_match: tuple[int, GroceryCategory] = (-1, GroceryCategory.OTHER)

    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                if len(kw) > best_match[0]:
                    best_match = (len(kw), category)

    return best_match[1]


# -------------------------------------------------------------------
# Core analysis pipeline
# -------------------------------------------------------------------

def analyze_pantry_photos(
    photo_results: list[dict],
    pantry: Pantry,
) -> PantrySuggestion:
    """Analyze pantry photos and produce a suggestion.

    This is the single public entry point for photo-based review.

    Args:
        photo_results: List of per-photo result dicts (see module docstring).
                      An empty list means no photos were provided.
        pantry: The current Pantry, used to mark items as NEW vs ALREADY_IN_PANTRY.

    Returns:
        PantrySuggestion with categorized, deduplicated items and any
        unclear photo URLs.
    """
    if not photo_results:
        return PantrySuggestion(items=[], unclear_photos=[])

    # 1. Collect all items across photos
    all_raw_items: list[dict] = []
    unclear_photos: list[str] = []

    for result in photo_results:
        if result.get("unclear"):
            unclear_photos.append(result.get("photo_url", ""))
            continue
        all_raw_items.extend(result.get("items", []))

    # 2. Merge duplicates across photos
    merged = _merge_results(all_raw_items)

    # 3. Compare with pantry to set status
    suggestion = _compare_with_pantry(merged, pantry)

    # 4. Attach categories (infer for new items, mark already_in_pantry as OTHER)
    items = []
    for item in suggestion.items:
        if item.status == ItemStatus.NEW:
            cat = _infer_category(item.name)
        else:
            cat = GroceryCategory.OTHER
        items.append(
            SuggestedItem(
                name=item.name,
                confidence=item.confidence,
                status=item.status,
                category=cat,
                quantity=item.quantity,
            )
        )

    return PantrySuggestion(items=items, unclear_photos=unclear_photos)


def _merge_results(raw_items: list[dict]) -> list[SuggestedItem]:
    """Deduplicate items seen across multiple photos.

    Items are matched case-insensitively. When the same item appears
    in multiple photos, the entry with the highest confidence is kept.

    Args:
        raw_items: Flattened list of item dicts from all photos.

    Returns:
        Deduplicated list of SuggestedItem (status not yet set).
    """
    # best[name_lower] = best_item_dict (highest confidence)
    best: dict[str, dict] = {}

    for raw in raw_items:
        name = raw.get("name", "").strip()
        if not name:
            continue
        name_lower = name.lower()
        confidence = float(raw.get("confidence", 0.5))

        existing = best.get(name_lower)
        if existing is None or confidence > float(existing.get("confidence", 0.0)):
            best[name_lower] = {
                "name": name,
                "confidence": confidence,
                "quantity": raw.get("quantity"),
            }

    result: list[SuggestedItem] = []
    for name_lower, info in best.items():
        confidence = Confidence.from_score(float(info["confidence"]))
        result.append(
            SuggestedItem(
                name=info["name"],
                confidence=confidence,
                status=ItemStatus.NEW,  # temporarily set, corrected in _compare_with_pantry
                category=GroceryCategory.OTHER,
                quantity=info.get("quantity"),
            )
        )

    # Sort: high confidence first, then alphabetical
    # Note: Confidence enum orders alphabetically (HIGH, LOW, MEDIUM),
    # so we use a numeric map for correct sort order.
    _CONF_LEVEL = {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1}
    result.sort(key=lambda i: (-_CONF_LEVEL[i.confidence], i.name.lower()))
    return result


def _compare_with_pantry(
    items: list[SuggestedItem],
    pantry: Pantry,
) -> PantrySuggestion:
    """Mark each item as NEW or ALREADY_IN_PANTRY based on the current pantry."""
    pantry_names_lower = {p.name.lower() for p in pantry.items}
    marked = [
        SuggestedItem(
            name=item.name,
            confidence=item.confidence,
            status=(
                ItemStatus.ALREADY_IN_PANTRY
                if item.name.lower() in pantry_names_lower
                else ItemStatus.NEW
            ),
            category=item.category,
            quantity=item.quantity,
        )
        for item in items
    ]
    return PantrySuggestion(items=marked, unclear_photos=[])


# -------------------------------------------------------------------
# Discord output formatting
# -------------------------------------------------------------------

def format_suggestion(suggestion: PantrySuggestion) -> str:
    """Format a PantrySuggestion as a Discord-ready message.

    Items are grouped by (status, category) and displayed as a
    categorized list with confidence and status markers.

    Output format:
        🆕 New items:
        🥬 Produce
          ➕ Avocado [?]    ← uncertain new item
          ➕ Cherry Tomatoes
        ...

        ✅ Already in pantry:
        🧀 Dairy / Refrigerated
          ✅ Milk
          ✅ Butter [?]
        ...

    Args:
        suggestion: The result from `analyze_pantry_photos`.

    Returns:
        A string ready to post to Discord. Empty string if no items.
    """
    if not suggestion.items:
        return "_No items identified in the photos. Try retaking with better lighting._"

    # Separate new vs already-in-pantry
    new_items = [i for i in suggestion.items if i.status == ItemStatus.NEW]
    existing_items = [i for i in suggestion.items if i.status == ItemStatus.ALREADY_IN_PANTRY]

    lines: list[str] = []

    # Unclear photos warning
    if suggestion.unclear_photos:
        lines.append(
            "_⚠️ Some photos couldn't be read clearly — results below may be incomplete. "
            "Try retaking with better lighting._\n"
        )

    # New items section
    if new_items:
        lines.append("**🆕 New items**\n")
        lines.extend(_format_category_group(new_items))
        lines.append("")

    # Already-in-pantry items section
    if existing_items:
        lines.append("**✅ Already in pantry**\n")
        lines.extend(_format_category_group(existing_items))
        lines.append("")

    lines.append("_Reply with corrections (e.g. `change Avocado to Guacamole`, "
                 "`remove Tomatoes`) or `confirm` to update the pantry._")

    return "\n".join(lines)


def _format_category_group(items: list[SuggestedItem]) -> list[str]:
    """Format a list of items within one status section, grouped by category."""
    # Group by category
    by_category: dict[GroceryCategory, list[SuggestedItem]] = {}
    for item in items:
        by_category.setdefault(item.category, []).append(item)

    # Canonical category order
    CATEGORY_ORDER = [
        GroceryCategory.PRODUCE,
        GroceryCategory.DAIRY,
        GroceryCategory.MEAT_SEAFOOD,
        GroceryCategory.BAKERY,
        GroceryCategory.PANTRY,
        GroceryCategory.FROZEN,
        GroceryCategory.CONDIMENTS,
        GroceryCategory.SNACKS,
        GroceryCategory.BEVERAGES,
        GroceryCategory.OTHER,
    ]

    lines: list[str] = []
    for cat in CATEGORY_ORDER:
        cat_items = by_category.get(cat)
        if not cat_items:
            continue

        emoji = _CATEGORY_EMOJI.get(cat, "📦")
        lines.append(f"**{emoji} {cat.value}**")
        for item in sorted(cat_items, key=lambda i: i.name.lower()):
            confidence_marker = " [?]" if item.confidence == Confidence.LOW else ""
            if item.status == ItemStatus.NEW:
                status_icon = "➕"
            else:
                status_icon = "✅"
            quantity_str = f" ({item.quantity})" if item.quantity else ""
            lines.append(f"  {status_icon} {item.name}{quantity_str}{confidence_marker}")
        lines.append("")

    return lines


_CATEGORY_EMOJI: dict[GroceryCategory, str] = {
    GroceryCategory.DAIRY: "🧀",
    GroceryCategory.PRODUCE: "🥬",
    GroceryCategory.BAKERY: "🛒",
    GroceryCategory.PANTRY: "🍚",
    GroceryCategory.CONDIMENTS: "🥫",
    GroceryCategory.SNACKS: "🥜",
    GroceryCategory.BEVERAGES: "☕",
    GroceryCategory.MEAT_SEAFOOD: "🥩",
    GroceryCategory.FROZEN: "❄️",
    GroceryCategory.OTHER: "📦",
}
