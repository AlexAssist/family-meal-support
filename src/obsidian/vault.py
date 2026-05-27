"""Read and write meal plans from Obsidian Markdown files."""
from datetime import date, timedelta
from pathlib import Path
import re

from meal_plan import MealPlan, PlannedMeal


_DEFROST_PREP_PATTERN = re.compile(
    r"🧊\s*Defrost:\s*(.*?)\s*\|\s*🔪\s*Prep:\s*(.*)",
    re.IGNORECASE,
)


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
        # Find the **Supper:** line and parse defrost/prep from section
        raw = ""
        defrost: str | None = None
        prep: str | None = None
        for line in section.split("\n"):
            line_stripped = line.strip()
            if line_stripped.startswith("**Supper:**"):
                # Take only the content on this same line (not subsequent rows)
                raw = line_stripped.split("**Supper:**", 1)[1].strip()
            elif _DEFROST_PREP_PATTERN.match(line_stripped):
                m = _DEFROST_PREP_PATTERN.match(line_stripped)
                def_text = m.group(1).strip()
                prep_text = m.group(2).strip()
                if def_text and def_text != "None":
                    defrost = def_text
                if prep_text and prep_text != "None":
                    prep = prep_text

        recipe_name, recipe_link = _parse_supper_line(raw)

        days.append(
            PlannedMeal(
                date=current_date,
                recipe_name=recipe_name,
                recipe_link=recipe_link,
                defrost_reminder=defrost,
                prep_reminder=prep,
            )
        )
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
    return current + timedelta(days=1)


# -------------------------------------------------------------------
# Day-of-week names for formatting
# -------------------------------------------------------------------
_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _format_day(
    date: date, recipe_name: str, recipe_link: str | None, defrost: str | None, prep: str | None
) -> str:
    """Format a single day section for a plan file."""
    day_name = _DAY_NAMES[date.weekday()]
    month_day = f"{day_name} {date.strftime('%B %-d')}"

    # Build the **Supper:** line value
    if recipe_name.strip():
        if recipe_link:
            supper_value = f"[{recipe_name}]({recipe_link})"
        else:
            supper_value = recipe_name
    else:
        supper_value = ""

    defrost_val = defrost if defrost else ""
    prep_val = prep if prep else ""

    return f"""## {month_day}
**Supper:** {supper_value}
🧊 Defrost: {defrost_val} | 🔪 Prep: {prep_val}
"""


def write_meal_plan(plan: MealPlan, plan_file: Path) -> None:
    """Write a MealPlan to a Markdown file.

    Raises PantryError if the file cannot be written.
    """
    # Header
    header = f"# Week of {plan.week_start.strftime('%B %-d, %Y')}\n"

    # Day sections
    days_text = "".join(
        _format_day(day.date, day.recipe_name, day.recipe_link, day.defrost_reminder, day.prep_reminder)
        for day in plan.days
    )

    # Footer
    footer = f"\n---\n\n*Plan created {date.today().strftime('%Y-%m-%d')}*\n"

    text = header + days_text + footer

    # Ensure directory exists
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(text)