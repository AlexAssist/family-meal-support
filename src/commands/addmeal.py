"""!addmeal command — add a planned meal to a day."""
from datetime import date, timedelta
from pathlib import Path
import re

from meal_plan import MealPlan, PlannedMeal
from obsidian.vault import read_meal_plan, write_meal_plan
from recipes.lookup import find_recipe, RecipeStore


# -------------------------------------------------------------------
# Day parser
# -------------------------------------------------------------------
_WEEKDAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_WEEKDAY_ABBREVS = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def parse_day(day_spec: str, today: date) -> date:
    """Convert a day specification to a date.

    Accepts:
      - Full weekday name: "Monday", "Tuesday", ...
      - Abbreviated: "Mon", "Tue", ...
      - YYYY-MM-DD ISO date
      - Weekday name with trailing colon: "Tuesday:"

    Returns the date within the week containing `today`.
    Raises ValueError if the day name is not recognized.
    """
    # Strip trailing colon (common in "Tuesday: Chicken")
    cleaned = day_spec.rstrip(":").strip()

    # Try YYYY-MM-DD
    if re.match(r"\d{4}-\d{2}-\d{2}", cleaned):
        return date.fromisoformat(cleaned)

    # Try full weekday name or abbrev
    lower = cleaned.lower()
    if lower in _WEEKDAY_NAMES:
        target_weekday = _WEEKDAY_NAMES[lower]
    elif lower in _WEEKDAY_ABBREVS:
        target_weekday = _WEEKDAY_ABBREVS[lower]
    else:
        raise ValueError(f"Unknown day: {day_spec!r}")

    # Find the Monday of the current week
    days_since_monday = today.weekday()
    monday = today - timedelta(days=days_since_monday)
    return monday + timedelta(days=target_weekday)


def add_meal_to_plan(
    vault: Path,
    day_spec: str,
    meal_name: str,
    recipe_store: RecipeStore,
    *,
    today: date | None = None,
) -> tuple[PlannedMeal, bool]:
    """Add a meal to the plan for a given day.

    Args:
        vault: Path to the Obsidian vault.
        day_spec: Day specification (weekday name, abbrev, or YYYY-MM-DD).
        meal_name: Recipe name (exact or substring match).
        recipe_store: Source of recipes.
        today: Reference date for weekday lookup (defaults to today).

    Returns:
        (new_meal, was_overwrite) — the added PlannedMeal and whether the day
        already had a meal.

    Raises:
        RecipeNotFoundError: No recipe matches the name.
        MultipleCandidatesError: Multiple recipes match the name.
        ValueError: Unrecognized day specification.
    """
    if today is None:
        today = date.today()

    # Parse day
    target_date = parse_day(day_spec, today)

    # Find the Monday of that week
    days_since_monday = target_date.weekday()
    monday = target_date - timedelta(days=days_since_monday)
    plan_file = (
        vault
        / "reference"
        / "meal-planning"
        / "plans"
        / f"{monday.strftime('%Y-%m-%d')}.md"
    )

    # Read existing plan or start empty
    plan = read_meal_plan(plan_file)

    # Look up recipe
    recipe = find_recipe(meal_name, recipe_store)

    # Build or extend plan to include target_date
    if plan is None:
        # No plan file — create one for this week
        week_days = _build_empty_week(monday)
        plan = MealPlan(week_start=monday, days=week_days)
    else:
        # Ensure plan covers target_date (may need to extend for past/future weeks)
        week_days = _ensure_day_in_plan(plan, target_date)

    # Find or create the PlannedMeal for target_date
    existing_meal: PlannedMeal | None = None
    for d in week_days:
        if d.date == target_date:
            if d.recipe_name.strip():
                existing_meal = d
            break

    was_overwrite = existing_meal is not None

    # Update the day with the new meal
    new_meal = PlannedMeal(
        date=target_date,
        recipe_name=recipe.name,
        recipe_link=recipe.link,
    )
    week_days = [
        new_meal if d.date == target_date else d
        for d in week_days
    ]

    updated_plan = MealPlan(week_start=monday, days=week_days)
    write_meal_plan(updated_plan, plan_file)

    return new_meal, was_overwrite


def _build_empty_week(monday: date) -> list[PlannedMeal]:
    """Build a 7-day week of empty PlannedMeals starting Monday."""
    return [
        PlannedMeal(date=monday + timedelta(days=i), recipe_name="")
        for i in range(7)
    ]


def _ensure_day_in_plan(plan: MealPlan, target_date: date) -> list[PlannedMeal]:
    """Extend plan.days to cover target_date if it's not already present.

    Maintains existing PlannedMeals for days that overlap.
    """
    if not plan.days:
        return _build_empty_week(plan.week_start)

    existing_dates = {d.date for d in plan.days}
    if target_date in existing_dates:
        return list(plan.days)

    # Determine the range to cover: from Monday of the earliest existing day
    # to Sunday of the latest existing day, inclusive, extended to include target_date
    all_dates = sorted(existing_dates | {target_date})
    new_monday = all_dates[0] - timedelta(days=all_dates[0].weekday())
    new_sunday = all_dates[-1] + timedelta(days=6 - all_dates[-1].weekday())

    # Build new day list
    new_days: list[PlannedMeal] = []
    current = new_monday
    while current <= new_sunday:
        # Check if we already have this date
        for existing in plan.days:
            if existing.date == current:
                new_days.append(existing)
                break
        else:
            new_days.append(PlannedMeal(date=current, recipe_name=""))
        current += timedelta(days=1)

    return new_days