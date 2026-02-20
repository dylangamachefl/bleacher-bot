"""
main.py — Bleacher Bot entry point.

Orchestrates the full pipeline:
  1. Load config
  2. Scrape all three data sources
  3. Build newsletter via parallel LLM calls
  4. Deliver via email (or print if DRY_RUN=true)
"""

import logging
import sys
from datetime import datetime

# Configure logging before any imports that use it
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bleacher-bot")

from src.config import TEAM, DRY_RUN
from src.scrape import fetch_general_news, fetch_reddit_sentiment, fetch_offseason_news
from src.compose import build_newsletter
from src.deliver import send_email


def main() -> int:
    team_name = TEAM["name"]
    logger.info(f"🏈 Bleacher Bot starting — team: {team_name}")
    logger.info(f"   DRY_RUN={DRY_RUN}")

    # ── Step 1: Scrape ─────────────────────────────────────────────────────
    logger.info("Scraping data sources...")
    try:
        general_news = fetch_general_news()
        logger.info("  ✓ General news fetched")
    except Exception as e:
        logger.error(f"  ✗ General news failed: {e}")
        general_news = "Could not retrieve general news this week."

    try:
        reddit_sentiment = fetch_reddit_sentiment()
        logger.info("  ✓ Reddit sentiment fetched")
    except Exception as e:
        logger.error(f"  ✗ Reddit fetch failed: {e}")
        reddit_sentiment = "Could not retrieve Reddit sentiment this week."

    try:
        offseason_news = fetch_offseason_news()
        logger.info("  ✓ Offseason/seasonal news fetched")
    except Exception as e:
        logger.error(f"  ✗ Offseason news failed: {e}")
        offseason_news = "Could not retrieve offseason news this week."

    # ── Step 2: Compose ────────────────────────────────────────────────────
    logger.info("Composing newsletter (3 parallel LLM calls)...")
    try:
        newsletter = build_newsletter(
            general_news=general_news,
            reddit_sentiment=reddit_sentiment,
            offseason_news=offseason_news,
        )
        logger.info("  ✓ Newsletter composed")
    except Exception as e:
        logger.error(f"Newsletter composition failed: {e}")
        return 1

    # ── Step 3: Deliver ────────────────────────────────────────────────────
    date_str = datetime.now().strftime("%B %d, %Y")
    subject = f"🐬 {team_name} Weekly Brief — {date_str}"

    logger.info("Delivering newsletter...")
    try:
        send_email(subject=subject, markdown_body=newsletter)
    except Exception as e:
        logger.error(f"Email delivery failed: {e}")
        return 1

    logger.info("✅ Bleacher Bot finished successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
