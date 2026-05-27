"""!tonight command - what's for dinner tonight?"""


def get_tonight_meal(vault: "Path", today: "date") -> "PlannedMeal | None":
    """Return the planned meal for today, or None if nothing is planned.

    Args:
        vault: Path to the Obsidian vault.
        today: The date to look up.

    Returns:
        The PlannedMeal for today, or None if no plan or no meal scheduled.
    """
    from datetime import timedelta

    # Find the Monday of the current week
    days_since_monday = today.weekday()
    monday = today - timedelta(days=days_since_monday)
    monday_str = monday.strftime("%Y-%m-%d")

    plan_file = (
        vault
        / "reference"
        / "meal-planning"
        / "plans"
        / f"{monday_str}.md"
    )

    if not plan_file.exists():
        return None

    from obsidian.vault import read_meal_plan

    plan = read_meal_plan(plan_file)
    if plan is None:
        return None

    # Find the day matching today
    for day in plan.days:
        if day.date == today:
            if day.recipe_name.strip():
                return day
            return None

    return None
