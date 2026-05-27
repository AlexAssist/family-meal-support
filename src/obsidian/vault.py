"""Read and write meal plans from Obsidian Markdown files."""
from datetime import date
from pathlib import Path
import re

from meal_plan import MealPlan, PlannedMeal


def read_meal_plan(plan_file: Path) -> MealPlan | None:
    """Read a weekly meal plan from a Markdown file.

    The file is named YYYY-MM-DD (the Monday of the week) and contains
    daily sections with optional recipe links in Markdown format.

    Returns None if the file does not exist.
    """
    if not plan_file.exists():
        return None

    text = plan_file.read_text()
    return _parse_plan_file(plan_file.name, text)


def _parse_plan_file(filename: str, text: str) -> MealPlan:
    """Parse a plan file's text content."""
    # Extract week start from filename (YYYY-MM-DD)
    date_str = filename.replace(".md", "")
    week_start = date.fromisoformat(date_str)

    days: list[PlannedMeal] = []
    current_date = week_start

    # Match each day section: ## Monday May 4  (or ## Monday May 4, 2026)
    day_pattern = re.compile(
        r"##\s+\w+\s+\w+\s+\d{1,2}(?:,?\s*\d{4})?", re.IGNORECASE
    )

    # Split by day headers
    sections = day_pattern.split(text)
    # First element is the header before any day sections
    sections.pop(0)

    for section in sections:
        # Find the **Supper:** line within this day's section.
        # Defrost/prep rows are on their own lines — ignore them.
        raw = ""
        for line in section.split("\n"):
            if line.startswith("**Supper:**"):
                # Take only the content on this same line (not subsequent rows)
                raw = line.split("**Supper:**", 1)[1].strip()
                break
        recipe_name, recipe_link = _parse_supper_line(raw)

        days.append(
            PlannedMeal(
                date=current_date,
                recipe_name=recipe_name,
                recipe_link=recipe_link,
            )
        )
        # Advance to next day (skip weekends for a 5-day plan, or just increment)
        current_date = _next_day(current_date)

    return MealPlan(week_start=week_start, days=days)


def _parse_supper_line(raw: str) -> tuple[str, str | None]:
    """Parse a **Supper:** line value.

    Returns (recipe_name, recipe_link). Link is None if no Markdown link.
    """
    # Markdown link: [Recipe Name](url) — url may be empty, http, or any scheme
    link_match = re.match(r"\[(.+?)\]\((.*?)\)", raw)
    if link_match:
        name = link_match.group(1)
        url = link_match.group(2)
        return name, url if url else None

    # Plain text recipe name (may be empty for no planned meal)
    return raw, None


def _next_day(current: date) -> date:
    """Advance one day."""
    return date(
        current.year,
        current.month,
        current.day + 1,
    )


def write_meal_plan(plan: MealPlan, plan_file: Path) -> None:
    """Write a MealPlan to a Markdown file.

    Raises PantryError if the file cannot be written.
    """
    raise NotImplementedError("write_meal_plan not yet implemented")
