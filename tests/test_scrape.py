"""
tests/test_scrape.py — Live smoke test for Google News RSS scraper.
Requires internet access. Skipped automatically if no network.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.scrape import fetch_general_news, fetch_offseason_news


@pytest.mark.network
def test_fetch_general_news_returns_content():
    """Basic check: scraper returns a non-empty string."""
    result = fetch_general_news()
    assert isinstance(result, str)
    assert len(result) > 50, "Expected meaningful news content"


@pytest.mark.network
def test_fetch_offseason_news_returns_content():
    """Basic check: seasonal scraper returns a non-empty string."""
    result = fetch_offseason_news()
    assert isinstance(result, str)
    assert len(result) > 50, "Expected meaningful offseason content"
