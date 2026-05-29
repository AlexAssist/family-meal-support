"""Tests for the !grocery command handlers."""
from __future__ import annotations

import json
import pytest
from datetime import date, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from shared.types import GroceryCategory
from commands.grocery import (
    handle_grocery_generate,
    handle_grocery_status,
    _load_status,
    _save_status,
    _get_week_monday,
)


# -------------------------------------------------------------------
# Helpers for status tests
# -------------------------------------------------------------------

def _status_roundtrip(tmp_path: Path, data: dict) -> dict:
    """Write data as status, read it back via _load_status."""
    status_file = tmp_path / "grocery-status.json"
    status_file.write_text(json.dumps(data))
    with patch("commands.grocery._get_status_path", return_value=status_file):
        return _load_status()


# -------------------------------------------------------------------
# Test: status roundtrip
# -------------------------------------------------------------------

class TestStatusPersistence:
    """_load_status and _save_status work correctly."""

    def test_save_and_load_roundtrip(self, tmp_path):
        data = {
            "generated_at": "2026-06-01T18:00:00+00:00",
            "item_count": 23,
            "categories": 7,
        }
        loaded = _status_roundtrip(tmp_path, data)
        assert loaded["item_count"] == 23
        assert loaded["categories"] == 7

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        status_file = tmp_path / "nonexistent.json"
        with patch("commands.grocery._get_status_path", return_value=status_file):
            result = _load_status()
        assert result == {}


# -------------------------------------------------------------------
# Test: !grocery status
# -------------------------------------------------------------------

class TestGroceryStatus:
    """handle_grocery_status returns a quick count without generating."""

    def test_no_status_file_returns_no_list_message(self, tmp_path):
        """When no status file exists, the message says 'no grocery list generated yet'."""
        status_file = tmp_path / "nonexistent.json"
        with patch("commands.grocery._get_status_path", return_value=status_file):
            msg = handle_grocery_status(tmp_path)
        assert "no grocery list generated" in msg.lower()

    def test_status_returns_count_and_time(self, tmp_path):
        """Status with data returns item count, category count, and formatted time."""
        status_file = tmp_path / "grocery-status.json"
        status_data = {
            "generated_at": "2026-06-01T18:00:00+00:00",
            "item_count": 23,
            "categories": 7,
            "week_start": "2026-06-01",
        }
        status_file.write_text(json.dumps(status_data))

        with patch("commands.grocery._get_status_path", return_value=status_file):
            msg = handle_grocery_status(tmp_path)

        assert "23" in msg
        assert "7" in msg
        assert "never" not in msg.lower()


# -------------------------------------------------------------------
# Test: !grocery generate
# -------------------------------------------------------------------

class TestGroceryGenerate:
    """handle_grocery_generate builds and writes the grocery list."""

    def test_empty_plan_returns_no_meals_message(self, tmp_path):
        """When no meal plan exists, a graceful message is returned."""
        vault = tmp_path / "vault"
        vault.mkdir()
        plans_dir = vault / "reference" / "meal-planning" / "plans"
        plans_dir.mkdir(parents=True)
        pantry_file = vault / "pantry.md"

        # No plan file written — plan_file won't exist
        msg = handle_grocery_generate(vault, plans_dir, pantry_file)
        assert "no meals planned" in msg.lower()

    def test_generates_and_writes_to_sheets(self, tmp_path):
        """With a meal plan and recipe, write_grocery_list is called on the sheets client."""
        vault = tmp_path / "vault"
        vault.mkdir()
        plans_dir = vault / "reference" / "meal-planning" / "plans"
        plans_dir.mkdir(parents=True)
        pantry_file = vault / "pantry.md"

        # Write a minimal plan file
        monday = _get_week_monday(date.today())
        plan_file = plans_dir / f"{monday.strftime('%Y-%m-%d')}.md"
        plan_file.write_text(
            f"# Week of {monday.strftime('%B %-d, %Y')}\n"
            f"## {monday.strftime('%A %B %-d')}\n"
            f"**Supper:** Chicken Tacos\n"
        )

        # Write pantry (empty)
        pantry_file.write_text("# Pantry Items\n")

        # Build a mock grocery list with 2 items
        mock_grocery_list = MagicMock()
        mock_grocery_list.items = [
            MagicMock(name="chicken breast", category=GroceryCategory.MEAT_SEAFOOD, source_recipe="Chicken Tacos"),
            MagicMock(name="taco shells", category=GroceryCategory.PANTRY, source_recipe="Chicken Tacos"),
        ]

        # Mock the sheets client
        mock_client = MagicMock()

        with patch("sheets.auth.SheetsAuth.build", return_value=mock_client), \
             patch("commands.grocery.generate_grocery_list", return_value=mock_grocery_list):
            msg = handle_grocery_generate(vault, plans_dir, pantry_file)

        mock_client.write_grocery_list.assert_called_once()
        # Message should be positive
        assert "items" in msg.lower()


# -------------------------------------------------------------------
# Test: week Monday helper
# -------------------------------------------------------------------

class TestWeekMonday:
    """_get_week_monday returns the Monday of the week for a given date."""

    def test_monday_returns_same_monday(self):
        monday = date(2026, 6, 1)
        assert _get_week_monday(monday) == date(2026, 6, 1)

    def test_wednesday_returns_previous_monday(self):
        wednesday = date(2026, 6, 3)
        assert _get_week_monday(wednesday) == date(2026, 6, 1)

    def test_sunday_returns_previous_monday(self):
        sunday = date(2026, 6, 7)
        assert _get_week_monday(sunday) == date(2026, 6, 1)