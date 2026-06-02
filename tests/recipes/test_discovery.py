"""Tests for recipe discovery module."""
import pytest
from recipes.discovery import (
    RecipeCandidate,
    discover_recipe,
    _rank_candidates,
    _parse_candidates,
)


class TestRecipeCandidate:
    def test_creation(self):
        c = RecipeCandidate(name="Pasta Primavera", description="Classic Italian recipe", source_url="https://example.com")
        assert c.name == "Pasta Primavera"
        assert c.description == "Classic Italian recipe"
        assert c.source_url == "https://example.com"
        assert c.score == 0.0

    def test_immutable(self):
        c = RecipeCandidate(name="Test", description="Test", source_url="https://example.com")
        with pytest.raises(Exception):  # frozen dataclass
            c.name = "Changed"


class TestRankCandidates:
    def test_exact_query_word_match_boosts_score(self):
        candidates = [
            RecipeCandidate(name="Pasta Primavera", description="A great weeknight dinner", source_url="https://allrecipes.com"),
            RecipeCandidate(name="Pasta Salad", description="Cold pasta salad", source_url="https://example.com"),
        ]
        ranked = _rank_candidates(candidates, "pasta")
        assert ranked[0].name == "Pasta Primavera"
        assert ranked[0].score > ranked[1].score

    def test_quality_domain_boosts_score(self):
        candidates = [
            RecipeCandidate(name="Spaghetti", description="Simple pasta", source_url="https://example.com"),
            RecipeCandidate(name="Spaghetti", description="Simple pasta", source_url="https://allrecipes.com"),
        ]
        ranked = _rank_candidates(candidates, "spaghetti")
        # allrecipes.com should rank higher
        assert ranked[0].source_url == "https://allrecipes.com"

    def test_penalizes_short_description(self):
        # Recipe B has a clear title match and long description.
        # Recipe A has only a title match but very short description.
        # B should score higher.
        candidates = [
            RecipeCandidate(name="Chicken Recipe X", description="X", source_url="https://allrecipes.com"),
            RecipeCandidate(name="Best Chicken Recipe", description="A hearty and delicious chicken dinner the whole family will love.", source_url="https://allrecipes.com"),
        ]
        ranked = _rank_candidates(candidates, "chicken")
        assert len(ranked) == 2
        # B has 'chicken' in title + quality domain bonus, A only has 'chicken' in title
        assert ranked[0].name == "Best Chicken Recipe"

    def test_penalizes_generic_domains(self):
        candidates = [
            RecipeCandidate(name="Pasta", description="Test", source_url="https://www.yahoo.com"),
            RecipeCandidate(name="Pasta", description="Test", source_url="https://allrecipes.com"),
        ]
        ranked = _rank_candidates(candidates, "pasta")
        assert ranked[0].source_url == "https://allrecipes.com"

    def test_returns_top_3_only(self):
        candidates = [
            RecipeCandidate(name=f"Recipe {i}", description="A detailed description for testing", source_url=f"https://site{i}.com")
            for i in range(10)
        ]
        ranked = _rank_candidates(candidates, "recipe")
        assert len(ranked) == 3

    def test_ties_broken_by_score(self):
        candidates = [
            RecipeCandidate(name="A", description="Detailed description for testing purposes.", source_url="https://a.com"),
            RecipeCandidate(name="B", description="Detailed description for testing purposes.", source_url="https://b.com"),
        ]
        ranked = _rank_candidates(candidates, "recipe")
        assert len(ranked) == 2


class TestParseCandidates:
    def test_skips_results_without_title_or_url(self):
        raw = [
            {"title": "", "url": "https://example.com", "description": "A description"},
            {"title": "Valid Recipe", "url": "", "description": "A description"},
            {"title": "Valid Recipe", "url": "https://example.com", "description": "Too short"},
        ]
        parsed = _parse_candidates(raw)
        assert len(parsed) == 0

    def test_skips_results_with_short_description(self):
        raw = [
            {"title": "Valid Recipe", "url": "https://example.com", "description": "Short"},
        ]
        parsed = _parse_candidates(raw)
        assert len(parsed) == 0

    def test_keeps_valid_results(self):
        raw = [
            {
                "title": "Pasta Primavera",
                "url": "https://example.com/pasta",
                "description": "A delicious Italian pasta dish with fresh vegetables and a light sauce.",
            }
        ]
        parsed = _parse_candidates(raw)
        assert len(parsed) == 1
        assert parsed[0].name == "Pasta Primavera"


class TestDiscoverRecipeIntegration:
    """Integration tests using mock to simulate network."""

    def test_discover_recipe_with_mocked_search(self, monkeypatch):
        """Test discover_recipe when search returns valid results."""
        mock_results = [
            {
                "title": "Pasta Primavera",
                "url": "https://allrecipes.com/pasta-primavera",
                "description": "A delicious weeknight pasta dish with fresh vegetables.",
            },
            {
                "title": "Easy Pasta Primavera",
                "url": "https://budgetbytes.com/pasta-primavera",
                "description": "Simple and affordable pasta with seasonal vegetables.",
            },
        ]

        def mock_search(name):
            return mock_results

        monkeypatch.setattr("recipes.discovery.web_search_discovery", mock_search)

        candidates = discover_recipe("pasta primavera")
        assert len(candidates) <= 3
        assert all(isinstance(c, RecipeCandidate) for c in candidates)

    def test_discover_recipe_returns_empty_on_search_failure(self, monkeypatch):
        """Test discover_recipe returns empty list when search fails."""
        def mock_search(name):
            return []  # Simulates network failure

        monkeypatch.setattr("recipes.discovery.web_search_discovery", mock_search)

        candidates = discover_recipe("nonexistent recipe xyz")
        assert candidates == []