"""!email command — send weekly meal plan + grocery snapshot to family.

Trigger: `!email` (primary), also natural language variants.
Sends to both Jason and Tara at once.
"""
from __future__ import annotations

import subprocess
from datetime import date, timedelta
from pathlib import Path


# -------------------------------------------------------------------
# Trigger patterns
# -------------------------------------------------------------------

def is_email_trigger(message: str) -> bool:
    """Return True if the message matches a weekly email trigger."""
    msg = message.strip().lower()
    return msg in ("!email", "!email", "send email", "weekly email", "email meal plan")


# -------------------------------------------------------------------
# Format helpers
# -------------------------------------------------------------------

def format_weekly_email(
    vault: Path,
    week_start: date,
) -> str | None:
    """Format a weekly email with meal plan and grocery list.

    Args:
        vault: Path to the Obsidian vault.
        week_start: Monday of the week to report on.

    Returns:
        Formatted email body as a string, or None if the plan is empty.
    """
    from grocery.generate import generate_grocery_list
    from obsidian.recipes import ObsidianRecipeStore
    from obsidian.vault import read_meal_plan
    from pantry.inventory import read_pantry

    plan_file = vault / "reference" / "meal-planning" / "plans" / f"{week_start.strftime('%Y-%m-%d')}.md"
    plan = read_meal_plan(plan_file)
    if plan is None:
        return None

    # Check if there are any planned meals
    if not any(day.recipe_name.strip() for day in plan.days):
        return None

    # Read pantry and recipe store
    pantry_file = vault / "reference" / "grocery-lists" / "pantry-items.md"
    pantry = read_pantry(pantry_file)
    recipe_store = ObsidianRecipeStore(vault / "reference" / "meal-planning" / "meals")

    grocery = generate_grocery_list(plan, pantry, recipe_store)

    # Build the email body
    lines: list[str] = []

    # Header
    lines.append(f"Week of {week_start.strftime('%B %-d, %Y')}")
    lines.append("=" * 40)
    lines.append("")

    # Meal plan section
    lines.append("📅 THIS WEEK'S MEALS")
    lines.append("")
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for day in plan.days:
        if day.recipe_name.strip():
            name = day.recipe_name
            link = f" ({day.recipe_link})" if day.recipe_link else ""
            lines.append(f"  {day_names[day.date.weekday()]} — {name}{link}")
            if day.defrost_reminder:
                lines.append(f"    🧊 Defrost: {day.defrost_reminder}")
            if day.prep_reminder:
                lines.append(f"    🔪 Prep: {day.prep_reminder}")
        else:
            lines.append(f"  {day_names[day.date.weekday()]} — (no plan)")
    lines.append("")

    # Grocery list section
    lines.append("🛒 GROCERY LIST")
    lines.append("")

    if grocery.items:
        # Group by category
        by_cat: dict[str, list[str]] = {}
        for item in grocery.items:
            cat = item.category.value if item.category else "Other"
            by_cat.setdefault(cat, []).append(f"  - {item.name}")
        for cat, items in by_cat.items():
            lines.append(f"[{cat}]")
            lines.extend(items)
            lines.append("")
    else:
        lines.append("  (no items needed — pantry is stocked!)")
        lines.append("")

    return "\n".join(lines)


# -------------------------------------------------------------------
# Send via gog
# -------------------------------------------------------------------

def _send_via_gog(subject: str, body: str, to: list[str]) -> tuple[bool, str]:
    """Send an email via gog CLI.

    Returns (success, error_message).
    """
    import subprocess

    # Write body to temp file to avoid shell escaping issues
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as f:
        f.write(body)
        body_path = f.name

    try:
        for recipient in to:
            result = subprocess.run(
                ["gog", "gmail", "send",
                 "--to", recipient,
                 "--subject", subject,
                 "--body-file", body_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                return False, f"gog failed for {recipient}: {result.stderr}"
        return True, ""
    finally:
        Path(body_path).unlink(missing_ok=True)


# -------------------------------------------------------------------
# Main handler
# -------------------------------------------------------------------

def handle_email(vault: Path, week_start: date | None = None) -> str:
    """Format and send the weekly email.

    Args:
        vault: Path to the Obsidian vault.
        week_start: Monday of the week to report on.
                  Defaults to the current week.

    Returns:
        A Discord-friendly status message.
    """
    if week_start is None:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

    body = format_weekly_email(vault, week_start)
    if body is None:
        return "❌ No meal plan found for this week."

    subject = f"📋 Meal Plan — Week of {week_start.strftime('%B %-d')}"

    recipients = ["jtbeck@gmail.com", "tarajbeck@gmail.com"]
    ok, err = _send_via_gog(subject, body, recipients)

    if ok:
        return (f"✅ Weekly meal plan emailed to {', '.join(recipients)}.\n"
                f"📋 *Subject: {subject}*")
    else:
        return f"❌ Failed to send email: {err}"