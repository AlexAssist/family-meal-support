# Family Meal Support

Meal planning, grocery lists, pantry management, and recipe discovery for the Beck household.

## Project Status

🟡 **Early Implementation** — First tracer bullet (`!tonight`) shipped.

## Quick Links

- **Vault docs:** `AlexAssist/notes` → `projects/family-meal-support/`
- **Recipes:** `reference/meal-planning/meals/`
- **Pantry:** `reference/grocery-lists/pantry-items.md`
- **Meal Plans:** `reference/meal-planning/plans/`

## Commands

### `!tonight`

What's for dinner tonight?

```
!tonight
```

Reads the current week's meal plan from the vault and posts tonight's planned meal.

- **Planned meal:** posts "Tonight: {recipe_name} ({recipe_link})"
- **No meal planned:** posts "No meal planned for tonight."
- **No plan file exists:** posts "No meal plan found for this week."

Reads from `reference/meal-planning/plans/YYYY-MM-DD.md` in the vault.

## Setup

```bash
# Clone the repo
git clone https://github.com/AlexAssist/family-meal-support
cd family-meal-support

# Copy and edit environment variables
cp .env.example .env
# Set VAULT_PATH to your Obsidian vault

# Install dev dependencies (optional)
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .
mypy src/
```

## Architecture

```
src/
├── shared/          # Shared types and errors
│   ├── types.py     # MealPlan, PlannedMeal, Recipe, GroceryList, Pantry...
│   └── errors.py    # MealSupportError, RecipeNotFoundError...
├── obsidian/        # Vault adapter
│   └── vault.py     # read_meal_plan(), write_meal_plan()
├── meal_plan/       # Meal plan management
├── commands/        # Discord command handlers
│   └── tonight.py   # get_tonight_meal()
└── ...
```

## For Tara (Sheets Integration)

Tara manages grocery lists via Google Sheets. See `PRD-CORE.md` in the vault for the full design — Tara sync is in the roadmap.

## Tech Stack

- Python 3.11+
- TDD (pytest, red→green→refactor)
- ruff + mypy
- Obsidian Markdown (canonical) + Google Sheets (collaborative)
