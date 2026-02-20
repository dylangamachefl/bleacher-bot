"""
main.py — Bleacher Bot entry point.

Pipeline:
  1. Scrape  — fetch structured data from Google News RSS + Reddit
  2. Compose — single LLM call produces JSON analysis (summaries, sentiment, war room)
  3. Render  — JSON + scraper data → self-contained HTML dashboard
  4. Deliver — send HTML as email attachment (or write preview file in DRY_RUN)
"""

import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bleacher-bot")

from src.config import TEAM, DRY_RUN
from src.scrape import fetch_general_news, fetch_reddit_data, fetch_offseason_news
from src.compose import build_report
from src.deliver import render_report, send_email


def main() -> int:
    team_name = TEAM["name"]
    logger.info(f"🏈 Bleacher Bot starting — team: {team_name}")
    logger.info(f"   DRY_RUN={DRY_RUN}")

    # ── Step 1: Scrape ─────────────────────────────────────────────────────
    logger.info("Scraping data sources...")

    try:
        general_news = fetch_general_news()
        logger.info(f"  ✓ General news — {len(general_news['items'])} items")
    except Exception as e:
        logger.error(f"  ✗ General news failed: {e}")
        general_news = {"items": [], "text_blob": "Could not retrieve general news this week."}

    try:
        reddit_data = fetch_reddit_data()
        logger.info(f"  ✓ Reddit — {len(reddit_data['top_comments'])} top comments collected")
    except Exception as e:
        logger.error(f"  ✗ Reddit fetch failed: {e}")
        reddit_data = {"posts_text": "Could not retrieve Reddit data this week.", "top_comments": []}

    try:
        offseason_news = fetch_offseason_news()
        logger.info(f"  ✓ Offseason news — {len(offseason_news['items'])} items")
    except Exception as e:
        logger.error(f"  ✗ Offseason news failed: {e}")
        offseason_news = {"items": [], "text_blob": "Could not retrieve offseason news this week."}

    # ── Step 2: Compose (single LLM call → ReportData) ────────────────────
    logger.info("Composing report (LLM analysis)...")
    try:
        report = build_report(
            general_news=general_news,
            reddit_data=reddit_data,
            offseason_news=offseason_news,
        )
        logger.info("  ✓ Report data composed")
    except Exception as e:
        logger.error(f"Report composition failed: {e}")
        return 1

    # ── Step 3: Render (data → HTML) ───────────────────────────────────────
    logger.info("Rendering HTML report...")
    try:
        html = render_report(
            report=report,
            general_news=general_news,
            reddit_data=reddit_data,
            offseason_news=offseason_news,
        )
        logger.info("  ✓ HTML rendered")
    except Exception as e:
        logger.error(f"HTML rendering failed: {e}")
        return 1

    # ── Step 4: Deliver ────────────────────────────────────────────────────
    date_str = datetime.now().strftime("%B %d, %Y")
    subject  = f"🐬 {team_name} Weekly Brief — {date_str}"

    logger.info("Delivering report...")
    try:
        send_email(subject=subject, html=html)
    except Exception as e:
        logger.error(f"Email delivery failed: {e}")
        return 1

    logger.info("✅ Bleacher Bot finished successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
