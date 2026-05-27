"""Tests for recipe saver module."""
import pytest
from pathlib import Path
import tempfile

from obsidian.recipe_saver import save_recipe, RecipeSaveError
from recipes.discovery import RecipeCandidate


class TestRecipeSaver:
    def test_save_recipe_creates_file(self, monkeypatch):
        """save_recipe creates a .md file in the meals directory."""
        mock_html = """
        <html><head><script type="application/ld+json">
        {"@type":"Recipe","name":"Test Pasta","recipeIngredient":["pasta","sauce"]}
        </script></head></html>
        """
        monkeypatch.setattr("obsidian.recipe_saver._fetch_page", lambda url: mock_html)

        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            candidate = RecipeCandidate(
                name="Test Pasta",
                description="A test pasta recipe",
                source_url="https://example.com/test-pasta",
            )
            recipe = save_recipe(candidate, vault)

            # File should exist
            meals_dir = vault / "reference" / "meal-planning" / "meals"
            assert meals_dir.exists()
            files = list(meals_dir.glob("*.md"))
            assert len(files) == 1

            # Recipe object should be correct
            assert recipe.name == "Test Pasta"
            assert recipe.link == "https://example.com/test-pasta"

    def test_save_recipe_handles_jsonld(self, monkeypatch):
        """Recipe with JSON-LD has ingredients and nutrition parsed correctly."""
        mock_html = """
        <html><head>
        <script type="application/ld+json">
        {
            "@type": "Recipe",
            "name": "Salmon Pasta",
            "recipeIngredient": ["1 lb salmon", "8 oz pasta", "1 cup broccoli"],
            "nutrition": {
                "calories": "542 kcal",
                "proteinContent": "34g",
                "carbohydContent": "53g",
                "fatContent": "22g"
            }
        }
        </script>
        </head></html>
        """
        monkeypatch.setattr("obsidian.recipe_saver._fetch_page", lambda url: mock_html)

        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            candidate = RecipeCandidate(
                name="Salmon Pasta",
                description="Baked salmon with pasta",
                source_url="https://example.com/salmon-pasta",
            )
            recipe = save_recipe(candidate, vault)

            assert recipe.name == "Salmon Pasta"
            assert len(recipe.ingredients) == 3
            assert recipe.calories == 542
            assert recipe.protein_g == 34.0
            assert recipe.carbs_g == 53.0
            assert recipe.fat_g == 22.0

    def test_save_recipe_fallback_on_no_jsonld(self, monkeypatch):
        """When no JSON-LD, uses heuristic parsing."""
        mock_html = "<html><body><p>No structured data here</p></body></html>"
        monkeypatch.setattr("obsidian.recipe_saver._fetch_page", lambda url: mock_html)

        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            candidate = RecipeCandidate(
                name="Simple Salad",
                description="A fresh garden salad",
                source_url="https://example.com/salad",
            )
            recipe = save_recipe(candidate, vault)

            assert recipe.name == "Simple Salad"
            assert recipe.calories is None  # No nutrition parsed

    def test_save_recipe_raises_on_fetch_failure(self, monkeypatch):
        """Fetch failure raises RecipeSaveError."""
        def mock_fetch(url):
            raise Exception("Network error")

        monkeypatch.setattr("obsidian.recipe_saver._fetch_page", mock_fetch)

        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            candidate = RecipeCandidate(
                name="Test",
                description="Test",
                source_url="https://example.com/test",
            )
            with pytest.raises(RecipeSaveError):
                save_recipe(candidate, vault)

    def test_save_recipe_handles_name_collision(self, monkeypatch):
        """When file exists, appends a counter."""
        mock_html = '<script type="application/ld+json">{"@type":"Recipe","name":"Duplicate","recipeIngredient":[]}</script>'
        monkeypatch.setattr("obsidian.recipe_saver._fetch_page", lambda url: mock_html)

        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            meals_dir = vault / "reference" / "meal-planning" / "meals"
            meals_dir.mkdir(parents=True)

            # Create first file
            (meals_dir / "duplicate.md").write_text("# Duplicate\n")

            candidate = RecipeCandidate(
                name="Duplicate",
                description="Test",
                source_url="https://example.com/duplicate",
            )
            recipe = save_recipe(candidate, vault)

            # Both files should exist
            files = list(meals_dir.glob("*.md"))
            assert len(files) == 2
            names = {f.name for f in files}
            assert "duplicate.md" in names
            # New file should have the counter suffix
            counter_files = [f for f in files if f.name.startswith("duplicate-")]
            assert len(counter_files) == 1
            assert counter_files[0].stem.startswith("duplicate-")

    def test_saved_file_format(self, monkeypatch):
        """Saved file follows the existing meals/ format."""
        mock_html = """
        <html><head><script type="application/ld+json">
        {"@type":"Recipe","name":"Test Recipe","recipeIngredient":["1 cup flour","2 eggs","1 tsp salt"]}
        </script></head></html>
        """
        monkeypatch.setattr("obsidian.recipe_saver._fetch_page", lambda url: mock_html)

        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            candidate = RecipeCandidate(
                name="Test Recipe",
                description="Testing the format",
                source_url="https://example.com/test",
            )
            save_recipe(candidate, vault)

            meals_dir = vault / "reference" / "meal-planning" / "meals"
            saved_file = list(meals_dir.glob("*.md"))[0]
            content = saved_file.read_text()

            assert "# Test Recipe" in content
            assert "## Ingredients" in content
            assert "- 1 cup flour" in content
            assert "[Source](https://example.com/test)" in content