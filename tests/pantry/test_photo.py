"""Tests for the pantry photo analysis pipeline."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ is on path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from pantry._photo import (
    _infer_category,
    _merge_results,
    _compare_with_pantry,
    analyze_pantry_photos,
    format_suggestion,
)
from shared.types import (
    Confidence,
    GroceryCategory,
    ItemStatus,
    Pantry,
    PantryItem,
    PantrySuggestion,
    SuggestedItem,
)


# -------------------------------------------------------------------
# _infer_category tests
# -------------------------------------------------------------------

class TestInferCategory:
    def test_dairy(self):
        assert _infer_category("Lactantia Salted Cultured Butter") == GroceryCategory.DAIRY
        assert _infer_category("Organic Valley Milk") == GroceryCategory.DAIRY
        assert _infer_category("Sharp Cheddar Cheese") == GroceryCategory.DAIRY
        assert _infer_category("Greek Yogurt") == GroceryCategory.DAIRY
        assert _infer_category("Free Range Large Eggs") == GroceryCategory.DAIRY

    def test_produce(self):
        assert _infer_category("Roma Tomatoes") == GroceryCategory.PRODUCE
        assert _infer_category("Baby Spinach") == GroceryCategory.PRODUCE
        assert _infer_category("Red Bell Pepper") == GroceryCategory.PRODUCE
        assert _infer_category("Avocado") == GroceryCategory.PRODUCE
        assert _infer_category("Cherry Tomatoes") == GroceryCategory.PRODUCE

    def test_meat_seafood(self):
        assert _infer_category("Chicken Breast") == GroceryCategory.MEAT_SEAFOOD
        assert _infer_category("Atlantic Salmon Fillet") == GroceryCategory.MEAT_SEAFOOD
        assert _infer_category("Bacon Strips") == GroceryCategory.MEAT_SEAFOOD
        assert _infer_category("Ground Beef 80/20") == GroceryCategory.MEAT_SEAFOOD

    def test_bakery(self):
        assert _infer_category("Sourdough Bread") == GroceryCategory.BAKERY
        assert _infer_category("Whole Wheat Buns") == GroceryCategory.BAKERY
        assert _infer_category("Flour Tortillas") == GroceryCategory.BAKERY

    def test_pantry(self):
        assert _infer_category("Arborio Rice") == GroceryCategory.PANTRY
        assert _infer_category("Penne Pasta") == GroceryCategory.PANTRY
        assert _infer_category("Olive Oil") == GroceryCategory.PANTRY
        # "Crackers" is classified as SNACKS (cracker keyword in SNACKS wins over PANTRY)
        assert _infer_category("Crackers") == GroceryCategory.SNACKS

    def test_condiments(self):
        assert _infer_category("Heinz Ketchup") == GroceryCategory.CONDIMENTS
        assert _infer_category("Duke's Mayonnaise") == GroceryCategory.CONDIMENTS
        assert _infer_category("Wild Honey") == GroceryCategory.CONDIMENTS
        assert _infer_category("Peanut Butter") == GroceryCategory.CONDIMENTS

    def test_snacks(self):
        assert _infer_category("Lays Chips") == GroceryCategory.SNACKS
        assert _infer_category("Triscuit Crackers") == GroceryCategory.SNACKS
        assert _infer_category("Pretzels") == GroceryCategory.SNACKS

    def test_beverages(self):
        assert _infer_category("Orange Juice") == GroceryCategory.BEVERAGES
        assert _infer_category("Pepsi Soda") == GroceryCategory.BEVERAGES

    def test_frozen(self):
        assert _infer_category("Frozen Pizza") == GroceryCategory.FROZEN
        assert _infer_category("Ice Cream") == GroceryCategory.FROZEN

    def test_unknown_defaults_to_other(self):
        assert _infer_category("Mysterious Item 123 XYZ") == GroceryCategory.OTHER
        assert _infer_category("Something Not Listed") == GroceryCategory.OTHER


# -------------------------------------------------------------------
# _merge_results tests
# -------------------------------------------------------------------

class TestMergeResults:
    def _raw(self, name: str, confidence: float, quantity: str | None = None) -> dict:
        return {"name": name, "confidence": confidence, "quantity": quantity}

    def test_deduplicates_same_item_different_confidence(self):
        """Same item in two photos → keep the higher-confidence result."""
        raw = [
            self._raw("Milk", 0.95),
            self._raw("Milk", 0.85),
        ]
        result = _merge_results(raw)
        assert len(result) == 1
        assert result[0].name == "Milk"
        assert result[0].confidence == Confidence.HIGH  # 0.95 → HIGH

    def test_deduplicates_case_insensitive(self):
        """'Milk' and 'MILK' treated as same item."""
        raw = [
            self._raw("Milk", 0.70),
            self._raw("MILK", 0.90),
        ]
        result = _merge_results(raw)
        assert len(result) == 1
        assert result[0].name == "MILK"  # second one wins (highest confidence)
        assert result[0].confidence == Confidence.HIGH

    def test_different_items_kept_separate(self):
        raw = [
            self._raw("Milk", 0.95),
            self._raw("Eggs", 0.90),
            self._raw("Bread", 0.85),
        ]
        result = _merge_results(raw)
        assert len(result) == 3
        names = {r.name for r in result}
        assert names == {"Milk", "Eggs", "Bread"}

    def test_empty_list_returns_empty(self):
        assert _merge_results([]) == []

    def test_skips_empty_names(self):
        raw = [self._raw("Milk", 0.95), self._raw("", 0.50)]
        result = _merge_results(raw)
        assert len(result) == 1
        assert result[0].name == "Milk"

    def test_sorts_by_confidence_desc_then_alpha(self):
        raw = [
            self._raw("Zucchini", 0.75),   # MEDIUM
            self._raw("Apple", 0.95),       # HIGH
            self._raw("Yogurt", 0.88),     # HIGH
        ]
        result = _merge_results(raw)
        # HIGH items first, alphabetical within; then MEDIUM
        assert result[0].name in ("Apple", "Yogurt")  # both HIGH
        assert result[2].name == "Zucchini"  # MEDIUM

    def test_preserves_quantity_from_best_entry(self):
        raw = [
            self._raw("Milk", 0.60, quantity="1 carton"),
            self._raw("Milk", 0.90, quantity=None),
        ]
        result = _merge_results(raw)
        assert len(result) == 1
        # Best confidence is 0.90 (HIGH), quantity is None from that entry
        assert result[0].quantity is None


# -------------------------------------------------------------------
# _compare_with_pantry tests
# -------------------------------------------------------------------

class TestCompareWithPantry:
    def _si(
        self,
        name: str,
        confidence: float = 0.90,
        status: ItemStatus = ItemStatus.NEW,
    ) -> SuggestedItem:
        return SuggestedItem(
            name=name,
            confidence=Confidence.from_score(confidence),
            status=status,
            category=GroceryCategory.OTHER,
            quantity=None,
        )

    def _pantry(self, *names: str) -> Pantry:
        return Pantry(items=[PantryItem(name=n) for n in names])

    def test_new_item_marked_new(self):
        items = [self._si("Chicken Breast")]
        pantry = self._pantry("Milk", "Eggs")
        result = _compare_with_pantry(items, pantry)
        assert len(result.items) == 1
        assert result.items[0].status == ItemStatus.NEW

    def test_pantry_item_marked_already_in_pantry(self):
        items = [self._si("Milk")]
        pantry = self._pantry("Milk", "Eggs")
        result = _compare_with_pantry(items, pantry)
        assert result.items[0].status == ItemStatus.ALREADY_IN_PANTRY

    def test_mixed_items_correctly_classified(self):
        items = [
            self._si("Milk"),
            self._si("Chicken Breast"),
            self._si("Eggs"),
        ]
        pantry = self._pantry("Eggs", "Butter")
        result = _compare_with_pantry(items, pantry)
        by_name = {i.name: i.status for i in result.items}
        assert by_name["Milk"] == ItemStatus.NEW
        assert by_name["Chicken Breast"] == ItemStatus.NEW
        assert by_name["Eggs"] == ItemStatus.ALREADY_IN_PANTRY

    def test_case_insensitive_matching(self):
        items = [self._si("MILK"), self._si("milk"), self._si("Milk")]
        pantry = self._pantry("milk")
        result = _compare_with_pantry(items, pantry)
        # All three should be marked ALREADY_IN_PANTRY (case-insensitive)
        assert all(i.status == ItemStatus.ALREADY_IN_PANTRY for i in result.items)

    def test_empty_pantry_all_new(self):
        items = [self._si("Milk"), self._si("Eggs")]
        result = _compare_with_pantry(items, Pantry(items=[]))
        assert all(i.status == ItemStatus.NEW for i in result.items)


# -------------------------------------------------------------------
# analyze_pantry_photos — integration tests
# -------------------------------------------------------------------

class TestAnalyzePantryPhotos:
    def _photo(self, items: list[dict], unclear: bool = False) -> dict:
        return {"items": items, "unclear": unclear, "photo_url": "http://example.com/photo.jpg"}

    def _raw(self, name: str, confidence: float, quantity: str | None = None) -> dict:
        return {"name": name, "confidence": confidence, "quantity": quantity}

    def _pantry(self, *names: str) -> Pantry:
        return Pantry(items=[PantryItem(name=n) for n in names])

    def test_empty_photo_list_returns_empty_suggestion(self):
        result = analyze_pantry_photos([], self._pantry("Milk"))
        assert result.items == []
        assert result.unclear_photos == []

    def test_single_photo_results(self):
        photos = [
            self._photo([
                self._raw("Milk", 0.95),
                self._raw("Eggs", 0.90),
            ])
        ]
        result = analyze_pantry_photos(photos, self._pantry())
        assert len(result.items) == 2
        names = {i.name for i in result.items}
        assert names == {"Milk", "Eggs"}
        assert all(i.status == ItemStatus.NEW for i in result.items)

    def test_multiple_photos_merge_dedupe(self):
        photos = [
            self._photo([self._raw("Milk", 0.70), self._raw("Eggs", 0.90)]),
            self._photo([self._raw("Milk", 0.95), self._raw("Bread", 0.85)]),
        ]
        result = analyze_pantry_photos(photos, self._pantry())
        # Milk from second photo (0.95) wins; Eggs and Bread are new
        milk_item = next(i for i in result.items if i.name == "Milk")
        assert milk_item.confidence == Confidence.HIGH
        assert len(result.items) == 3

    def test_unclear_photo_returns_unclear_photos(self):
        photos = [
            self._photo([], unclear=True),
            self._photo([self._raw("Milk", 0.95)]),
        ]
        result = analyze_pantry_photos(photos, self._pantry())
        assert len(result.unclear_photos) == 1
        assert len(result.items) == 1
        assert result.items[0].name == "Milk"

    def test_confidence_threshold_sets_low_marker(self):
        """Items below 0.60 confidence should be LOW confidence."""
        photos = [
            self._photo([
                self._raw("Mystery Item", 0.30),   # LOW
                self._raw("Clear Milk", 0.95),      # HIGH
            ])
        ]
        result = analyze_pantry_photos(photos, self._pantry())
        by_name = {i.name: i.confidence for i in result.items}
        assert by_name["Mystery Item"] == Confidence.LOW
        assert by_name["Clear Milk"] == Confidence.HIGH

    def test_items_already_in_pantry_marked_correctly(self):
        photos = [
            self._photo([
                self._raw("Milk", 0.95),
                self._raw("New Cheese", 0.90),
            ])
        ]
        result = analyze_pantry_photos(photos, self._pantry("Milk"))
        by_name = {i.name: i.status for i in result.items}
        assert by_name["Milk"] == ItemStatus.ALREADY_IN_PANTRY
        assert by_name["New Cheese"] == ItemStatus.NEW

    def test_infers_categories_for_new_items(self):
        photos = [
            self._photo([
                self._raw("Milk", 0.95),
                self._raw("Chicken Breast", 0.90),
                self._raw("Tomatoes", 0.88),
            ])
        ]
        result = analyze_pantry_photos(photos, self._pantry())
        by_name = {i.name: i.category for i in result.items}
        assert by_name["Milk"] == GroceryCategory.DAIRY
        assert by_name["Chicken Breast"] == GroceryCategory.MEAT_SEAFOOD
        assert by_name["Tomatoes"] == GroceryCategory.PRODUCE

    def test_already_in_pantry_items_get_other_category(self):
        """Already-in-pantry items have their category set to OTHER."""
        photos = [
            self._photo([self._raw("Milk", 0.95)])
        ]
        result = analyze_pantry_photos(photos, self._pantry("Milk"))
        # Milk is ALREADY_IN_PANTRY → category is OTHER (not inferred)
        milk = result.items[0]
        assert milk.category == GroceryCategory.OTHER


# -------------------------------------------------------------------
# format_suggestion tests
# -------------------------------------------------------------------

class TestFormatSuggestion:
    def _si(
        self,
        name: str,
        confidence: Confidence = Confidence.HIGH,
        status: ItemStatus = ItemStatus.NEW,
        category: GroceryCategory = GroceryCategory.OTHER,
    ) -> SuggestedItem:
        return SuggestedItem(name=name, confidence=confidence, status=status, category=category, quantity=None)

    def test_empty_suggestion_returns_try_again_message(self):
        result = format_suggestion(PantrySuggestion(items=[], unclear_photos=[]))
        assert "Try retaking" in result  # capitalized as formatted

    def test_new_items_shown_with_plus_icon(self):
        suggestion = PantrySuggestion(items=[
            self._si("Avocado", status=ItemStatus.NEW),
        ])
        result = format_suggestion(suggestion)
        assert "➕ Avocado" in result

    def test_already_in_pantry_shown_with_check_icon(self):
        suggestion = PantrySuggestion(items=[
            self._si("Milk", status=ItemStatus.ALREADY_IN_PANTRY),
        ])
        result = format_suggestion(suggestion)
        assert "✅ Milk" in result

    def test_low_confidence_item_has_question_marker(self):
        suggestion = PantrySuggestion(items=[
            self._si("Avocado [?]", confidence=Confidence.LOW, status=ItemStatus.NEW),
        ])
        result = format_suggestion(suggestion)
        assert "[?]" in result

    def test_items_grouped_by_status(self):
        suggestion = PantrySuggestion(items=[
            self._si("Avocado", status=ItemStatus.NEW, category=GroceryCategory.PRODUCE),
            self._si("Milk", status=ItemStatus.ALREADY_IN_PANTRY),
        ])
        result = format_suggestion(suggestion)
        assert "🆕 New items" in result
        assert "✅ Already in pantry" in result

    def test_unclear_photos_warning_included(self):
        suggestion = PantrySuggestion(
            items=[self._si("Milk", status=ItemStatus.NEW)],
            unclear_photos=["http://example.com/blur.jpg"],
        )
        result = format_suggestion(suggestion)
        assert "⚠️" in result

    def test_confirm_reminder_included(self):
        suggestion = PantrySuggestion(items=[
            self._si("Milk", status=ItemStatus.NEW),
        ])
        result = format_suggestion(suggestion)
        assert "confirm" in result.lower()

    def test_quantity_shown_when_present(self):
        suggestion = PantrySuggestion(items=[
            SuggestedItem(
                name="Milk",
                confidence=Confidence.HIGH,
                status=ItemStatus.NEW,
                category=GroceryCategory.DAIRY,
                quantity="2 cartons",
            )
        ])
        result = format_suggestion(suggestion)
        assert "Milk" in result
        assert "2 cartons" in result
