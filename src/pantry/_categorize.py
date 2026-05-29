"""Category inference — determines GroceryCategory from an item name.

Single public function: infer_category().
Used by write_pantry() and doneshopping command.
"""
from __future__ import annotations

from shared.types import GroceryCategory


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


def infer_category(item_name: str) -> GroceryCategory:
    """Infer a GroceryCategory from an item name using keyword matching.

    Args:
        item_name: The name of the item to categorize.

    Returns:
        The inferred GroceryCategory, or GroceryCategory.OTHER if no match.
    """
    name_lower = item_name.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return category
    return GroceryCategory.OTHER
