"""Google Sheets adapter — thin interface at the data seam."""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from meal_plan import MealPlan, PlannedMeal
from shared.errors import SheetSyncError
from shared.types import GroceryList, GroceryItem, GroceryCategory

if TYPE_CHECKING:
    from googleapiclient.discovery import Resource
    from googleapiclient.errors import HttpError

# -------------------------------------------------------------------
# Column indices (1-based for Sheets API)
MEAL_COLUMNS = ["Date", "Meal", "Recipe Link", "Defrost", "Prep"]
DATE_COL, MEAL_COL, LINK_COL, DEFROST_COL, PREP_COL = range(1, 6)

GROCERY_COLUMNS = ["Done", "Item", "Qty", "Source"]
CHECK_COL, ITEM_COL, QTY_COL, SOURCE_COL = range(1, 5)


class SheetsClient:
    """Adapter for Google Sheets operations.

    All Google API complexity lives here. Core modules import this
    adapter, never googleapiclient directly.
    """

    def __init__(self, service: Resource, spreadsheet_id: str) -> None:
        """Initialize with an authenticated Sheets service and spreadsheet ID.

        Args:
            service: Authenticated googleapiclient Resource (sheets API).
            spreadsheet_id: The Sheets document ID (from the URL).
        """
        self._service = service
        self._spreadsheet_id = spreadsheet_id

    @property
    def spreadsheet_id(self) -> str:
        """Public accessor for the spreadsheet ID."""
        return self._spreadsheet_id

    # ------------------------------------------------------------------
    # Meal Plan
    # ------------------------------------------------------------------

    def write_meal_plan(self, plan: MealPlan, tab_name: str = "Meal Plan") -> None:
        """Write a 7-day meal plan to the Sheet.

        Clears existing content in the tab and writes fresh (full replace).

        Raises:
            SheetSyncError: If the Sheets API call fails.
        """
        try:
            self._clear_tab(tab_name)

            rows = [MEAL_COLUMNS]
            for day in plan.days:
                rows.append([
                    day.date.strftime("%Y-%m-%d"),
                    day.recipe_name or "",
                    day.recipe_link or "",
                    day.defrost_reminder or "",
                    day.prep_reminder or "",
                ])

            range_name = f"{tab_name}!A1:E{len(rows)}"
            body = {"values": rows}
            self._service.spreadsheets().values().update(
                spreadsheetId=self._spreadsheet_id,
                range=range_name,
                body=body,
                valueInputOption="USER_ENTERED",
            ).execute()

        except Exception as e:
            name = type(e).__name__
            if name == "HttpError":
                raise SheetSyncError("write_meal_plan", str(e)) from e
            raise

    def read_meal_plan(self, week_start: date, tab_name: str = "Meal Plan") -> MealPlan:
        """Read a 7-day meal plan from the Sheet.

        Raises:
            SheetSyncError: If the Sheets API call fails.
        """
        try:
            range_name = f"{tab_name}!A:E"
            result = self._service.spreadsheets().values().get(
                spreadsheetId=self._spreadsheet_id,
                range=range_name,
            ).execute()
            values: list[list[str]] = result.get("values", [])

            if not values:
                return MealPlan(week_start=week_start, days=[])

            days: list[PlannedMeal] = []
            for row in values[1:]:
                if len(row) < 2:
                    continue
                try:
                    day_date = date.fromisoformat(row[DATE_COL - 1].strip())
                except ValueError:
                    continue

                recipe_name = row[MEAL_COL - 1].strip() if len(row) >= MEAL_COL else ""
                recipe_link = row[LINK_COL - 1].strip() if len(row) >= LINK_COL else ""

                days.append(PlannedMeal(
                    date=day_date,
                    recipe_name=recipe_name,
                    recipe_link=recipe_link or None,
                ))

            return MealPlan(week_start=week_start, days=days)

        except Exception as e:
            name = type(e).__name__
            if name == "HttpError":
                raise SheetSyncError("read_meal_plan", str(e)) from e
            raise

    # ------------------------------------------------------------------
    # Grocery List
    # ------------------------------------------------------------------

    def write_grocery_list(self, grocery_list: GroceryList, tab_name: str = "Grocery") -> None:
        """Write a grocery list to the Grocery tab.

        Raises:
            SheetSyncError: If the Sheets API call fails.
        """
        try:
            self._clear_tab(tab_name)

            rows = [GROCERY_COLUMNS]
            prev_category = None
            prev_source = None
            for item in grocery_list.items:
                # Add Staples section divider before first staple item
                if item.source_recipe == "staples" and prev_source != "staples":
                    rows.append(["", "", "", ""])
                    rows.append(["", "━━ 🛒 STAPLES (always buy) ━━", "", ""])
                    prev_category = None  # reset so we don't double-insert category header
                # Add category header row when category changes
                if item.category != prev_category:
                    if prev_category is not None:
                        # Blank row between groups
                        rows.append(["", "", "", ""])
                    # Category header (bold via formatting, here just text)
                    rows.append(["", f"━━ {item.category.value.upper()} ━━", "", ""])
                    prev_category = item.category
                rows.append([
                    "true" if item.checked else "",
                    item.name,
                    item.quantity or "",
                    item.source_recipe or "",
                ])
                prev_source = item.source_recipe

            range_name = f"{tab_name}!A1:D{len(rows)}"
            body = {"values": rows}
            self._service.spreadsheets().values().update(
                spreadsheetId=self._spreadsheet_id,
                range=range_name,
                body=body,
                valueInputOption="USER_ENTERED",
            ).execute()

        except Exception as e:
            name = type(e).__name__
            if name == "HttpError":
                raise SheetSyncError("write_grocery_list", str(e)) from e
            raise

    def read_checked_grocery_items(self, tab_name: str = "Grocery") -> list[str]:
        """Return names of items checked (marked done) in the Grocery tab.

        Used by the done-shopping flow (#7).

        Raises:
            SheetSyncError: If the Sheets API call fails.
        """
        try:
            range_name = f"{tab_name}!A:B"
            result = self._service.spreadsheets().values().get(
                spreadsheetId=self._spreadsheet_id,
                range=range_name,
            ).execute()
            values: list[list[str]] = result.get("values", [])

            checked: list[str] = []
            for row in values[1:]:
                if len(row) < 2:
                    continue
                if row[CHECK_COL - 1].strip().lower() in ("true", "1", "yes"):
                    checked.append(row[ITEM_COL - 1].strip())

            return checked

        except Exception as e:
            name = type(e).__name__
            if name == "HttpError":
                raise SheetSyncError("read_checked_grocery_items", str(e)) from e
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clear_tab(self, tab_name: str) -> None:
        """Clear all values from a tab."""
        try:
            self._service.spreadsheets().values().clear(
                spreadsheetId=self._spreadsheet_id,
                range=f"{tab_name}!A:Z",
            ).execute()
        except Exception as e:
            name = type(e).__name__
            if name == "HttpError":
                raise SheetSyncError("clear_tab", str(e)) from e
            raise