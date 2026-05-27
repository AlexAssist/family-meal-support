"""Internal sync logic: Obsidian ↔ Google Sheets."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from meal_plan import MealPlan
from obsidian.vault import read_meal_plan, write_meal_plan
from sheets import SheetsClient

# -------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------
_SYNC_META_FILENAME = ".sync-meta.json"

# -------------------------------------------------------------------
# Types
# -------------------------------------------------------------------

@dataclass(frozen=True)
class SyncMeta:
    """Metadata about the last sync operation."""
    last_push: str | None  # ISO timestamp
    last_pull: str | None  # ISO timestamp
    last_push_hash: str | None  # hash of what was pushed
    sheet_id: str  # which sheet was last synced


@dataclass
class ConflictDetected:
    """Sheets has changes since the last push."""
    sheet_plan: MealPlan
    last_push_timestamp: str


@dataclass
class SyncResult:
    """Result of a sync operation."""
    success: bool
    message: str
    days_synced: int = 0


# -------------------------------------------------------------------
# Sync metadata persistence
# -------------------------------------------------------------------

def _get_meta_path(plans_dir: Path) -> Path:
    return plans_dir / _SYNC_META_FILENAME


def _load_meta(plans_dir: Path) -> SyncMeta | None:
    path = _get_meta_path(plans_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return SyncMeta(**data)
    except Exception:
        return None


def _save_meta(plans_dir: Path, meta: SyncMeta) -> None:
    path = _get_meta_path(plans_dir)
    path.write_text(json.dumps({
        "last_push": meta.last_push,
        "last_pull": meta.last_pull,
        "last_push_hash": meta.last_push_hash,
        "sheet_id": meta.sheet_id,
    }))


def _meal_plan_hash(plan: MealPlan) -> str:
    """Hash of a meal plan for change detection."""
    parts = [
        plan.week_start.isoformat(),
        *[f"{d.date.isoformat()}|{d.recipe_name}|{d.recipe_link or ''}" for d in plan.days],
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


# -------------------------------------------------------------------
# Push: Obsidian → Sheets
# -------------------------------------------------------------------

def sync_push(
    vault: Path,
    plans_dir: Path,
    sheets_client: SheetsClient,
    week_start: date,
    tab_name: str = "Meal Plan",
) -> SyncResult:
    """Push the current week's meal plan from Obsidian to Sheets.

    Reads from Obsidian plan file, writes to Sheets (full replace),
    and records the push timestamp.
    """
    plan_file = plans_dir / f"{week_start.strftime('%Y-%m-%d')}.md"
    plan = read_meal_plan(plan_file)
    if plan is None:
        return SyncResult(
            success=False,
            message=f"No meal plan found for week of {week_start.strftime('%Y-%m-%d')}",
        )

    sheets_client.write_meal_plan(plan, tab_name=tab_name)

    now = datetime.now(timezone.utc).isoformat()
    existing = _load_meta(plans_dir)
    meta = SyncMeta(
        last_push=now,
        last_pull=existing.last_pull if existing else None,
        last_push_hash=_meal_plan_hash(plan),
        sheet_id=sheets_client._spreadsheet_id,  # noqa: SLF001
    )
    _save_meta(plans_dir, meta)

    return SyncResult(
        success=True,
        message=f"Meal plan pushed to Google Sheets ({len(plan.days)} days)",
        days_synced=len(plan.days),
    )


# -------------------------------------------------------------------
# Pull: Sheets → Obsidian
# -------------------------------------------------------------------

def sync_pull(
    vault: Path,
    plans_dir: Path,
    sheets_client: SheetsClient,
    week_start: date,
    tab_name: str = "Meal Plan",
) -> tuple[SyncResult, ConflictDetected | None]:
    """Pull the meal plan from Sheets into Obsidian.

    Returns (result, conflict). If conflict is not None, the caller
    must ask the user for confirmation before writing to Obsidian.
    """
    sheet_plan = sheets_client.read_meal_plan(week_start, tab_name=tab_name)

    meta = _load_meta(plans_dir)
    conflict = None
    if meta and meta.last_push_hash:
        current_hash = _meal_plan_hash(sheet_plan)
        if current_hash != meta.last_push_hash:
            conflict = ConflictDetected(
                sheet_plan=sheet_plan,
                last_push_timestamp=meta.last_push or "unknown",
            )

    return SyncResult(success=True, message="Sheet read OK", days_synced=len(sheet_plan.days)), conflict


def confirm_pull(
    vault: Path,
    plans_dir: Path,
    sheets_client: SheetsClient,
    sheet_plan: MealPlan,
    tab_name: str = "Meal Plan",
) -> SyncResult:
    """After user confirms a conflict, write the sheet plan to Obsidian.

    This writes the sheet_plan to Obsidian, then updates sync metadata
    to reflect the pull completion.
    """
    plan_file = plans_dir / f"{sheet_plan.week_start.strftime('%Y-%m-%d')}.md"
    write_meal_plan(sheet_plan, plan_file)

    now = datetime.now(timezone.utc).isoformat()
    existing = _load_meta(plans_dir)
    meta = SyncMeta(
        last_push=existing.last_push if existing else None,
        last_pull=now,
        last_push_hash=_meal_plan_hash(sheet_plan),
        sheet_id=sheets_client._spreadsheet_id,  # noqa: SLF001
    )
    _save_meta(plans_dir, meta)

    return SyncResult(
        success=True,
        message=f"Meal plan pulled from Google Sheets ({len(sheet_plan.days)} days)",
        days_synced=len(sheet_plan.days),
    )