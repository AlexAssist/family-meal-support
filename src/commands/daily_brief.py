"""!daily-brief command — what's for dinner tonight and any prep reminders."""
from __future__ import annotations

from datetime import date
from pathlib import Path


def format_daily_brief(vault: Path, today: date) -> str | None:
    """Format the daily dinner brief for today.

    Args:
        vault: Path to the Obsidian vault.
        today: Today's date.

    Returns:
        A formatted string with tonight's meal and prep/defrost reminders,
        or None if no meal is planned.
    """
    from commands.tonight import get_tonight_meal

    meal = get_tonight_meal(vault, today)
    if meal is None:
        return None

    # Build the brief
    if meal.recipe_link:
        brief = f"**Tonight: {meal.recipe_name}** ({meal.recipe_link})"
    else:
        brief = f"**Tonight: {meal.recipe_name}**"

    # Add defrost/prep reminders if present
    reminders = []
    if meal.defrost_reminder:
        reminders.append(f"🧊 Defrost: {meal.defrost_reminder}")
    if meal.prep_reminder:
        reminders.append(f"🔪 Prep: {meal.prep_reminder}")

    if reminders:
        brief += "\n" + "\n".join(reminders)

    return brief