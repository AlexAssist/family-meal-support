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

    # Match day section headers in three formats:
    #   ## Monday May 4          (old: month + day)
    #   ## Monday May 4, 2026    (old: month + day + year)
    #   ## Monday (2026-06-01)   (new: parentheses ISO)
    #   ## Wednesday 2026-06-03  (new: ISO without parentheses)
    p1 = re.compile(r"##\s+\w+\s+\w+\s+\d{1,2}(?:,\s*\d{4})?", re.IGNORECASE)  # old
    p2 = re.compile(r"##\s+\w+\s+\(\d{4}-\d{2}-\d{2}\)", re.IGNORECASE)  # new ()
    p3 = re.compile(r"##\s+\w+\s+\d{4}-\d{2}-\d{2}", re.IGNORECASE)  # new no ()
    day_pattern = re.compile("|".join([p1.pattern, p2.pattern, p3.pattern]), re.IGNORECASE)

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


def update_plan_meal_link(plan_file: Path, day_date: date, recipe_link: str) -> bool:
    """Update the recipe_link for a specific day in a plan file.

    Finds the day section matching `day_date` and replaces its **Supper:**
    line value to include the recipe_link. Preserves defrost/prep if present.

    Returns True if the day was found and updated, False otherwise.
    """
    if not plan_file.exists():
        return False

    text = plan_file.read_text()

    # Build patterns to match this specific day in any of the 3 formats
    day_str = day_date.strftime("%Y-%m-%d")
    day_name = _DAY_NAMES[day_date.weekday()]

    # Match a day header line for this specific date
    # Formats: ## Monday May 4, 2026  or  ## Monday (2026-06-01)  or  ## Monday 2026-06-01
    month_day = day_date.strftime("%B %-d")
    year_str = str(day_date.year)
    patterns = [
        # ## Monday May 4, 2026  (with comma + year)
        re.compile(r"(?m)^##\s+" + re.escape(day_name) + r"\s+" + re.escape(month_day) + r",?\s*" + re.escape(year_str) + r"(?:\s*$|\n)"),
        # ## Monday (2026-06-01)  (ISO in parentheses)
        re.compile(r"(?m)^##\s+" + re.escape(day_name) + r"\s+\(" + re.escape(day_str) + r"\)(?:\s*$|\n)"),
        # ## Monday 2026-06-01  (bare ISO)
        re.compile(r"(?m)^##\s+" + re.escape(day_name) + r"\s+" + re.escape(day_str) + r"(?:\s*$|\n)"),
        # ## Monday May 4  (month + day only, no year)
        re.compile(r"(?m)^##\s+" + re.escape(day_name) + r"\s+" + re.escape(month_day) + r"(?:\s*$|\n)"),
    ]

    # Find the day header line
    header_match = None
    for p in patterns:
        m = p.search(text)
        if m:
            header_match = m
            break

    if not header_match:
        return False

    header_end = header_match.end()

    # Find the **Supper:** line within this day's section (next 5 lines max)
    supper_section = text[header_end : header_end + 500]
    supper_match = re.search(r"(?m)^(\*\*Supper:\*\*\s*)(.*)$", supper_section)
    if not supper_match:
        return False

    prefix = supper_match.group(1)  # '**Supper:** '
    current_value = supper_match.group(2).rstrip()  # e.g. 'Chicken Tacos' or '[Chicken Tacos](url)'

    # Parse the current recipe name
    link_match = re.match(r"\[(.+?)\]\((.*?)\)", current_value)
    if link_match:
        recipe_name = link_match.group(1)
    else:
        recipe_name = current_value

    # Build the new value
    new_value = f"[{recipe_name}]({recipe_link})"

    # Replace within the section
    new_supper_line = prefix + new_value + "\n"
    old_supper_line = supper_match.group(0) + "\n"

    # Find exact position in original text
    old_start = header_end + supper_match.start()
    old_end = header_end + supper_match.end()
    new_text = text[:old_start] + new_supper_line.rstrip() + "\n" + text[old_end:]

    plan_file.write_text(new_text)
    return True