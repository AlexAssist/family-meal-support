"""Internal sync logic: Obsidian ↔ Google Sheets."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from meal_plan import MealPlan
from obsidian.vault import read_meal_plan, write_meal_plan, update_plan_meal_link
from obsidian.recipe_saver import save_recipe, RecipeSaveError, _url_to_postfix
from recipes.discovery import RecipeCandidate, discover_recipe
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
        sheet_id=sheets_client.spreadsheet_id,
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
    to reflect the pull completion. For any PlannedMeal with a recipe_link
    that has no corresponding file in meals/, the recipe is fetched and
    saved so !grocery can pick it up.
    """
    plan_file = plans_dir / f"{sheet_plan.week_start.strftime('%Y-%m-%d')}.md"
    write_meal_plan(sheet_plan, plan_file)

    now = datetime.now(timezone.utc).isoformat()
    existing = _load_meta(plans_dir)
    meta = SyncMeta(
        last_push=existing.last_push if existing else None,
        last_pull=now,
        last_push_hash=_meal_plan_hash(sheet_plan),
        sheet_id=sheets_client.spreadsheet_id,
    )
    _save_meta(plans_dir, meta)

    # Sync any recipe links that don't have a local file yet
    _sync_missing_recipes(vault, sheet_plan)

    # Check for meals without links that need discovery
    discovery_result = _discover_and_prompt_recipes(vault, plan_file, sheet_plan)

    return SyncResult(
        success=True,
        message=f"Meal plan pulled from Google Sheets ({len(sheet_plan.days)} days)",
        days_synced=len(sheet_plan.days),
    ), discovery_result


def _discover_and_prompt_recipes(
    vault: Path,
    plan_file: Path,
    plan: MealPlan,
) -> _DiscoveryResult | None:
    """Check for PlannedMeals without recipe_links, attempt discovery.

    For each such meal, calls discover_recipe() (which reads from the
    agent-populated search cache) and determines whether to auto-save
    or surface to the user.

    Returns a _DiscoveryResult if any discovery is needed (caller must
    surface to user), or None if everything is resolved.

    The agent is responsible for calling handle_discovery_reply() when
    the user responds — this function only returns discovery state.
    """
    from commands.pending_discovery import start_discovery, get_pending_discovery

    no_link_days = [d for d in plan.days if not d.recipe_link and d.recipe_name.strip()]
    if not no_link_days:
        return None

    # Filter to days that don't already have a pending discovery
    user_id = "303354486393667585"  # Jason
    pending = get_pending_discovery(user_id)
    pending_dates = {pending.day_date} if pending else set()
    needs_discovery = [d for d in no_link_days if d.date.isoformat() not in pending_dates]
    if not needs_discovery:
        return None

    # Attempt discovery for each — use the agent-populated cache
    results_for_user: list[tuple[PlannedMeal, list[RecipeCandidate]]] = []
    auto_save: list[tuple[PlannedMeal, RecipeCandidate]] = []

    for day in needs_discovery:
        candidates = discover_recipe(day.recipe_name)
        if not candidates:
            continue

        top = candidates[0]
        is_high_quality = any(
            domain in top.source_url
            for domain in ("allrecipes.com", "seriouseats.com", "bbcgoodfood.com")
        )

        # Auto-accept single high-quality candidates
        if is_high_quality and len(candidates) == 1:
            auto_save.append((day, top))
        else:
            results_for_user.append((day, candidates))

    # Auto-save high-quality single candidates
    for day, candidate in auto_save:
        postfix = _url_to_postfix(candidate.source_url)
        try:
            saved = save_recipe(candidate, vault, postfix=postfix)
            update_plan_meal_link(plan_file, day.date, saved.link or candidate.source_url)
        except RecipeSaveError:
            pass

    # If everything auto-saved, nothing needs user input
    if not results_for_user:
        return None

    # Surface ambiguous results to user — use the first pending meal
    first_day, first_candidates = results_for_user[0]
    prompt = start_discovery(
        user_id=user_id,
        plan_file=plan_file,
        vault=vault,
        day_date=first_day.date,
        meal_name=first_day.recipe_name,
        candidates=first_candidates,
    )

    return _DiscoveryResult(
        prompt=prompt,
        plan_file=plan_file,
        day_date=first_day.date,
        meal_name=first_day.recipe_name,
    )


@dataclass
class _DiscoveryResult:
    """Result of _discover_and_prompt_recipes — agent must surface to user."""
    prompt: str
    plan_file: Path
    day_date: date
    meal_name: str


def _sync_missing_recipes(vault: Path, plan: MealPlan) -> list[str]:
    """Fetch and save recipes for any PlannedMeal with a recipe_link but no local file.

    Returns a list of recipe names that were saved.
    """
    from recipes.discovery import RecipeCandidate

    saved: list[str] = []
    meals_dir = vault / "reference" / "meal-planning" / "meals"

    for day in plan.days:
        if not day.recipe_link:
            continue

        postfix = _url_to_postfix(day.recipe_link)
        slug = _slugify_recipe_name(day.recipe_name)
        filename = f"{slug}-{postfix}.md"

        if (meals_dir / filename).exists():
            continue

        # Construct a RecipeCandidate and save it
        candidate = RecipeCandidate(
            name=day.recipe_name,
            description="",
            source_url=day.recipe_link,
        )
        try:
            save_recipe(candidate, vault, postfix=postfix)
            saved.append(day.recipe_name)
        except RecipeSaveError:
            # Log but don't fail the whole pull
            pass

    return saved


def _slugify_recipe_name(name: str) -> str:
    """Convert a recipe name to the same kebab-case slug used by save_recipe."""
    import re
    name = name.lower()
    name = re.sub(r"[^a-z0-9\s]", "", name)
    name = re.sub(r"\s+", "-", name)
    return name.strip("-")