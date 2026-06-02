"""Tests for the meal_plan sync module."""
from datetime import date
from pathlib import Path
import json
import tempfile

import pytest

from meal_plan import MealPlan, PlannedMeal
from meal_plan._sync import (
    SyncMeta,
    ConflictDetected,
    SyncResult,
    _meal_plan_hash,
    _load_meta,
    _save_meta,
    _get_meta_path,
    sync_push,
    sync_pull,
    confirm_pull,
    _sync_missing_recipes,
    _slugify_recipe_name,
)


class FakeSheetsClient:
    """Fake Sheets client for testing sync logic."""

    def __init__(self) -> None:
        self._written_plans: list[MealPlan] = []
        self._read_plans: list[MealPlan] = []
        self.spreadsheet_id = "fake-sheet-id"

    def write_meal_plan(self, plan: MealPlan, tab_name: str = "Meal Plan") -> None:
        self._written_plans.append(plan)

    def read_meal_plan(self, week_start: date, tab_name: str = "Meal Plan") -> MealPlan:
        return self._read_plans[-1] if self._read_plans else MealPlan(week_start=week_start, days=[])


class TestMealPlanHash:
    """_meal_plan_hash produces stable hashes for change detection."""

    def test_same_plan_same_hash(self) -> None:
        plan1 = MealPlan(week_start=date(2026, 5, 4), days=[
            PlannedMeal(date=date(2026, 5, 4), recipe_name="Pasta"),
        ])
        plan2 = MealPlan(week_start=date(2026, 5, 4), days=[
            PlannedMeal(date=date(2026, 5, 4), recipe_name="Pasta"),
        ])
        assert _meal_plan_hash(plan1) == _meal_plan_hash(plan2)

    def test_different_recipe_different_hash(self) -> None:
        plan1 = MealPlan(week_start=date(2026, 5, 4), days=[
            PlannedMeal(date=date(2026, 5, 4), recipe_name="Pasta"),
        ])
        plan2 = MealPlan(week_start=date(2026, 5, 4), days=[
            PlannedMeal(date=date(2026, 5, 4), recipe_name="Tacos"),
        ])
        assert _meal_plan_hash(plan1) != _meal_plan_hash(plan2)


class TestSyncMetaPersistence:
    """Sync metadata is saved and loaded correctly."""

    def test_save_and_load_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            plans_dir = Path(tmpdir)
            meta = SyncMeta(
                last_push="2026-05-28T10:00:00Z",
                last_pull="2026-05-28T09:00:00Z",
                last_push_hash="abc123",
                sheet_id="sheet-1",
            )
            _save_meta(plans_dir, meta)
            loaded = _load_meta(plans_dir)

        assert loaded is not None
        assert loaded.last_push == "2026-05-28T10:00:00Z"
        assert loaded.last_pull == "2026-05-28T09:00:00Z"
        assert loaded.last_push_hash == "abc123"
        assert loaded.sheet_id == "sheet-1"

    def test_load_meta_missing_file_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            plans_dir = Path(tmpdir)
            result = _load_meta(plans_dir)

        assert result is None


class TestSyncPush:
    """!sync push reads from Obsidian and writes to Sheets."""

    def test_push_no_plan_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plans_dir = vault / "plans"
            plans_dir.mkdir()
            client = FakeSheetsClient()

            result = sync_push(vault, plans_dir, client, date(2026, 5, 4))

        assert not result.success
        assert "No meal plan found" in result.message

    def test_push_writes_plan_to_sheets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plans_dir = vault / "plans"
            plans_dir.mkdir()

            # Create a plan file
            plan_file = plans_dir / "2026-05-04.md"
            plan_file.write_text("# Week of May 4, 2026\n\n## Monday May 4\n**Supper:** Pasta\n")

            client = FakeSheetsClient()

            result = sync_push(vault, plans_dir, client, date(2026, 5, 4))

        assert result.success
        assert len(client._written_plans) == 1
        assert client._written_plans[0].days[0].recipe_name == "Pasta"


class TestSyncPull:
    """!sync pull reads from Sheets, detects conflicts, and can confirm write."""

    def test_pull_no_conflict_writes_to_obsidian(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plans_dir = vault / "plans"
            plans_dir.mkdir()

            client = FakeSheetsClient()
            # Configure the fake client to return a plan
            client._read_plans.append(MealPlan(week_start=date(2026, 5, 4), days=[
                PlannedMeal(date=date(2026, 5, 4), recipe_name="Tacos"),
            ]))

            result, conflict = sync_pull(vault, plans_dir, client, date(2026, 5, 4))

        assert result.success
        assert conflict is None

    def test_pull_with_conflict_detects_and_returns_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plans_dir = vault / "plans"
            plans_dir.mkdir()

            # First, push a plan to establish a baseline hash
            plan_file = plans_dir / "2026-05-04.md"
            plan_file.write_text("# Week of May 4, 2026\n\n## Monday May 4\n**Supper:** Pasta\n")
            client = FakeSheetsClient()
            sync_push(vault, plans_dir, client, date(2026, 5, 4))

            # Now Sheets has a different plan
            client._read_plans.append(MealPlan(week_start=date(2026, 5, 4), days=[
                PlannedMeal(date=date(2026, 5, 4), recipe_name="Tacos"),
            ]))

            result, conflict = sync_pull(vault, plans_dir, client, date(2026, 5, 4))

        assert result.success
        assert conflict is not None
        assert conflict.sheet_plan.days[0].recipe_name == "Tacos"

    def test_confirm_pull_writes_to_obsidian(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plans_dir = vault / "plans"
            plans_dir.mkdir()

            client = FakeSheetsClient()
            sheet_plan = MealPlan(week_start=date(2026, 5, 4), days=[
                PlannedMeal(date=date(2026, 5, 4), recipe_name="Tacos"),
            ])

            result, _discovery = confirm_pull(vault, plans_dir, client, sheet_plan)

            assert result.success
            # Verify file was written
            plan_file = plans_dir / "2026-05-04.md"
            assert plan_file.exists()
            content = plan_file.read_text()
            assert "Tacos" in content


class TestRecipeSync:
    """Recipe sync: PlannedMeals with recipe_links are saved to meals/ on pull."""

    def test_confirm_pull_saves_recipe_file_from_link(self, monkeypatch) -> None:
        """When a PlannedMeal has a recipe_link, the recipe is fetched and saved."""
        mock_html = """
        <html><head><script type="application/ld+json">
        {"@type":"Recipe","name":"Chicken Tacos",
         "recipeIngredient":["1 lb chicken","8 tortillas","1 cup salsa"],
         "nutrition":{"calories":"420 kcal","proteinContent":"35g"}}
        </script></head></html>
        """
        monkeypatch.setattr("obsidian.recipe_saver._fetch_page", lambda url: mock_html)

        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plans_dir = vault / "plans"
            plans_dir.mkdir()

            client = FakeSheetsClient()
            sheet_plan = MealPlan(week_start=date(2026, 5, 4), days=[
                PlannedMeal(
                    date=date(2026, 5, 4),
                    recipe_name="Chicken Tacos",
                    recipe_link="https://www.allrecipes.com/chicken-tacos",
                ),
            ])

            result, discovery_result = confirm_pull(vault, plans_dir, client, sheet_plan)

            assert result.success
            # Recipe file should exist
            meals_dir = vault / "reference" / "meal-planning" / "meals"
            assert meals_dir.exists()
            recipe_files = list(meals_dir.glob("*.md"))
            assert len(recipe_files) == 1
            assert "chicken-tacos-allrecipes" in recipe_files[0].name
            content = recipe_files[0].read_text()
            assert "Chicken Tacos" in content
            assert "chicken" in content.lower()

    def test_confirm_pull_skips_recipe_already_in_meals(self, monkeypatch) -> None:
        """If the recipe file already exists, it is not re-fetched."""
        fetch_calls: list[str] = []

        def track_fetch(url: str) -> str:
            fetch_calls.append(url)
            return """<html><head><script type="application/ld+json">
            {"@type":"Recipe","name":"Pasta",
             "recipeIngredient":["pasta","sauce"]}
            </script></head></html>"""

        monkeypatch.setattr("obsidian.recipe_saver._fetch_page", track_fetch)

        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plans_dir = vault / "plans"
            plans_dir.mkdir()

            # Pre-create the recipe file
            meals_dir = vault / "reference" / "meal-planning" / "meals"
            meals_dir.mkdir(parents=True)
            (meals_dir / "pasta-allrecipes.md").write_text("# Already there\n")

            client = FakeSheetsClient()
            sheet_plan = MealPlan(week_start=date(2026, 5, 4), days=[
                PlannedMeal(
                    date=date(2026, 5, 4),
                    recipe_name="Pasta",
                    recipe_link="https://www.allrecipes.com/pasta",
                ),
            ])

            result, discovery_result = confirm_pull(vault, plans_dir, client, sheet_plan)

            assert result.success
            assert len(fetch_calls) == 0  # Not fetched — file already exists

    def test_confirm_pull_continues_on_recipe_save_error(self, monkeypatch) -> None:
        """If a recipe fails to save, the pull still succeeds."""
        def fail_fetch(url: str) -> str:
            raise Exception("Network error")

        monkeypatch.setattr("obsidian.recipe_saver._fetch_page", fail_fetch)

        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            plans_dir = vault / "plans"
            plans_dir.mkdir()

            client = FakeSheetsClient()
            sheet_plan = MealPlan(week_start=date(2026, 5, 4), days=[
                PlannedMeal(
                    date=date(2026, 5, 4),
                    recipe_name="Bad Recipe",
                    recipe_link="https://example.com/bad",
                ),
            ])

            result, discovery_result = confirm_pull(vault, plans_dir, client, sheet_plan)

            # Pull itself still succeeds even if recipe fetch fails
            assert result.success
            plan_file = plans_dir / "2026-05-04.md"
            assert plan_file.exists()

    def test_slugify_recipe_name(self) -> None:
        """_slugify_recipe_name produces kebab-case slugs matching save_recipe."""
        assert _slugify_recipe_name("Chicken Tacos") == "chicken-tacos"
        assert _slugify_recipe_name("Salmon Pasta Bake!") == "salmon-pasta-bake"
        # Dashes are stripped (same as save_recipe's _slugify)
        assert _slugify_recipe_name("Quick 15-Minute Chili") == "quick-15minute-chili"