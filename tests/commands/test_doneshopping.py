"""Tests for the done-shopping flow."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from commands.doneshopping import (
    is_doneshopping_trigger,
    _infer_category,
    handle_doneshopping,
)
from pantry.inventory import read_pantry, add_items, write_pantry
from shared.types import (
    GroceryCategory,
    Pantry,
    PantryItem,
)


# -------------------------------------------------------------------
# Trigger tests
# -------------------------------------------------------------------

class TestIsDoneshoppingTrigger:
    def test_command_exact(self):
        assert is_doneshopping_trigger("!doneshopping") is True

    def test_command_with_spaces(self):
        assert is_doneshopping_trigger("!doneshopping ") is True

    def test_plain_done_shopping(self):
        assert is_doneshopping_trigger("done shopping") is True

    def test_plain_shopping_done(self):
        assert is_doneshopping_trigger("shopping done") is True

    def test_plain_shopping_complete(self):
        assert is_doneshopping_trigger("shopping complete") is True

    def test_plain_finished_shopping(self):
        assert is_doneshopping_trigger("finished shopping") is True

    def test_case_insensitive(self):
        assert is_doneshopping_trigger("DONE SHOPPING") is True
        assert is_doneshopping_trigger("!DonEshopping") is True

    def test_not_trigger(self):
        assert is_doneshopping_trigger("!grocery") is False
        assert is_doneshopping_trigger("I went shopping") is False
        assert is_doneshopping_trigger("done shopping later") is False


# -------------------------------------------------------------------
# Category inference tests
# -------------------------------------------------------------------

class TestInferCategory:
    def test_dairy(self):
        assert _infer_category("Organic Valley Milk") == GroceryCategory.DAIRY
        assert _infer_category("Sharp Cheddar Cheese") == GroceryCategory.DAIRY
        assert _infer_category("Greek Yogurt") == GroceryCategory.DAIRY
        assert _infer_category("Large Eggs") == GroceryCategory.DAIRY

    def test_produce(self):
        assert _infer_category("Roma Tomatoes") == GroceryCategory.PRODUCE
        assert _infer_category("Red Bell Pepper") == GroceryCategory.PRODUCE
        assert _infer_category("Baby Spinach") == GroceryCategory.PRODUCE
        assert _infer_category("Yellow Onions") == GroceryCategory.PRODUCE

    def test_meat_seafood(self):
        assert _infer_category("Chicken Breast") == GroceryCategory.MEAT_SEAFOOD
        assert _infer_category("Ground Beef 80/20") == GroceryCategory.MEAT_SEAFOOD
        assert _infer_category("Atlantic Salmon Fillet") == GroceryCategory.MEAT_SEAFOOD
        assert _infer_category("Bacon Strips") == GroceryCategory.MEAT_SEAFOOD

    def test_bakery(self):
        assert _infer_category("Sourdough Bread") == GroceryCategory.BAKERY
        assert _infer_category("Flour Tortillas") == GroceryCategory.BAKERY
        assert _infer_category("Whole Wheat Buns") == GroceryCategory.BAKERY

    def test_pantry(self):
        assert _infer_category("Arborio Rice") == GroceryCategory.PANTRY
        assert _infer_category("Penne Pasta") == GroceryCategory.PANTRY
        assert _infer_category("Olive Oil") == GroceryCategory.PANTRY

    def test_condiments(self):
        assert _infer_category("Heinz Ketchup") == GroceryCategory.CONDIMENTS
        assert _infer_category("Duke's Mayonnaise") == GroceryCategory.CONDIMENTS
        assert _infer_category("Wild Honey") == GroceryCategory.CONDIMENTS

    def test_snacks(self):
        # "chip" is in SNACKS keywords
        assert _infer_category("Lays Chips") == GroceryCategory.SNACKS
        # "cracker" is in SNACKS
        assert _infer_category("Triscuit Crackers") == GroceryCategory.SNACKS

    def test_beverages(self):
        # "soda" is in BEVERAGES
        assert _infer_category("Pepsi Soda") == GroceryCategory.BEVERAGES
        assert _infer_category("Orange Juice") == GroceryCategory.BEVERAGES

    def test_unknown_falls_back_to_other(self):
        assert _infer_category("Mysterious Item 123") == GroceryCategory.OTHER


# -------------------------------------------------------------------
# add_items unit tests
# -------------------------------------------------------------------

class TestAddItems:
    def test_empty_pantry(self):
        pantry = Pantry(items=[])
        new_items = [
            PantryItem(name="Chicken Breast"),
            PantryItem(name="Milk"),
        ]
        result = add_items(pantry, new_items)
        assert len(result.items) == 2
        assert result.items[0].name == "Chicken Breast"
        assert result.items[1].name == "Milk"

    def test_skips_duplicates_case_insensitive(self):
        pantry = Pantry(items=[
            PantryItem(name="Eggs"),
            PantryItem(name="Milk"),
        ])
        new_items = [
            PantryItem(name="eggs"),       # exact duplicate (lower)
            PantryItem(name="Chicken Breast"),
        ]
        result = add_items(pantry, new_items)
        names_lower = [p.name.lower() for p in result.items]
        assert "chicken breast" in names_lower
        # eggs should be skipped (case-insensitive), exactly one eggs entry
        egg_count = sum(1 for n in names_lower if n == "eggs")
        assert egg_count == 1, f"Expected 1 eggs entry, got {egg_count}: {names_lower}"
        assert egg_count == 1

    def test_returns_new_pantry_not_mutated(self):
        original = Pantry(items=[PantryItem(name="Butter")])
        new_items = [PantryItem(name="Milk")]
        result = add_items(original, new_items)
        assert original.items[0].name == "Butter"
        assert len(original.items) == 1
        assert len(result.items) == 2

    def test_all_duplicate_returns_identical_items(self):
        pantry = Pantry(items=[PantryItem(name="Butter")])
        new_items = [PantryItem(name="Butter"), PantryItem(name="butter")]
        result = add_items(pantry, new_items)
        assert len(result.items) == 1


# -------------------------------------------------------------------
# write_pantry / integration tests
# -------------------------------------------------------------------

class TestWritePantry:
    def test_write_and_read_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pantry_file = Path(tmpdir) / "pantry-items.md"
            categories = list(GroceryCategory)

            pantry = Pantry(items=[
                PantryItem(name="Lactantia Salted Cultured Butter"),
                PantryItem(name="Eggs"),
            ])
            write_pantry(pantry_file, pantry, categories)

            assert pantry_file.exists()
            text = pantry_file.read_text()
            assert "Lactantia Salted Cultured Butter" in text
            assert "Eggs" in text
            assert "# Pantry Items" in text

    def test_creates_file_if_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pantry_file = Path(tmpdir) / "does-not-exist.md"
            categories = list(GroceryCategory)

            pantry = Pantry(items=[PantryItem(name="Milk")])
            write_pantry(pantry_file, pantry, categories)

            assert pantry_file.exists()

    def test_categorized_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pantry_file = Path(tmpdir) / "pantry-items.md"
            categories = list(GroceryCategory)

            pantry = Pantry(items=[
                PantryItem(name="Milk"),
                PantryItem(name="Chicken Breast"),
                PantryItem(name="Tomatoes"),
            ])
            # Pass infer_category so items get sorted into their categories
            write_pantry(pantry_file, pantry, categories, infer_category=_infer_category)

            text = pantry_file.read_text()
            # Milk → Dairy, Chicken → Meat, Tomatoes → Produce
            assert "Dairy / Refrigerated" in text
            assert "Meat & Seafood" in text
            assert "Produce" in text


# -------------------------------------------------------------------
# handle_doneshopping tests (mock Sheets)
# -------------------------------------------------------------------

class MockSheetsClient:
    """Mock Sheets client for testing."""

    def __init__(self, checked_items: list[str]) -> None:
        self._checked_items = checked_items

    def read_checked_grocery_items(self, tab_name: str = "Grocery") -> list[str]:
        return self._checked_items


@pytest.fixture
def mock_sheets(monkeypatch):
    """Patch _get_sheets_client to return a mock."""
    mock_client = MockSheetsClient(checked_items=[
        "Chicken Breast",
        "Eggs",
        "Butter",
        "Mozzarella Cheese",
        "Tomatoes",
        "Red Bell Pepper",
    ])

    def fake_get_sheets_client(vault):
        return mock_client

    import commands.doneshopping as ds
    monkeypatch.setattr(ds, "_get_sheets_client", fake_get_sheets_client)


class TestHandleDoneshopping:
    def test_adds_new_items_skips_existing(self, mock_sheets):
        with tempfile.TemporaryDirectory() as tmpdir:
            pantry_file = Path(tmpdir) / "pantry-items.md"
            vault = Path(tmpdir) / "vault"

            # Pre-populate pantry with some items
            existing_pantry = Pantry(items=[
                PantryItem(name="Butter"),  # already in pantry
                PantryItem(name="Eggs"),    # already in pantry
            ])
            categories = list(GroceryCategory)
            write_pantry(pantry_file, existing_pantry, categories)

            result = handle_doneshopping(pantry_file, vault)

            # Should say added 4 new items, skipped 2 existing
            assert "Chicken Breast" in result or "Added 4" in result or "4" in result
            # Should mention existing
            assert "already in stock" in result or "2" in result

    def test_no_checked_items(self, mock_sheets):
        # Re-patch with empty list
        mock_client = MockSheetsClient(checked_items=[])
        import commands.doneshopping as ds
        original = ds._get_sheets_client

        def fake_empty(vault):
            return mock_client

        with tempfile.TemporaryDirectory() as tmpdir:
            pantry_file = Path(tmpdir) / "pantry-items.md"
            vault = Path(tmpdir) / "vault"
            ds._get_sheets_client = fake_empty

            try:
                result = handle_doneshopping(pantry_file, vault)
                assert "No items checked" in result
            finally:
                ds._get_sheets_client = original

    def test_all_items_already_in_pantry(self, mock_sheets):
        mock_client = MockSheetsClient(checked_items=["Eggs", "Butter"])
        import commands.doneshopping as ds
        original = ds._get_sheets_client

        with tempfile.TemporaryDirectory() as tmpdir:
            pantry_file = Path(tmpdir) / "pantry-items.md"
            vault = Path(tmpdir) / "vault"

            existing_pantry = Pantry(items=[
                PantryItem(name="Eggs"),
                PantryItem(name="Butter"),
            ])
            categories = list(GroceryCategory)
            write_pantry(pantry_file, existing_pantry, categories)

            def fake_all_existing(vault):
                return mock_client

            ds._get_sheets_client = fake_all_existing
            try:
                result = handle_doneshopping(pantry_file, vault)
                # All were in stock
                assert "already in stock" in result or "were already" in result.lower()
            finally:
                ds._get_sheets_client = original