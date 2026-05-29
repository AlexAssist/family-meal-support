# Family Meal Support

Meal planning, grocery lists, pantry management, and recipe discovery for the Beck household.

## Project Status

🟢 **Implementation Complete** — Core commands shipped and operational.

All commands are accessible via Discord DM to Alex (no prefix needed — just talk naturally).

---

## Commands

### `!tonight` — What's for Dinner?

Quick lookup of tonight's planned meal from the weekly meal plan.

```
!tonight
```

Shows:
- **Tonight: {Recipe Name}** with a link to the recipe
- Any defrost reminders (e.g. "move from freezer to fridge this morning")
- Any prep reminders (e.g. "marinate after school")

Reads from `reference/meal-planning/plans/YYYY-MM-DD.md` in the vault.

---

### `!grocery` — Generate Grocery List

Builds a smart grocery list from the current week's meal plan, subtracts what you already have in pantry, and writes it to Google Sheets.

```
!grocery
```

Flow:
1. Reads this week's meal plan (`plans/YYYY-MM-DD.md`)
2. Looks up each recipe's ingredients
3. Subtracts items already in your pantry
4. Adds any missing staples (butter, eggs, etc.)
5. Groups items by store section (Dairy, Produce, Meat, etc.)
6. Writes to the **Grocery** tab in Google Sheets

Output:
- A Discord message with item count and category count
- A link to open the Google Sheet

---

### `!doneshopping` — After You Shop

Run after you've done the grocery shopping and checked items off in Sheets.

```
!doneshopping
```
Also triggers: "done shopping", "shopping done", "finished shopping"

Flow:
1. Reads checked items from the **Grocery** tab in Google Sheets
2. Compares against your current pantry (`pantry-items.md`)
3. Items already in pantry → skipped
4. New items → added to `pantry-items.md` under the right category
5. Posts a summary to Discord

---

### Pantry Photo Review — Update What's in Your Fridge/Pantry

Send Alex photos of your fridge or pantry, then say "done" to have them analyzed and merged into your pantry list.

**Step 1 — Send photos:**
Just send images in the DM chat (as attachments or links). You can send multiple.

**Step 2 — Say "done":**
```
done
```
Also triggers: "review pantry", "update pantry", "pantry review", `!pantry`

Alex analyzes each photo, identifies food items with estimated quantities, and shows you a suggested update.

**Step 3 — Correct if needed:**
```
change Chicken to Chicken Thighs
remove Salsa
```

Alex re-generates the suggestion. When it looks right:

```
confirm
```
Also triggers: "looks good", "yep", "yes", "that's right"

Changes are written to `pantry-items.md`.

---

### `!email` — Send Weekly Plan to Family

Sends the current week's meal plan and grocery list to both Jason and Tara via Gmail.

```
!email
```
Also triggers: "send email", "weekly email", "email meal plan"

Email includes:
- Full 7-day meal plan with recipe links
- Defrost/prep reminders per day
- Grocery list grouped by category

Recipients: jtbeck@gmail.com, tarajbeck@gmail.com

---

## Daily Dinner Brief (Automated)

Every morning at **7:00 AM MDT**, Alex posts a brief to Discord with:
- What tonight's planned meal is (with recipe link)
- Any defrost or prep reminders

You don't need to trigger this — it's automatic. Configure or disable via the cron job `family-meal-support/daily-brief`.

---

## Google Sheets Structure

The project syncs with a shared Google Spreadsheet (owned by Tara, linked from the grocery flow).

### Tab: Meal Plan
| Date | Meal | Recipe Link | Defrost | Prep |
|------|------|-------------|---------|------|
| 2026-05-25 | Butter Chicken | https://... | | |

- **Date** — YYYY-MM-DD format
- **Meal** — Recipe name (must match a file in `reference/meal-planning/meals/`)
- **Recipe Link** — Optional URL to the recipe
- **Defrost** — Optional reminder (e.g. "chicken this morning")
- **Prep** — Optional reminder (e.g. "marinate after school")

### Tab: Grocery
| Done | Item | Qty | Source |
|------|------|-----|--------|
| true | Chicken Thighs | 2 lbs | Butter Chicken |
| | Basmati Rice | 1 kg | |

- **Done** — Check this when you've bought the item (triggers `!doneshopping`)
- **Item** — Ingredient name
- **Qty** — Optional quantity
- **Source** — Which recipe needs this (set automatically by `!grocery`)

---

## Data Sources

### Meal Plans
- Weekly plans: `reference/meal-planning/plans/YYYY-MM-DD.md`
- Daily logs: `reference/meal-planning/daily/YYYY-MM-DD.md` (with macros)

### Recipes
- Structured recipes: `reference/meal-planning/meals/*.md` (12 recipes)
- Captured recipes: `captures/recipes/*.md` (2 sourced recipes)

### Pantry
`reference/grocery-lists/pantry-items.md` — what you currently have at home

### Grocery Lists
`reference/grocery-lists/YYYY-MM-DD-grocery.md` — generated lists by date

---

## Architecture

```
src/
├── commands/           # Discord command handlers
│   ├── tonight.py      # !tonight
│   ├── grocery.py      # !grocery → Sheets
│   ├── doneshopping.py # !doneshopping ← Sheets
│   ├── pantry_review.py# Photo review + state machine
│   ├── email.py        # !email via gog
│   └── daily_brief.py  # Cron-triggered dinner brief
├── grocery/
│   └── generate.py     # Core grocery list generation
├── obsidian/
│   ├── vault.py        # Read/write meal plans
│   └── recipes.py       # Recipe store
├── pantry/
│   ├── inventory.py    # Read/write pantry
│   └── _categorize.py  # Category inference
├── sheets/
│   ├── auth.py         # Google OAuth
│   └── client.py       # Sheets API adapter
└── shared/
    ├── types.py        # MealPlan, GroceryList, etc.
    └── errors.py       # SheetSyncError, etc.
```

---

## Related Documentation

- **Vault:** `projects/family-meal-support/` — full project docs, PRDs, decisions
- **GitHub:** https://github.com/AlexAssist/family-meal-support
- **ADR-001:** Tech stack and design decisions in vault
- **PRD-CORE.md:** Feature spec for core system
- **PRD-002-PANTRY.md:** Pantry photo feature spec