"""!mealplan command - show a weekly meal plan."""
from datetime import date, timedelta
from pathlib import Path

from meal_plan import MealPlan
from obsidian.vault import read_meal_plan


def get_week_monday(d: date) -> date:
    """Return the Monday that starts the week containing date d."""
    return d - timedelta(days=d.weekday())


def format_meal_plan(vault: Path, today: date, *, next: bool = False) -> str | None:
    """Format a weekly meal plan for display.

    Args:
        vault: Path to the Obsidian vault.
        today: A date in the week to display.
        next: If True, show the following week instead.

    Returns:
        A formatted multi-line plan, or None if no plan file exists.
    """
    monday = get_week_monday(today)
    if next:
        monday += timedelta(weeks=1)

    plan_file = (
        vault
        / "reference"
        / "meal-planning"
        / "plans"
        / f"{monday.strftime("%Y-%m-%d")}.md"
    )

    plan = read_meal_plan(plan_file)
    if plan is None:
        return None

    return _format(plan)


def _format(plan: MealPlan) -> str:
    """Format a MealPlan as a readable weekly view.

    Output format:
        Week of Month Day, Year
        Mon Jan 1 — Recipe Name <link>
        Tue Jan 2 — Recipe Name
        ...
    """
    lines: list[str] = []

    # Header — "Week of May 4, 2026"
    first_day = plan.days[0]
    lines.append(f"Week of {first_day.date.strftime("%B %-d, %Y")}")

    # Day lines — Mon Jan 1 — Recipe Name <link>
    for day in plan.days:
        day_str = day.date.strftime("%a %b %-d")
        if day.recipe_name.strip():
            meal_str = day.recipe_name
            if day.recipe_link:
                meal_str += f" <{day.recipe_link}>"
            lines.append(f"{day_str} — {meal_str}")
        else:
            lines.append(f"{day_str} — —")

    return "\n".join(lines)
