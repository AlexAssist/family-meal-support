"""Tests for the pantry_review command handler."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure src/ is on path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from commands.pantry_review import (
    accumulate_photo,
    clear_pending,
    format_suggestion,
    get_awaiting_suggestion,
    get_pending_photos,
    handle_correction,
    is_confirm,
    is_review_trigger,
    parse_correction,
    run_analysis,
    set_awaiting_confirm,
    _apply_change,
    _apply_remove,
    _confirm,
)
from shared.types import (
    Confidence,
    GroceryCategory,
    ItemStatus,
    PantrySuggestion,
    SuggestedItem,
    PantryItem,
    Pantry,
)
from pantry.inventory import read_pantry, write_pantry


# -------------------------------------------------------------------
# Trigger detection tests
# -------------------------------------------------------------------

class TestIsReviewTrigger:
    def test_done(self):
        assert is_review_trigger("done") is True
        assert is_review_trigger("Done") is True
        assert is_review_trigger("DONE") is True

    def test_review_pantry(self):
        assert is_review_trigger("review pantry") is True
        assert is_review_trigger("Review Pantry") is True

    def test_analyze_pantry(self):
        assert is_review_trigger("analyze pantry") is True

    def test_check_pantry(self):
        assert is_review_trigger("check pantry") is True

    def test_not_trigger(self):
        assert is_review_trigger("I'm done cooking") is False
        assert is_review_trigger("!grocery") is False
        assert is_review_trigger("done shopping") is False


class TestIsConfirm:
    def test_confirm(self):
        assert is_confirm("confirm") is True
        assert is_confirm("CONFIRM") is True

    def test_looks_good(self):
        assert is_confirm("looks good") is True
        assert is_confirm("Looks Good") is True

    def test_thats_right(self):
        assert is_confirm("that's right") is True
        assert is_confirm("thats right") is True

    def test_yep(self):
        assert is_confirm("yep") is True
        assert is_confirm("yep!") is True
        assert is_confirm("yeah") is False  # not in our patterns

    def test_not_confirm(self):
        assert is_confirm("!grocery") is False
        assert is_confirm("done shopping") is False


class TestParseCorrection:
    def test_change_pattern(self):
        result = parse_correction("change Avocado to Guacamole")
        assert result == ("change", "Avocado", "Guacamole")

    def test_change_case_insensitive(self):
        result = parse_correction("CHANGE Avocado TO Guacamole")
        assert result == ("change", "Avocado", "Guacamole")

    def test_change_with_spaces_in_names(self):
        result = parse_correction("change Red Bell Pepper to Green Pepper")
        assert result == ("change", "Red Bell Pepper", "Green Pepper")

    def test_remove_pattern(self):
        result = parse_correction("remove Avocado")
        assert result == ("remove", "Avocado")

    def test_remove_case_insensitive(self):
        result = parse_correction("REMOVE Tomatoes")
        assert result == ("remove", "Tomatoes")

    def test_not_correction(self):
        assert parse_correction("confirm") is None
        assert parse_correction("!grocery") is None
        assert parse_correction("looks good") is None


# -------------------------------------------------------------------
# State persistence tests (using temp file)
# -------------------------------------------------------------------

class TestStatePersistence:
    def test_accumulate_photo(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        accumulate_photo("user123", "http://example.com/photo1.jpg")
        accumulate_photo("user123", "http://example.com/photo2.jpg")
        assert get_pending_photos("user123") == [
            "http://example.com/photo1.jpg",
            "http://example.com/photo2.jpg",
        ]

    def test_get_pending_photos_empty_for_unknown_user(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        assert get_pending_photos("unknown_user") == []

    def test_clear_pending(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        accumulate_photo("user123", "http://example.com/photo1.jpg")
        clear_pending("user123")
        assert get_pending_photos("user123") == []


# -------------------------------------------------------------------
# Suggestion persistence tests
# -------------------------------------------------------------------

class TestSuggestionPersistence:
    def test_set_and_get_awaiting_suggestion(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        suggestion = PantrySuggestion(items=[
            SuggestedItem(
                name="Milk",
                confidence=Confidence.HIGH,
                status=ItemStatus.NEW,
                category=GroceryCategory.DAIRY,
                quantity=None,
            )
        ], unclear_photos=[])
        set_awaiting_confirm("user123", suggestion)
        retrieved = get_awaiting_suggestion("user123")
        assert retrieved is not None
        assert len(retrieved.items) == 1
        assert retrieved.items[0].name == "Milk"
        assert retrieved.items[0].status == ItemStatus.NEW

    def test_get_awaiting_suggestion_none_when_not_set(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        assert get_awaiting_suggestion("unknown") is None


# -------------------------------------------------------------------
# run_analysis tests
# -------------------------------------------------------------------

class TestRunAnalysis:
    def _vault_pantry_file(self, tmp_path):
        """Build full vault path and return (pantry_file, cleanup_func)."""
        vault_root = tmp_path / "Documents" / "Obsidian"
        pantry_path = vault_root / "reference" / "grocery-lists"
        pantry_file = pantry_path / "pantry-items.md"
        pantry_path.mkdir(parents=True, exist_ok=True)
        return pantry_file

    def test_no_photos_returns_error_message(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        pantry_file = self._vault_pantry_file(tmp_path)
        pantry_file.write_text("# Pantry Items\n")

        msg, success = run_analysis(
            "user123",
            pantry_file,
            call_image_tool=_fake_image_tool([]),
        )
        assert success is False
        assert "No photos" in msg

    def test_analyzes_and_returns_suggestion(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        pantry_file = self._vault_pantry_file(tmp_path)
        pantry_file.write_text("# Pantry Items\n")

        accumulate_photo("user123", "http://example.com/milk.jpg")

        def fake_tool(url):
            return {
                "items": [{"name": "Milk", "confidence": 0.95, "quantity": "1 carton"}],
                "unclear": False,
                "photo_url": url,
            }

        msg, success = run_analysis("user123", pantry_file, call_image_tool=fake_tool)
        assert success is True
        assert "Milk" in msg
        assert "➕ Milk" in msg  # new item

    def test_failed_image_tool_treated_as_unclear(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        pantry_file = self._vault_pantry_file(tmp_path)
        pantry_file.write_text("# Pantry Items\n")
        accumulate_photo("user123", "http://example.com/blur.jpg")

        def failing_tool(url):
            raise RuntimeError("image tool failed")

        msg, success = run_analysis("user123", pantry_file, call_image_tool=failing_tool)
        assert success is False
        assert "try retaking" in msg

    def test_items_in_pantry_marked_already_in(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        pantry_file = self._vault_pantry_file(tmp_path)
        categories = list(GroceryCategory)
        write_pantry(
            pantry_file,
            Pantry(items=[PantryItem(name="Milk")]),
            categories,
        )
        accumulate_photo("user123", "http://example.com/milk.jpg")

        def fake_tool(url):
            return {
                "items": [{"name": "Milk", "confidence": 0.95, "quantity": None}],
                "unclear": False,
                "photo_url": url,
            }

        msg, success = run_analysis("user123", pantry_file, call_image_tool=fake_tool)
        assert "✅ Milk" in msg  # already in pantry


# -------------------------------------------------------------------
# Correction tests
# -------------------------------------------------------------------

class TestHandleCorrection:
    def _vault_pantry_file(self, tmp_path):
        vault_root = tmp_path / "Documents" / "Obsidian"
        pantry_path = vault_root / "reference" / "grocery-lists"
        pantry_file = pantry_path / "pantry-items.md"
        pantry_path.mkdir(parents=True, exist_ok=True)
        return pantry_file

    def test_non_correction_returns_none(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        suggestion = PantrySuggestion(items=[
            SuggestedItem(
                name="Avocado",
                confidence=Confidence.HIGH,
                status=ItemStatus.NEW,
                category=GroceryCategory.PRODUCE,
                quantity=None,
            )
        ], unclear_photos=[])
        set_awaiting_confirm("user123", suggestion)

        msg, result = handle_correction("user123", "!grocery")
        assert result is None  # not a correction

    def test_confirm_returns_confirmed_true(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        pantry_file = self._vault_pantry_file(tmp_path)
        pantry_file.write_text("# Pantry Items\n")
        suggestion = PantrySuggestion(items=[
            SuggestedItem(
                name="Milk",
                confidence=Confidence.HIGH,
                status=ItemStatus.NEW,
                category=GroceryCategory.DAIRY,
                quantity=None,
            )
        ], unclear_photos=[])
        set_awaiting_confirm("user123", suggestion)

        # Patch Path.home so _confirm writes to tmp_path vault structure
        monkeypatch.setattr(
            "commands.pantry_review.Path.home",
            lambda: tmp_path,
        )

        msg, confirmed = handle_correction("user123", "confirm")
        assert confirmed is True

    def test_confirm_not_in_confirm_state_returns_none(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        msg, result = handle_correction("unknown_user", "confirm")
        assert result is None


class TestApplyChange:
    def test_change_item_name(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        suggestion = PantrySuggestion(items=[
            SuggestedItem(
                name="Avocado",
                confidence=Confidence.HIGH,
                status=ItemStatus.NEW,
                category=GroceryCategory.PRODUCE,
                quantity=None,
            )
        ], unclear_photos=[])
        set_awaiting_confirm("user123", suggestion)

        msg, result = handle_correction("user123", "change Avocado to Guacamole")
        assert result is None  # not a final confirm
        # Verify item was renamed
        updated = get_awaiting_suggestion("user123")
        names = {i.name for i in updated.items}
        assert "Guacamole" in names
        assert "Avocado" not in names

    def test_change_nonexistent_item_returns_error(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        suggestion = PantrySuggestion(items=[
            SuggestedItem(
                name="Milk",
                confidence=Confidence.HIGH,
                status=ItemStatus.NEW,
                category=GroceryCategory.DAIRY,
                quantity=None,
            )
        ], unclear_photos=[])
        set_awaiting_confirm("user123", suggestion)

        msg, result = handle_correction("user123", "change NotThere to Something")
        assert "Couldn't find" in msg
        assert result is None


class TestApplyRemove:
    def test_remove_item(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        suggestion = PantrySuggestion(items=[
            SuggestedItem(
                name="Avocado",
                confidence=Confidence.HIGH,
                status=ItemStatus.NEW,
                category=GroceryCategory.PRODUCE,
                quantity=None,
            ),
            SuggestedItem(
                name="Milk",
                confidence=Confidence.HIGH,
                status=ItemStatus.NEW,
                category=GroceryCategory.DAIRY,
                quantity=None,
            ),
        ], unclear_photos=[])
        set_awaiting_confirm("user123", suggestion)

        msg, result = handle_correction("user123", "remove Avocado")
        assert result is None
        updated = get_awaiting_suggestion("user123")
        assert len(updated.items) == 1
        assert updated.items[0].name == "Milk"

    def test_remove_nonexistent_returns_error(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")
        suggestion = PantrySuggestion(items=[
            SuggestedItem(
                name="Milk",
                confidence=Confidence.HIGH,
                status=ItemStatus.NEW,
                category=GroceryCategory.DAIRY,
                quantity=None,
            )
        ], unclear_photos=[])
        set_awaiting_confirm("user123", suggestion)

        msg, result = handle_correction("user123", "remove NotThere")
        assert "Couldn't find" in msg
        assert result is None


# -------------------------------------------------------------------
# Confirm → pantry write tests
# -------------------------------------------------------------------

class TestConfirmPantryWrite:
    def test_confirm_adds_new_items_to_pantry(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")

        # Build the full vault path structure that _confirm() expects
        vault_root = tmp_path / "Documents" / "Obsidian"
        pantry_path = vault_root / "reference" / "grocery-lists"
        pantry_file = pantry_path / "pantry-items.md"
        pantry_path.mkdir(parents=True, exist_ok=True)

        categories = list(GroceryCategory)
        write_pantry(pantry_file, Pantry(items=[PantryItem(name="Eggs")]), categories)

        suggestion = PantrySuggestion(items=[
            SuggestedItem(
                name="Milk",
                confidence=Confidence.HIGH,
                status=ItemStatus.NEW,
                category=GroceryCategory.DAIRY,
                quantity=None,
            ),
            SuggestedItem(
                name="Eggs",
                confidence=Confidence.HIGH,
                status=ItemStatus.ALREADY_IN_PANTRY,
                category=GroceryCategory.OTHER,
                quantity=None,
            ),
        ], unclear_photos=[])
        set_awaiting_confirm("user123", suggestion)

        # Patch Path.home so _confirm constructs the same vault path
        monkeypatch.setattr(
            "commands.pantry_review.Path.home",
            lambda: tmp_path,
        )

        msg, confirmed = handle_correction("user123", "confirm")
        assert confirmed is True
        # Read back and verify
        updated = read_pantry(pantry_file)
        names_lower = {p.name.lower() for p in updated.items}
        assert "milk" in names_lower  # new item was added
        assert "eggs" in names_lower  # existing item still there

    def test_confirm_no_new_items_returns_nothing_to_add(self, tmp_path, monkeypatch):
        _patch_state_file(monkeypatch, tmp_path / "state.json")

        # Build the full vault path structure
        vault_root = tmp_path / "Documents" / "Obsidian"
        pantry_path = vault_root / "reference" / "grocery-lists"
        pantry_file = pantry_path / "pantry-items.md"
        pantry_path.mkdir(parents=True, exist_ok=True)

        categories = list(GroceryCategory)
        write_pantry(pantry_file, Pantry(items=[PantryItem(name="Milk")]), categories)

        # All items already in pantry
        suggestion = PantrySuggestion(items=[
            SuggestedItem(
                name="Milk",
                confidence=Confidence.HIGH,
                status=ItemStatus.ALREADY_IN_PANTRY,
                category=GroceryCategory.OTHER,
                quantity=None,
            )
        ], unclear_photos=[])
        set_awaiting_confirm("user123", suggestion)

        monkeypatch.setattr(
            "commands.pantry_review.Path.home",
            lambda: tmp_path,
        )

        msg, confirmed = handle_correction("user123", "confirm")
        assert confirmed is True
        assert "up to date" in msg


# -------------------------------------------------------------------
# Fixtures / helpers
# -------------------------------------------------------------------

def _fake_image_tool(results_by_url: list[dict]):
    """Build a fake image tool that returns pre-configured results."""
    def fake(url: str) -> dict:
        for r in results_by_url:
            if r.get("photo_url") == url or r.get("url") == url:
                return r
        return {"items": [], "unclear": True, "photo_url": url}
    return fake


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    """Temp state file for each test."""
    state_file = tmp_path / "state.json"
    _patch_state_file(monkeypatch, state_file)
    return tmp_path


def _patch_state_file(monkeypatch, path: Path):
    """Patch the state file path used by pantry_review."""
    import commands.pantry_review as pr
    monkeypatch.setattr(pr, "_STATE_FILE", path)
    monkeypatch.setattr(pr, "_STATE_DIR", path.parent)
