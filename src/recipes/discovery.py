"""Recipe discovery — web search + candidate ranking.

Public interface:
    discover_recipe(name: str) -> list[RecipeCandidate]
        Searches the web for the recipe name, returns up to 3 ranked candidates.
        Returns empty list on complete failure (no network, etc.).

    web_search_discovery(name: str) -> list[dict]
        Performs a live Tavily web search for the recipe name.
        Returns list of dicts with keys: title, url, description.
        Calls Tavily API directly using the key from openclaw.json config.

Private internals (not exposed to callers):
    - _load_tavily_key() — load API key from openclaw.json
    - _rank_candidates() — relevance + quality scoring
    - _parse_candidates() — extract candidates from search results
"""
from __future__ import annotations

import json
import os
import re
import requests
from dataclasses import dataclass
from pathlib import Path

# Type for a discovered recipe candidate
@dataclass(frozen=True)
class RecipeCandidate:
    """A candidate recipe from web search."""

    name: str
    description: str
    source_url: str
    score: float = 0.0


# -------------------------------------------------------------------
# Public interface
# -------------------------------------------------------------------

def discover_recipe(name: str) -> list[RecipeCandidate]:
    """Search the web for recipe candidates matching `name`.

    Returns up to 3 ranked candidates. Returns empty list if search fails
    completely (no network, all results rejected, etc.).

    Tries live Tavily search first (via web_search_discovery), then falls
    back to any cached results from a parent agent, then returns empty.
    """
    # Try live search first
    raw_results = web_search_discovery(name)

    if not raw_results:
        # Fall back to parent-agent cache (set_search_cache)
        raw_results = _search_cache.get(name.lower().strip(), [])

    if not raw_results:
        return []

    candidates = _parse_candidates(raw_results)
    if not candidates:
        return []

    return _rank_candidates(candidates, name)


def web_search_discovery(name: str) -> list[dict]:
    """Perform a live Tavily web search for recipe candidates.

    Loads the Tavily API key from ~/.openclaw/openclaw.json and calls
    the Tavily Search API directly.

    Returns a list of dicts with keys: title, url, description.
    Returns empty list on failure (network error, API error, etc.).
    """
    api_key = _load_tavily_key()
    if not api_key:
        return []

    query = f"{name} recipe"
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={"query": query, "api_key": api_key, "max_results": 5},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        if response.status_code != 200:
            return []
        data = response.json()
        results = data.get("results", [])
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("content", r.get("snippet", "")),
            }
            for r in results
        ]
    except Exception:
        return []


def _load_tavily_key() -> str | None:
    """Load Tavily API key from openclaw.json config.

    Searches ~/.openclaw/openclaw.json under
    plugins.entries.tavily.config.webSearch.apiKey.

    Returns None if not found or not readable.
    """
    config_path = Path.home() / ".openclaw" / "openclaw.json"
    try:
        data = json.loads(config_path.read_text())
        entries = data.get("plugins", {}).get("entries", {})
        tavily_cfg = entries.get("tavily", {}).get("config", {})
        web_search = tavily_cfg.get("webSearch", {})
        return web_search.get("apiKey") or None
    except Exception:
        return None


def set_search_cache(query: str, results: list[dict]) -> None:
    """Inject web search results into the module-level cache.

    Called by the parent agent after running `web_search` so that
    `discover_recipe()` picks up the results without making its own
    network call.

    Args:
        query: The search query (normalized, lowercase).
        results: List of dicts with keys: title, url, description.
    """
    global _search_cache
    _search_cache[query.lower().strip()] = results


_search_cache: dict[str, list[dict]] = {}


# -------------------------------------------------------------------
# Private — parsing
# -------------------------------------------------------------------

def _parse_candidates(raw_results: list[dict]) -> list[RecipeCandidate]:
    """Convert raw search results into RecipeCandidate objects."""
    candidates: list[RecipeCandidate] = []

    for r in raw_results:
        name = r.get("title", "").strip()
        url = r.get("url", "").strip()
        description = r.get("description", "").strip()

        if not name or not url:
            continue

        # Skip results with empty or very short descriptions
        if len(description) < 20:
            continue

        candidates.append(RecipeCandidate(
            name=name,
            description=description,
            source_url=url,
        ))

    return candidates


# -------------------------------------------------------------------
# Private — ranking
# -------------------------------------------------------------------

def _rank_candidates(
    candidates: list[RecipeCandidate],
    query: str,
) -> list[RecipeCandidate]:
    """Rank candidates by relevance and source quality.

    Returns up to 3 best candidates, sorted by score descending.
    """
    query_lower = query.lower()

    ranked = []
    for c in candidates:
        score = c.score

        # Relevance: query words appear in title
        query_words = query_lower.split()
        title_lower = c.name.lower()
        for word in query_words:
            if word in title_lower:
                score += 2.0
            elif word in c.description.lower():
                score += 0.5

        # Quality signals: recipe-specific domains score higher
        quality_domains = [
            "allrecipes.com",
            "food.com",
            "seriouseats.com",
            "epicurious.com",
            "bonappetit.com",
            "cookinglight.com",
            "EatingWell",
            "Sally's Baking",
            "Budget Bytes",
            "Minimalist Baker",
        ]
        for domain in quality_domains:
            if domain.lower() in c.name.lower() or domain.lower() in c.description.lower():
                score += 1.5
            if domain.lower() in c.source_url.lower():
                score += 2.0

        # Penalize very short descriptions (likely low-quality)
        if len(c.description) < 60:
            score -= 1.0

        # Penalize generic/non-food domains
        generic_domains = ["yahoo.com", "bing.com", "google.com"]
        for domain in generic_domains:
            if domain in c.source_url.lower():
                score -= 3.0

        ranked.append(RecipeCandidate(
            name=c.name,
            description=c.description,
            source_url=c.source_url,
            score=score,
        ))

    # Sort by score descending, take top 3
    ranked.sort(key=lambda x: x.score, reverse=True)
    return ranked[:3]