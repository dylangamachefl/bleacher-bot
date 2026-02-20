"""
config.py — Team configuration and seasonal keyword logic.
"""

import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Team Configuration ──────────────────────────────────────────────────────
# Override any of these via GitHub Secrets / .env
TEAM = {
    "name": os.getenv("TEAM_NAME", "Miami Dolphins"),
    "subreddit": os.getenv("TEAM_SUBREDDIT", "miamidolphins"),
    # Google News RSS query — keep concise for best results
    "news_query": os.getenv("TEAM_NEWS_QUERY", "Miami+Dolphins+NFL"),
}

# ── API Keys ────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Reddit — no credentials needed; uses public JSON API

GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
# Send to yourself by default
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", GMAIL_USER)

# ── Flags ────────────────────────────────────────────────────────────────────
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"


# ── Seasonal Keyword Helper ──────────────────────────────────────────────────
def get_seasonal_keyword() -> str:
    """
    Returns the appropriate offseason/season keyword for the RSS query
    based on the current month.
    """
    month = datetime.now().month

    season_map = {
        1: "Playoffs OR Super Bowl",           # January
        2: "Free Agency OR Combine",           # February
        3: "Free Agency OR Signing",           # March
        4: "Mock Draft OR NFL Draft",          # April
        5: "NFL Draft OR Undrafted",           # May
        6: "OTAs OR Offseason",                # June
        7: "Training Camp OR Roster",          # July
        8: "Preseason OR Depth Chart",         # August
        9: "Week 1 OR Season Opener",          # September
        10: "Standings OR Injury Report",      # October
        11: "Playoff Race OR Trade Deadline",  # November
        12: "Playoff Push OR Wild Card",       # December
    }

    return season_map.get(month, "NFL Season")
