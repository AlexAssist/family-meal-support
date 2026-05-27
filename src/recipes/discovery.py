"""Recipe discovery — web search + candidate ranking.

Public interface:
    discover_recipe(name: str) -> list[RecipeCandidate]
        Searches the web for the recipe name, returns up to 3 ranked candidates.
        Returns empty list on complete failure (caller handles gracefully).

Private internals (not exposed to callers):
    - _search_web() — raw search API call
    - _rank_candidates() — relevance + quality scoring
    - _parse_candidates() — extract candidates from search results
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import date

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
    """
    raw_results = _search_web(name)
    if not raw_results:
        return []

    candidates = _parse_candidates(raw_results)
    if not candidates:
        return []

    return _rank_candidates(candidates, name)


# -------------------------------------------------------------------
# Private — web search
# -------------------------------------------------------------------

def _search_web(name: str) -> list[dict]:
    """Perform a web search and return raw result dicts.

    Uses DuckDuckGo HTML (no API key required).
    Returns list of dicts with keys: title, url, description.
    """
    try:
        import requests

        query = urllib.parse.quote(name)
        url = f"https://duckduckgo.com/html/?q={query}+recipe"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        return _parse_ddg_html(resp.text)
    except Exception:
        return []


def _parse_ddg_html(html: str) -> list[dict]:
    """Parse DuckDuckGo HTML results page into structured dicts."""
    results: list[dict] = []

    # Each result is in a div with class "result"
    result_blocks = re.findall(r'<div class="result[^"]*">(.*?)</div>\s*</div>', html, re.DOTALL)
    for block in result_blocks[:10]:
        title_match = re.search(r'<a class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
        snippet_match = re.search(r'<a class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)

        if not title_match:
            continue

        url = title_match.group(1).strip()
        title_raw = title_match.group(2).strip()
        # Strip any HTML tags from title
        title = re.sub(r'<[^>]+>', '', title_raw)

        description = ""
        if snippet_match:
            description = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()

        # Skip non-recipe sites that are clearly not food
        skip_patterns = [
            "wikipedia.org",
            "twitter.com",
            "x.com",
            "instagram.com",
            "facebook.com",
            "youtube.com",
            "pinterest.com",
        ]
        if any(p in url.lower() for p in skip_patterns):
            continue

        results.append({
            "title": title,
            "url": url,
            "description": description,
        })

    return results


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