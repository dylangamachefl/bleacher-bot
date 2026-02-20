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


def fetch_reddit_data() -> RedditData:
    """
    Scrapes hot posts and top comments from the team subreddit.

    Returns a RedditData dict containing:
      - posts_text:   flat text blob (post titles + top comments) for LLM context
      - top_comments: list of the highest-upvoted RedditComment dicts across all
                      fetched posts, for direct rendering as hot takes in the report
    """
    subreddit = TEAM["subreddit"]
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={REDDIT_POST_LIMIT}"
    headers = {"User-Agent": "BleacherBot/1.0 (newsletter automation; read-only)"}
    logger.info(f"Fetching Reddit data from r/{subreddit}")

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"Reddit fetch failed: {e}")
        return RedditData(posts_text="Could not retrieve Reddit data this week.", top_comments=[])

    posts = data.get("data", {}).get("children", [])
    posts = [p for p in posts if not p.get("data", {}).get("stickied", False)]

    if not posts:
        logger.warning(f"No Reddit posts found in r/{subreddit}")
        return RedditData(posts_text="No Reddit activity found this week.", top_comments=[])

    all_comments: list[RedditComment] = []
    text_lines:   list[str]           = []

    for post_wrapper in posts[:REDDIT_POST_LIMIT]:
        post  = post_wrapper.get("data", {})
        title = post.get("title", "").strip()
        score = post.get("score", 0)
        age   = _age_label(post.get("created_utc", 0))

        text_lines.append(f"### {title} (↑{score}, {age})")

        selftext = post.get("selftext", "").strip()
        if selftext and len(selftext) > 20:
            text_lines.append(f"Body: {selftext[:300]}")

        post_id = post.get("id", "")
        author  = post.get("author", "u/unknown")

        if post_id:
            comments_url = (
                f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json"
                f"?limit={REDDIT_COMMENT_LIMIT}&sort=top"
            )
            try:
                c_resp = requests.get(comments_url, headers=headers, timeout=10)
                c_resp.raise_for_status()
                c_data = c_resp.json()
                comments = c_data[1].get("data", {}).get("children", [])

                for comment in comments[:REDDIT_COMMENT_LIMIT]:
                    cdata   = comment.get("data", {})
                    body    = cdata.get("body", "").strip().replace("\n", " ")
                    c_score = cdata.get("score", 0)
                    c_user  = cdata.get("author", "u/unknown")

                    if not body or body in ("[deleted]", "[removed]"):
                        continue

                    text_lines.append(f"  └ u/{c_user} (↑{c_score}): {body[:300]}")
                    all_comments.append(RedditComment(
                        user=f"u/{c_user}",
                        text=body[:280],
                        upvotes=c_score,
                        post=title,
                    ))

            except Exception as e:
                logger.warning(f"Could not fetch comments for post {post_id}: {e}")

        text_lines.append("")

    # Sort all collected comments by upvotes, keep the top N for the hot-takes UI
    top_comments = sorted(all_comments, key=lambda c: c["upvotes"], reverse=True)[:TOP_COMMENTS_TARGET]

    return RedditData(posts_text="\n".join(text_lines), top_comments=top_comments)


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
