"""
scrape.py — Public data scrapers: Google News RSS and Reddit JSON API.

Each function returns a structured dict rather than a flat text blob so
downstream code (compose.py, deliver.py) can render individual fields
directly into the report layout.
"""

import feedparser
import requests
import logging
from datetime import datetime, timezone
from typing import TypedDict

from src.config import TEAM, get_seasonal_keyword

logger = logging.getLogger(__name__)

# ── Limits ────────────────────────────────────────────────────────────────────
NEWS_ITEM_LIMIT      = 6
REDDIT_POST_LIMIT    = 8   # fetch more so we have better comment coverage
REDDIT_COMMENT_LIMIT = 3
TOP_COMMENTS_TARGET  = 5   # how many hot-take comments to surface in final output


# ── TypedDicts (document the shape each function returns) ─────────────────────

class NewsItem(TypedDict):
    title:  str
    source: str
    url:    str
    date:   str   # human-readable, e.g. "2 hrs ago" or "Feb 20"


class RedditComment(TypedDict):
    user:    str
    text:    str
    upvotes: int
    post:    str   # title of the parent post, for attribution in the UI


class RedditData(TypedDict):
    posts_text:   str              # flat text blob for LLM context
    top_comments: list[RedditComment]  # structured comments for direct rendering


class NewsData(TypedDict):
    items:     list[NewsItem]
    text_blob: str   # flat text for LLM context


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_rss_date(entry) -> str:
    """Return a human-readable date string from an RSS entry."""
    try:
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if published:
            dt = datetime(*published[:6], tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            delta_hours = (now - dt).total_seconds() / 3600
            if delta_hours < 1:
                return "< 1 hr ago"
            elif delta_hours < 24:
                return f"{int(delta_hours)} hrs ago"
            elif delta_hours < 48:
                return "Yesterday"
            else:
                return dt.strftime("%b %d")
    except Exception:
        pass
    return ""


def _parse_source(entry) -> str:
    """
    Extract the outlet name from a Google News RSS entry.
    Google News appends ' - Outlet Name' to every title.
    """
    title = entry.get("title", "")
    if " - " in title:
        return title.rsplit(" - ", 1)[-1].strip()
    source_tag = entry.get("source", {})
    if isinstance(source_tag, dict):
        return source_tag.get("title", "").strip()
    return "News"


def _clean_title(entry) -> str:
    """Strip the trailing ' - Outlet Name' suffix Google News adds."""
    title = entry.get("title", "").strip()
    if " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title


def _age_label(created_utc: float) -> str:
    """Return a human-readable age for a Reddit post."""
    now = datetime.now(timezone.utc)
    age_hours = (now - datetime.fromtimestamp(created_utc, tz=timezone.utc)).total_seconds() / 3600
    if age_hours < 1:
        return "< 1 hour ago"
    elif age_hours < 24:
        return f"{int(age_hours)}h ago"
    else:
        return f"{int(age_hours / 24)}d ago"


# ── Public scrapers ───────────────────────────────────────────────────────────

def fetch_general_news() -> NewsData:
    """
    Scrapes Google News RSS for general team headlines.

    Returns a NewsData dict containing:
      - items:     list of NewsItem dicts for direct rendering in the report
      - text_blob: flat text for feeding into the LLM as context
    """
    query = TEAM["news_query"]
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    logger.info(f"Fetching general news: {url}")

    feed = feedparser.parse(url)
    entries = feed.entries[:NEWS_ITEM_LIMIT]

    if not entries:
        logger.warning("No general news entries found.")
        return NewsData(items=[], text_blob="No news articles found for this team this week.")

    items: list[NewsItem] = []
    text_lines: list[str] = []

    for entry in entries:
        title  = _clean_title(entry)
        source = _parse_source(entry)
        link   = entry.get("link", "")
        date   = _parse_rss_date(entry)

        items.append(NewsItem(title=title, source=source, url=link, date=date))
        text_lines.append(f"• [{source}] {title} ({date})")

    return NewsData(items=items, text_blob="\n".join(text_lines))


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode common HTML entities from a string."""
    import re
    import html as html_module
    # Remove all HTML tags
    clean = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities (&#32; &amp; &quot; etc.)
    clean = html_module.unescape(clean)
    return clean.strip()


def fetch_reddit_data() -> RedditData:
    """
    Scrapes hot posts from the team subreddit via the public RSS feed.

    Reddit's RSS feed (https://www.reddit.com/r/<sub>/hot.rss) requires no
    credentials and works from CI environments, unlike the JSON API which is
    blocked on cloud IP ranges.

    The RSS entries contain post titles, authors, selftext snippets (in the
    summary field), publication timestamps, and links. We surface the most
    discussion-worthy posts as "Top Community Takes" in the report.

    Returns a RedditData dict containing:
      - posts_text:   flat text blob for LLM context
      - top_comments: list of RedditComment-shaped dicts (one per notable post)
                      for direct rendering in the sentiment card
    """
    subreddit = TEAM["subreddit"]
    url = f"https://www.reddit.com/r/{subreddit}/hot.rss?limit={REDDIT_POST_LIMIT}"
    logger.info(f"Fetching Reddit RSS from r/{subreddit}")

    try:
        feed = feedparser.parse(url)
    except Exception as e:
        logger.error(f"Reddit RSS parse failed: {e}")
        return RedditData(posts_text="Could not retrieve Reddit data this week.", top_comments=[])

    # Filter out AutoModerator/bot posts and take up to the limit
    entries = [
        e for e in feed.entries
        if e.get("author", "").lower() not in ("/u/automoderator", "automoderator")
    ][:REDDIT_POST_LIMIT]

    if not entries:
        logger.warning(f"No Reddit RSS entries found for r/{subreddit}")
        return RedditData(posts_text="No Reddit activity found this week.", top_comments=[])

    text_lines: list[str]         = []
    top_posts:  list[RedditComment] = []

    for entry in entries:
        title  = entry.get("title", "").strip()
        author = entry.get("author", "u/unknown").strip()
        link   = entry.get("link", "")
        age    = _parse_rss_date(entry)

        # The RSS summary is an HTML blob — extract readable text from it
        raw_summary = entry.get("summary", "")
        summary     = _strip_html(raw_summary)
        # Strip Reddit navigation artifacts present in all summaries
        for artifact in ("[link]", "[comments]", "submitted by", "[removed]", "[deleted]"):
            summary = summary.replace(artifact, "")
        # Collapse whitespace
        summary = " ".join(summary.split())
        # Link posts (no selftext) leave only the author handle after stripping.
        # Detect these: if the only word that isn't a /u/ mention is gone, discard.
        words_without_usernames = [
            w for w in summary.split() if not w.startswith("/u/") and not w.startswith("u/")
        ]
        snippet = summary[:300] if len(words_without_usernames) > 3 else ""

        text_lines.append(f"### {title} ({age})")
        if snippet:
            text_lines.append(f"  {snippet}")
        text_lines.append(f"  Author: {author}")
        text_lines.append("")

        # Surface posts that have substantive self-text as "community takes"
        # Posts without selftext (link posts) use the title as the take text
        take_text = snippet if snippet else title
        top_posts.append(RedditComment(
            user=author,
            text=take_text[:280],
            upvotes=0,          # RSS doesn't expose upvote counts
            post=title,
        ))

    # Prefer posts with selftext (more discussion-worthy) for the hot takes UI
    # Posts with a snippet come first; trim to target count
    top_posts.sort(key=lambda p: len(p["text"]), reverse=True)
    top_posts = top_posts[:TOP_COMMENTS_TARGET]

    logger.info(f"Reddit RSS: {len(entries)} posts fetched, {len(top_posts)} selected for hot takes")

    return RedditData(posts_text="\n".join(text_lines), top_comments=top_posts)


def fetch_offseason_news() -> NewsData:
    """
    Scrapes Google News RSS with a seasonally-adjusted keyword for
    front-office, draft, and roster-move coverage.

    Returns the same NewsData shape as fetch_general_news().
    """
    base_query   = TEAM["news_query"]
    seasonal_kw  = get_seasonal_keyword()
    seasonal_enc = seasonal_kw.replace(" ", "+").replace("/", "+")
    query        = f"{base_query}+{seasonal_enc}"
    url          = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    logger.info(f"Fetching offseason/seasonal news: {url}")

    feed    = feedparser.parse(url)
    entries = feed.entries[:NEWS_ITEM_LIMIT]

    if not entries:
        logger.warning("No offseason news entries found.")
        return NewsData(items=[], text_blob="No offseason news found for this team this week.")

    items:      list[NewsItem] = []
    text_lines: list[str]     = []

    for entry in entries:
        title  = _clean_title(entry)
        source = _parse_source(entry)
        link   = entry.get("link", "")
        date   = _parse_rss_date(entry)

        items.append(NewsItem(title=title, source=source, url=link, date=date))
        text_lines.append(f"• [{source}] {title} ({date})")

    return NewsData(items=items, text_blob="\n".join(text_lines))
