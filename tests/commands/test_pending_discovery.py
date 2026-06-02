"""Tests for the pending_discovery state machine."""
from datetime import date
from pathlib import Path
import tempfile

import pytest

from commands.pending_discovery import (
    start_discovery,
    get_pending_discovery,
    handle_discovery_reply,
    PendingDiscovery,
)
from recipes.discovery import RecipeCandidate


# Sample candidates for testing
SAMPLE_CANDIDATES = [
    RecipeCandidate(
        name="Chicken Tacos",
        description="A delicious weeknight taco recipe",
        source_url="https://www.allrecipes.com/chicken-tacos",
        score=0.95,
    ),
    RecipeCandidate(
        name="Easy Chicken Tacos",
        description="Quick and easy chicken tacos",
        source_url="https://www.budgetbytes.com/chicken-tacos",
        score=0.85,
    ),
]


class TestPendingDiscoveryState:
    """Basic state persistence for pending discovery."""

    def test_start_and_get_pending_discovery(self) -> None:
        """start_discovery stores state; get_pending_discovery retrieves it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plan_file = vault / "reference" / "meal-planning" / "plans" / "2026-05-04.md"
            plan_file.parent.mkdir(parents=True)
            plan_file.write_text("# Week of May 4\n")

            user_id = "test-user-123"

            prompt = start_discovery(
                user_id=user_id,
                plan_file=plan_file,
                vault=vault,
                day_date=date(2026, 5, 4),
                meal_name="Chicken Tacos",
                candidates=SAMPLE_CANDIDATES,
            )

            # Check prompt content
            assert "Chicken Tacos" in prompt
            assert "allrecipes.com" in prompt

            # Check state retrieval
            pending = get_pending_discovery(user_id)
            assert pending is not None
            assert pending.meal_name == "Chicken Tacos"
            assert pending.day_date == "2026-05-04"
            assert len(pending.candidates) == 2

    def test_get_pending_no_pending_returns_none(self) -> None:
        """get_pending_discovery returns None when nothing is pending."""
        pending = get_pending_discovery("nonexistent-user-xyz")
        assert pending is None


class TestHandleDiscoveryReply:
    """handle_discovery_reply processes user responses correctly."""

    def test_reply_yes_saves_recipe_and_updates_plan(self, monkeypatch) -> None:
        """Reply 'yes' saves the top candidate and updates the plan link."""
        mock_html = """
        <html><head><script type="application/ld+json">
        {"@type":"Recipe","name":"Chicken Tacos",
         "recipeIngredient":["1 lb chicken","8 tortillas"]}
        </script></head></html>
        """
        monkeypatch.setattr("obsidian.recipe_saver._fetch_page", lambda url: mock_html)

        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plan_file = vault / "reference" / "meal-planning" / "plans" / "2026-05-04.md"
            plan_file.parent.mkdir(parents=True)
            # Write a plan with a day that has no link
            plan_file.write_text(
                "# Week of May 4, 2026\n\n"
                "## Monday May 4\n"
                "**Supper:** Chicken Tacos\n"
                "🧊 Defrost: | 🔪 Prep:\n"
            )

            user_id = "test-user-yes"

            # Set up pending state
            start_discovery(
                user_id=user_id,
                plan_file=plan_file,
                vault=vault,
                day_date=date(2026, 5, 4),
                meal_name="Chicken Tacos",
                candidates=SAMPLE_CANDIDATES,
            )

            # Reply "yes"
            reply, done = handle_discovery_reply(user_id, vault, "yes")

            assert done
            assert "✅" in reply or "Saved" in reply

            # Verify pending is cleared
            assert get_pending_discovery(user_id) is None

            # Verify the plan file was updated with the link
            content = plan_file.read_text()
            assert "https://www.allrecipes.com/chicken-tacos" in content

    def test_reply_no_skips_and_clears(self) -> None:
        """Reply 'no' clears pending state without saving anything."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plan_file = vault / "reference" / "meal-planning" / "plans" / "2026-05-04.md"
            plan_file.parent.mkdir(parents=True)
            plan_file.write_text("# Week of May 4\n## Monday May 4\n**Supper:** Chicken Tacos\n")

            user_id = "test-user-no"

            start_discovery(
                user_id=user_id,
                plan_file=plan_file,
                vault=vault,
                day_date=date(2026, 5, 4),
                meal_name="Chicken Tacos",
                candidates=SAMPLE_CANDIDATES,
            )

            reply, done = handle_discovery_reply(user_id, vault, "no")

            assert done
            assert "Skipped" in reply or "skip" in reply.lower()
            assert get_pending_discovery(user_id) is None

            # Plan file should be unchanged (no link added)
            content = plan_file.read_text()
            assert "[Chicken Tacos](" not in content

    def test_reply_number_selects_specific_candidate(self, monkeypatch) -> None:
        """Reply '2' saves the second candidate instead of the first."""
        mock_html = """
        <html><head><script type="application/ld+json">
        {"@type":"Recipe","name":"Easy Chicken Tacos",
         "recipeIngredient":["1 lb chicken","tortillas"]}
        </script></head></html>
        """
        monkeypatch.setattr("obsidian.recipe_saver._fetch_page", lambda url: mock_html)

        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plan_file = vault / "reference" / "meal-planning" / "plans" / "2026-05-04.md"
            plan_file.parent.mkdir(parents=True)
            plan_file.write_text(
                "# Week of May 4, 2026\n\n"
                "## Monday May 4\n"
                "**Supper:** Chicken Tacos\n"
                "🧊 Defrost: | 🔪 Prep:\n"
            )

            user_id = "test-user-num"

            start_discovery(
                user_id=user_id,
                plan_file=plan_file,
                vault=vault,
                day_date=date(2026, 5, 4),
                meal_name="Chicken Tacos",
                candidates=SAMPLE_CANDIDATES,
            )

            # Reply "2" to pick the second candidate (budgetbytes)
            reply, done = handle_discovery_reply(user_id, vault, "2")

            assert done
            # Plan should now have budgetbytes URL
            content = plan_file.read_text()
            assert "budgetbytes.com" in content

    def test_reply_invalid_number_asks_for_valid_input(self) -> None:
        """Reply with an invalid number returns a guidance message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plan_file = vault / "plans" / "2026-05-04.md"
            plan_file.parent.mkdir(parents=True)
            plan_file.write_text("# Week of May 4\n")

            user_id = "test-user-invalid"

            start_discovery(
                user_id=user_id,
                plan_file=plan_file,
                vault=vault,
                day_date=date(2026, 5, 4),
                meal_name="Chicken Tacos",
                candidates=SAMPLE_CANDIDATES,
            )

            reply, done = handle_discovery_reply(user_id, vault, "99")

            assert not done  # Not done — needs valid input
            assert "1-2" in reply  # Should mention valid range