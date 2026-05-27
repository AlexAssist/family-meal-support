"""Project-specific exceptions."""


class MealSupportError(Exception):
    """Base for all project errors."""

    pass


class RecipeNotFoundError(MealSupportError):
    """Recipe not found in the store."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Recipe not found: {name}")


class MultipleCandidatesError(MealSupportError):
    """Multiple recipes match the search term."""

    def __init__(self, name: str, candidates: list[str]) -> None:
        self.name = name
        self.candidates = candidates
        super().__init__(f"Multiple recipes match '{name}': {', '.join(candidates)}")


class SheetSyncError(MealSupportError):
    """Google Sheets read/write failed."""

    def __init__(self, operation: str, details: str) -> None:
        self.operation = operation
        self.details = details
        super().__init__(f"Sheet {operation} failed: {details}")


class PantryError(MealSupportError):
    """Pantry read/update failed."""

    pass
