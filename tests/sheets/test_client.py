"""Tests for the sheets client adapter."""
from datetime import date
from pathlib import Path
import tempfile

import pytest

from meal_plan import MealPlan, PlannedMeal
from sheets.client import SheetsClient, GroceryCategory, GroceryItem, GroceryList


class FakeSheetsService:
    """Fake Sheets API service for testing."""

    def __init__(self) -> None:
        self._tabs: dict[str, list[list[str]]] = {}
        self._cleared: set[str] = set()

    def spreadsheets(self):
        return _FakeSpreadsheets(self)


class _FakeSpreadsheets:
    def __init__(self, service: FakeSheetsService) -> None:
        self._service = service

    def values(self):
        return _FakeValues(self._service)


class _FakeValues:
    def __init__(self, service: FakeSheetsService) -> None:
        self._service = service

    def update(self, spreadsheetId, range, body, valueInputOption):
        rows = body["values"]
        tab = range.split("!")[0]
        self._service._tabs[tab] = [[c for c in r] for r in rows]
        return _FakeExecute()

    def get(self, spreadsheetId, range):
        tab = range.split("!")[0]
        rows = self._service._tabs.get(tab, [])
        return _FakeExecute({"values": rows})

    def clear(self, spreadsheetId, range):
        tab = range.split("!")[0]
        self._service._cleared.add(tab)
        return _FakeExecute()


class _FakeExecute:
    def __init__(self, data: dict | None = None) -> None:
        self._data = data or {}

    def execute(self, **kwargs):
        return self._data


class TestSheetsClientMealPlan:
    """SheetsClient read/write of meal plans."""

    def test_write_meal_plan_clears_and_writes(self) -> None:
        service = FakeSheetsService()
        client = SheetsClient(service, "test-sheet-id")

        plan = MealPlan(
            week_start=date(2026, 5, 4),
            days=[
                PlannedMeal(date=date(2026, 5, 4), recipe_name="Pasta", recipe_link="http://x.com"),
                PlannedMeal(date=date(2026, 5, 5), recipe_name="Tacos", recipe_link=None),
            ],
        )

        client.write_meal_plan(plan)

        tab = service._tabs["Meal Plan"]
        # Header row
        assert tab[0] == ["Date", "Meal", "Recipe Link", "Defrost", "Prep"]
        # Data rows
        assert tab[1] == ["2026-05-04", "Pasta", "http://x.com", "", ""]
        assert tab[2] == ["2026-05-05", "Tacos", "", "", ""]

    def test_write_meal_plan_with_empty_recipe_name(self) -> None:
        service = FakeSheetsService()
        client = SheetsClient(service, "test-sheet-id")

        plan = MealPlan(
            week_start=date(2026, 5, 4),
            days=[
                PlannedMeal(date=date(2026, 5, 4), recipe_name="", recipe_link=None),
            ],
        )

        client.write_meal_plan(plan)

        tab = service._tabs["Meal Plan"]
        assert tab[1] == ["2026-05-04", "", "", "", ""]

    def test_read_meal_plan_parses_rows(self) -> None:
        service = FakeSheetsService()
        # Pre-populate with data
        service._tabs["Meal Plan"] = [
            ["Date", "Meal", "Recipe Link", "Defrost", "Prep"],
            ["2026-05-04", "Pasta", "http://x.com", "", ""],
            ["2026-05-05", "Tacos", "", "", ""],
        ]

        client = SheetsClient(service, "test-sheet-id")
        plan = client.read_meal_plan(date(2026, 5, 4))

        assert plan.week_start == date(2026, 5, 4)
        assert len(plan.days) == 2
        assert plan.days[0].recipe_name == "Pasta"
        assert plan.days[0].recipe_link == "http://x.com"
        assert plan.days[1].recipe_name == "Tacos"
        assert plan.days[1].recipe_link is None

    def test_read_meal_plan_empty_tab_returns_empty_plan(self) -> None:
        service = FakeSheetsService()
        service._tabs["Meal Plan"] = []

        client = SheetsClient(service, "test-sheet-id")
        plan = client.read_meal_plan(date(2026, 5, 4))

        assert plan.week_start == date(2026, 5, 4)
        assert plan.days == []


class TestSheetsClientGrocery:
    """SheetsClient read/write of grocery lists."""

    def test_write_grocery_list(self) -> None:
        service = FakeSheetsService()
        client = SheetsClient(service, "test-sheet-id")

        grocery_list = GroceryList(
            week_start=date(2026, 5, 4),
            items=[
                GroceryItem(name="Pasta", quantity="500g", category=GroceryCategory.PANTRY, checked=False),
                GroceryItem(name="Chicken", quantity="1kg", category=GroceryCategory.MEAT_SEAFOOD, checked=True, source_recipe="Tacos"),
            ],
        )

        client.write_grocery_list(grocery_list)

        tab = service._tabs["Grocery"]
        assert tab[0] == ["Done", "Item", "Qty", "Source"]
        assert tab[1] == ["", "Pasta", "500g", ""]
        assert tab[2] == ["true", "Chicken", "1kg", "Tacos"]

    def test_read_checked_grocery_items(self) -> None:
        service = FakeSheetsService()
        service._tabs["Grocery"] = [
            ["Done", "Item", "Qty", "Source"],
            ["true", "Pasta", "500g", ""],
            ["", "Chicken", "1kg", ""],
            ["true", "Rice", "2kg", "Paella"],
        ]

        client = SheetsClient(service, "test-sheet-id")
        checked = client.read_checked_grocery_items()

        assert checked == ["Pasta", "Rice"]