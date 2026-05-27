"""Project-specific exceptions."""


class MealSupportError(Exception):
    """Base for all project errors."""

    pass


class RecipeNotFoundError(MealSupportError):
    """Recipe not found in the store."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Recipe not found: {name}")


class SheetSyncError(MealSupportError):
    """Google Sheets read/write failed."""

    def __init__(self, operation: str, details: str) -> None:
        self.operation = operation
        self.details = details
        super().__init__(f"Sheet {operation} failed: {details}")


class PantryError(MealSupportError):
    """Pantry read/update failed."""

    pass
