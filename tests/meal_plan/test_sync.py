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
)


class FakeSheetsClient:
    """Fake Sheets client for testing sync logic."""

    def __init__(self) -> None:
        self._written_plans: list[MealPlan] = []
        self._read_plans: list[MealPlan] = []
        self._spreadsheet_id = "fake-sheet-id"

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

            result = confirm_pull(vault, plans_dir, client, sheet_plan)

            assert result.success
            # Verify file was written
            plan_file = plans_dir / "2026-05-04.md"
            assert plan_file.exists()
            content = plan_file.read_text()
            assert "Tacos" in content