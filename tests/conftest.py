"""Shared test fixtures."""
import sys
from pathlib import Path

# Add src/ to path so tests can import meal_plan, obsidian, etc.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
