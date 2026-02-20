"""
compose.py — Parallel LLM calls that assemble the three newsletter sections.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.llm import GeminiClient
from src.config import TEAM

logger = logging.getLogger(__name__)

# ── Section Prompts ──────────────────────────────────────────────────────────

FRONT_PAGE_PROMPT = """You are a hard-hitting NFL sports journalist writing for a weekly newsletter.
Your job is to write a single gripping, dramatic paragraph (150–220 words) that captures
the single biggest storyline or controversy surrounding the {team} this week.
Do NOT use bullet points. Write in a compelling narrative voice that makes the reader want to keep reading.
Open with a punchy declarative sentence that sets the scene."""

WATERCOOLER_PROMPT = """You are the loudest, most passionate {team} fan in the stadium — you live and breathe this team.
Your job is to write a single colorful paragraph (150–220 words) that captures the current emotional state
and vibe of the fanbase based on what fans are actually saying on Reddit.
Be funny. Highlight any overreactions, hot takes, or memes. Use casual, fan-forum language.
Do NOT use bullet points. Write as one flowing, energetic paragraph."""

WAR_ROOM_PROMPT = """You are a sharp NFL front-office analyst writing the "War Room" section of a weekly newsletter.
Your job is to write a single focused paragraph (150–220 words) summarizing the {team}'s
upcoming priorities, roster moves, draft rumors, or future lookahead topics for this week.
Be specific and analytical. If it's the offseason, focus on free agency or draft strategy.
Do NOT use bullet points. Write as one authoritative paragraph."""


# ── Section Builder ──────────────────────────────────────────────────────────

def _build_section(client: GeminiClient, prompt_template: str, content: str) -> str:
    """Formats the prompt for the current team and calls the LLM."""
    prompt = prompt_template.format(team=TEAM["name"])
    return client.generate(system_prompt=prompt, user_content=content)


# ── Newsletter Composer ──────────────────────────────────────────────────────

def build_newsletter(
    general_news: str,
    reddit_sentiment: str,
    offseason_news: str,
) -> str:
    """
    Fires three LLM calls in parallel via ThreadPoolExecutor and stitches
    the results into a single Markdown newsletter document.

    Args:
        general_news:     Output of scrape.fetch_general_news()
        reddit_sentiment: Output of scrape.fetch_reddit_sentiment()
        offseason_news:   Output of scrape.fetch_offseason_news()

    Returns:
        Complete newsletter as a Markdown string.
    """
    client = GeminiClient()
    team_name = TEAM["name"]

    tasks = {
        "front_page": (FRONT_PAGE_PROMPT, general_news),
        "watercooler": (WATERCOOLER_PROMPT, reddit_sentiment),
        "war_room": (WAR_ROOM_PROMPT, offseason_news),
    }

    results = {}

    logger.info("Launching 3 parallel LLM threads...")
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_key = {
            executor.submit(_build_section, client, prompt, content): key
            for key, (prompt, content) in tasks.items()
        }

        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                results[key] = future.result()
                logger.info(f"✓ Section '{key}' complete.")
            except Exception as e:
                logger.error(f"✗ Section '{key}' failed: {e}")
                results[key] = f"*[Section unavailable due to an error: {e}]*"

    # ── Stitch into final Markdown ────────────────────────────────────────
    from datetime import datetime
    date_str = datetime.now().strftime("%B %d, %Y")

    newsletter = f"""# 🐬 {team_name} Weekly Brief
### {date_str}

---

## 📰 The Front Page

{results.get('front_page', '*Unavailable*')}

---

## 🍺 The Watercooler

{results.get('watercooler', '*Unavailable*')}

---

## 🏈 The War Room

{results.get('war_room', '*Unavailable*')}

---

*Bleacher Bot — automated with ❤️ and Gemma 3 27B*
"""

    return newsletter
