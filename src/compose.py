"""
compose.py — Parallel LLM calls that assemble the three newsletter sections.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.llm import GeminiClient
from src.config import TEAM

logger = logging.getLogger(__name__)

# ── Section Prompts ──────────────────────────────────────────────────────────

FRONT_PAGE_PROMPT = """You are a sports journalist writing the lead story for a weekly {team} newsletter.

Your task: Read the news headlines and summaries provided below. Identify the single most
significant story from that data and write a short news item covering it.

Output format — use exactly this structure:
**[One sentence lede that states the core news clearly and directly.]**

[Two to three sentences of context and detail drawn from the articles. What happened, who is
involved, and why it matters for the team. Stay focused on the one story — do not pivot to
other topics.]

Rules:
- Base your writing ONLY on the articles provided. Do not introduce facts, names, scores,
  or storylines not present in the data below.
- The bolded lede must be a standalone sentence that makes sense on its own.
- Write in a clear, direct journalistic voice. Confident but not sensational.
- Do not begin with "This week" or refer to yourself."""

WATERCOOLER_PROMPT = """You are a writer summarizing fan sentiment for the weekly {team} newsletter.

Your task: Read the Reddit posts and comments provided below. Write a short intro sentence
capturing the overall mood, then pull out 2 to 3 of the most representative or interesting
fan takes as blockquotes.

Output format — use exactly this structure:
[One sentence describing the dominant mood or topic in the community this week.]

> "[Direct quote or close paraphrase of a specific fan comment from the data.]"
> — *[brief descriptor, e.g. "top comment on the injury thread"]*

> "[Direct quote or close paraphrase of a second fan comment from the data.]"
> — *[brief descriptor]*

[Optional: one closing sentence if there is a clear secondary theme worth noting.]

Rules:
- Base your writing ONLY on the posts and comments provided. Every blockquote must come
  from actual content in the data below — do not invent quotes.
- The descriptor after the em dash should identify the post or comment it came from
  (e.g. "reply in the game thread", "top comment on the depth chart post").
- Keep the intro sentence plain and observational. No hype.
- Do not begin with "Reddit is buzzing" or similar generic openers."""

WAR_ROOM_PROMPT = """You are an analyst writing the roster and front-office section of the weekly {team} newsletter.

Your task: Read the news headlines and summaries provided below. Identify the key roster moves,
contract news, injuries, draft talk, or strategic decisions and present them as a brief
framing sentence followed by a short bullet list.

Output format — use exactly this structure:
[One sentence framing what the main front-office theme is this week.]

- **[Item title]:** [One sentence summary of the move or news, drawn from the articles.]
- **[Item title]:** [One sentence summary.]
- **[Item title]:** [One sentence summary.]

Rules:
- Base your writing ONLY on the articles provided. Do not invent transactions, signings,
  or rumors not present in the data below.
- Include 2 to 4 bullet points depending on how much material the data supports. Do not
  pad with generic observations if the data does not support them.
- Each bullet should be self-contained and specific — player name, nature of the move, context.
- Do not begin with "As the offseason" or other generic throat-clearing openers."""


# ── Section Builder ──────────────────────────────────────────────────────────

def _build_section(client: GeminiClient, prompt_template: str, content: str) -> str:
    """Formats the prompt for the current team and calls the LLM."""
    prompt = prompt_template.format(team=TEAM["name"])
    user_turn = (
        "Here is the source data to base your writing on. "
        "Do not use any information outside of what appears below.\n\n"
        f"{content}"
    )
    return client.generate(system_prompt=prompt, user_content=user_turn)


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
