"""
compose.py — LLM call that produces the report's analytical content as JSON.

The scrapers already return structured data (news items, reddit comments,
etc.) for direct rendering. This module asks the LLM to produce only the
things it's actually good at: prose summaries, sentiment scoring, and
extracting signal from noisy text.

Pydantic is used exclusively here to validate and coerce the LLM's JSON
output — the one place in the pipeline where we receive untrusted,
uncontrolled data that must match a known schema.
"""

import json
import logging
import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from src.llm import GeminiClient
from src.config import TEAM
from src.scrape import NewsData, RedditData

logger = logging.getLogger(__name__)


# ── Pydantic models for LLM output validation ─────────────────────────────────

class SentimentBreakdown(BaseModel):
    positive: int = 33
    neutral:  int = 34
    negative: int = 33

    @model_validator(mode="after")
    def normalise_to_100(self) -> "SentimentBreakdown":
        """Correct rounding errors so the three values always sum to 100."""
        total = self.positive + self.neutral + self.negative
        if total != 100 and total > 0:
            self.positive = round(self.positive / total * 100)
            self.neutral  = round(self.neutral  / total * 100)
            self.negative = 100 - self.positive - self.neutral
        return self


class WarRoomItem(BaseModel):
    title:   str
    summary: str


class LLMOutput(BaseModel):
    """
    Validated schema for the JSON object returned by the LLM.

    Pydantic handles:
      - Missing fields          → field defaults kick in, no KeyError
      - Wrong types             → automatic coercion where safe ("82" → 82)
      - Out-of-range score      → clamped to [0, 100] by the validator
      - Breakdown not summing   → normalised to 100 by SentimentBreakdown
      - Excess list items       → silently truncated by max_length
    """
    season_note:         str                = "Weekly Report"
    executive_summary:   str                = ""
    sentiment_score:     int                = 50
    sentiment_label:     str                = "Neutral"
    sentiment_trend:     str                = "Stable"
    sentiment_breakdown: SentimentBreakdown = Field(default_factory=SentimentBreakdown)
    sentiment_keywords:  list[str]          = Field(default_factory=list)
    war_room_intro:      str                = ""
    war_room_items:      list[WarRoomItem]  = Field(default_factory=list)

    @field_validator("sentiment_score", mode="before")
    @classmethod
    def clamp_score(cls, v: object) -> int:
        """Coerce to int and clamp to [0, 100] rather than raising on bad LLM output."""
        try:
            return max(0, min(100, int(v)))
        except (TypeError, ValueError):
            return 50

    @model_validator(mode="after")
    def truncate_lists(self) -> "LLMOutput":
        self.sentiment_keywords = self.sentiment_keywords[:6]
        self.war_room_items     = self.war_room_items[:4]
        return self


# ── ReportData — the shape passed to deliver.py ───────────────────────────────
# Kept as a plain TypedDict (not Pydantic) because it is assembled by our own
# code from already-validated sources, so there is nothing to validate.

from typing import TypedDict

class WarRoomItemDict(TypedDict):
    title:   str
    summary: str

class SentimentBreakdownDict(TypedDict):
    positive: int
    neutral:  int
    negative: int

class ReportData(TypedDict):
    team_name:           str
    date:                str
    season_note:         str
    executive_summary:   str
    sentiment_score:     int
    sentiment_label:     str
    sentiment_trend:     str
    sentiment_breakdown: SentimentBreakdownDict
    sentiment_keywords:  list[str]
    war_room_intro:      str
    war_room_items:      list[WarRoomItemDict]


# ── Prompt ────────────────────────────────────────────────────────────────────

ANALYSIS_PROMPT = """\
You are an NFL analyst producing the data payload for a weekly {team} fan intelligence report.

You will be given:
  1. GENERAL NEWS   — recent headlines about the team
  2. REDDIT DATA    — hot posts and top comments from the team subreddit
  3. OFFSEASON NEWS — roster, draft, and front-office headlines

Your job is to analyze this data and return a single JSON object with the following fields.
Return ONLY the JSON object — no markdown fences, no explanation, no extra text.

{{
  "season_note": "<string: one short phrase describing the current NFL calendar moment, e.g. 'NFL Scouting Combine Week'. Base it on the news data.>",

  "executive_summary": "<string: 2–3 sentence paragraph. The single most important thing happening with this team right now, written in a direct journalistic tone. Base it only on the provided data. No hype.>",

  "sentiment_score": <integer 0–100: your overall read of fan mood based on the Reddit data. Use this scale — 0-20: extremely negative/angry, 21-35: frustrated/pessimistic, 36-49: cautious/mixed-negative, 50: perfectly neutral, 51-64: cautious/mixed-positive, 65-79: optimistic/excited, 80-100: euphoric. Most weeks will NOT be 50 — pick the number that best reflects the dominant tone in the posts and comments.>,
  "sentiment_label": "<string: 2–3 word label matching the score, e.g. 'Highly Optimistic', 'Cautiously Pessimistic', 'Frustrated but Hopeful', 'Cautious but Interested'>",
  "sentiment_trend": "<string: brief trend note based on post tone, e.g. '+5 pts vs last week' — if you cannot determine a trend from the data, write 'Stable'>",
  "sentiment_breakdown": {{
    "positive": <integer: estimated % of posts/comments that are positive, must sum to 100 with neutral+negative>,
    "neutral":  <integer>,
    "negative": <integer>
  }},
  "sentiment_keywords": ["<keyword>", "<keyword>", "<keyword>", "<keyword>"],

  "war_room_intro": "<string: one sentence framing the team's main front-office priority this week, based only on the offseason news data.>",
  "war_room_items": [
    {{"title": "<short label>", "summary": "<one sentence drawn from the data>"}},
    {{"title": "<short label>", "summary": "<one sentence drawn from the data>"}}
  ]
}}

Rules:
- Base every field ONLY on the data provided below. Do not invent players, transactions, or events.
- war_room_items: include 2–4 items depending on how much the data supports. Do not pad.
- sentiment_keywords: extract actual topics being discussed (player names, events, themes).
- The JSON must be valid and parseable. Use double quotes for all strings.
- Do not include any text before or after the JSON object.\
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fallback_report(team_name: str) -> ReportData:
    """Returns a minimal valid ReportData when the LLM call or parse fails."""
    return ReportData(
        team_name          = team_name,
        date               = datetime.now().strftime("%B %d, %Y"),
        season_note        = "Weekly Report",
        executive_summary  = "This week's summary could not be generated. Please check back next week.",
        sentiment_score    = 50,
        sentiment_label    = "Unavailable",
        sentiment_trend    = "—",
        sentiment_breakdown= SentimentBreakdownDict(positive=33, neutral=34, negative=33),
        sentiment_keywords = [],
        war_room_intro     = "Front-office data unavailable this week.",
        war_room_items     = [],
    )


def _extract_json(raw: str) -> dict:
    """
    Extract and parse a JSON object from raw LLM output.
    Handles the common case where the model wraps output in markdown fences
    despite being told not to.
    """
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw.strip())
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in LLM output")
    return json.loads(raw[start:end])


# ── Main composer ─────────────────────────────────────────────────────────────

def build_report(
    general_news:   NewsData,
    reddit_data:    RedditData,
    offseason_news: NewsData,
) -> ReportData:
    """
    Calls the LLM once with all three scraped data sources and returns a
    fully populated ReportData dict ready for deliver.render_report().

    The LLM response is validated with Pydantic (LLMOutput) before being
    converted to a plain ReportData TypedDict for the rest of the pipeline.
    """
    client    = GeminiClient()
    team_name = TEAM["name"]

    user_content = (
        f"--- GENERAL NEWS ---\n{general_news['text_blob']}\n\n"
        f"--- REDDIT DATA ---\n{reddit_data['posts_text']}\n\n"
        f"--- OFFSEASON / FRONT-OFFICE NEWS ---\n{offseason_news['text_blob']}\n"
    )

    prompt = ANALYSIS_PROMPT.format(team=team_name)

    logger.info("Sending analysis prompt to LLM...")
    try:
        raw = client.generate(system_prompt=prompt, user_content=user_content)
        logger.debug(f"Raw LLM response:\n{raw}")
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return _fallback_report(team_name)

    try:
        raw_dict = _extract_json(raw)
    except Exception as e:
        logger.error(f"JSON extraction failed: {e}")
        logger.error(f"Raw response was:\n{raw}")
        return _fallback_report(team_name)

    try:
        parsed = LLMOutput.model_validate(raw_dict)
        logger.info("✓ LLM response received and validated.")
    except Exception as e:
        logger.error(f"Pydantic validation failed: {e}")
        logger.error(f"Parsed dict was: {raw_dict}")
        return _fallback_report(team_name)

    logger.info(f"LLM sentiment: score={parsed.sentiment_score}, label='{parsed.sentiment_label}', keywords={parsed.sentiment_keywords}")

    return ReportData(
        team_name          = team_name,
        date               = datetime.now().strftime("%B %d, %Y"),
        season_note        = parsed.season_note,
        executive_summary  = parsed.executive_summary,
        sentiment_score    = parsed.sentiment_score,
        sentiment_label    = parsed.sentiment_label,
        sentiment_trend    = parsed.sentiment_trend,
        sentiment_breakdown= SentimentBreakdownDict(
            positive = parsed.sentiment_breakdown.positive,
            neutral  = parsed.sentiment_breakdown.neutral,
            negative = parsed.sentiment_breakdown.negative,
        ),
        sentiment_keywords = parsed.sentiment_keywords,
        war_room_intro     = parsed.war_room_intro,
        war_room_items     = [
            WarRoomItemDict(title=item.title, summary=item.summary)
            for item in parsed.war_room_items
        ],
    )
