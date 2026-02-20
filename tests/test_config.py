"""
tests/test_config.py — Smoke tests for config helpers.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config import TEAM, get_seasonal_keyword
from unittest.mock import patch
import datetime


def test_team_has_required_keys():
    assert "name" in TEAM
    assert "subreddit" in TEAM
    assert "news_query" in TEAM


def test_seasonal_keyword_all_months():
    """Every month must return a non-empty string."""
    for month in range(1, 13):
        fake_date = datetime.datetime(2025, month, 15)
        with patch("src.config.datetime") as mock_dt:
            mock_dt.now.return_value = fake_date
            kw = get_seasonal_keyword()
            assert isinstance(kw, str) and len(kw) > 0, f"Empty keyword for month {month}"


def test_seasonal_keyword_february():
    """February should reference Free Agency or Combine."""
    fake_date = datetime.datetime(2025, 2, 1)
    with patch("src.config.datetime") as mock_dt:
        mock_dt.now.return_value = fake_date
        kw = get_seasonal_keyword()
        assert "Free Agency" in kw or "Combine" in kw
