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


class RedditPost(TypedDict):
    title:    str
    author:   str
    url:      str
    age:      str
    selftext: str         # may be empty for link posts
    comments: list[str]   # top comment bodies; empty if fetch failed or blocked
    is_media: bool        # True for image/video/meme posts — skip LLM summarization


class RedditData(TypedDict):
    posts_text:   str              # flat text blob for LLM context
    top_comments: list[RedditComment]  # kept for fallback rendering
    posts:        list[RedditPost]     # structured posts for per-card rendering


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


# Reddit's public JSON API requires a descriptive User-Agent; generic ones get 429'd.
_REDDIT_HEADERS = {
    "User-Agent": "python:bleacher-bot:v1.0.0 (by /u/bleacherbotdev)",
    "Accept":     "application/json",
}


_MEDIA_DOMAINS = (
    "i.redd.it", "v.redd.it", "preview.redd.it",
    "i.imgur.com", "imgur.com/", "gfycat.com", "redgifs.com", "giphy.com",
)
_MEDIA_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".mp4", ".webm", ".gifv", ".mov")

_JSON_MEDIA_HINTS = {"image", "video", "rich:video", "hosted:video"}


def _is_media_rss(raw_summary: str, entry) -> bool:
    """
    Detect image/video/meme posts using only data available from the RSS feed.
    Checks the raw HTML summary and any links attached to the entry for known
    media domains and file extensions. Works in CI — no extra API calls needed.
    """
    lower = raw_summary.lower()
    if any(domain in lower for domain in _MEDIA_DOMAINS):
        return True
    for link in entry.get("links", []):
        href = link.get("href", "").lower()
        if any(domain in href for domain in _MEDIA_DOMAINS):
            return True
        if any(href.endswith(ext) for ext in _MEDIA_EXTENSIONS):
            return True
    return False


def _fetch_post_comments(post_url: str, limit: int = REDDIT_COMMENT_LIMIT) -> tuple[list[str], bool | None]:
    """
    Fetch the top comments for one Reddit post via the public JSON API.
    Extracts the post ID from the RSS entry URL and hits:
      https://www.reddit.com/comments/<id>.json?sort=top

    Returns (comments, is_media_from_json):
      - comments:           list of top comment body strings (up to `limit`)
      - is_media_from_json: True/False from post_hint; None if fetch failed
    Returns ([], None) silently on any error — expected on GitHub Actions
    where Reddit's JSON API is blocked from cloud IP ranges.
    """
    import re
    match = re.search(r"/comments/([a-z0-9]+)/", post_url)
    if not match:
        return [], None
    post_id  = match.group(1)
    json_url = f"https://www.reddit.com/comments/{post_id}.json?sort=top&limit={limit * 3}"

    try:
        resp = requests.get(json_url, headers=_REDDIT_HEADERS, timeout=8)
        resp.raise_for_status()
        data = resp.json()   # [post_listing, comment_listing]
        if len(data) < 2:
            return [], None

        # Extract post_hint from the post listing for reliable media detection
        post_data      = data[0]["data"]["children"][0]["data"] if data[0]["data"]["children"] else {}
        post_hint      = post_data.get("post_hint", "")
        is_media       = post_hint in _JSON_MEDIA_HINTS

        comments: list[str] = []
        for child in data[1]["data"]["children"]:
            if child.get("kind") != "t1":          # skip "more" items
                continue
            cdata  = child.get("data", {})
            body   = cdata.get("body", "").strip()
            author = cdata.get("author", "")
            if body in ("[deleted]", "[removed]", "") or author.lower() == "automoderator":
                continue
            comments.append(body[:300])
            if len(comments) >= limit:
                break
        return comments, is_media
    except Exception as exc:
        logger.debug(f"Comment fetch skipped for {post_url}: {exc}")
        return [], None


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
        return RedditData(posts_text="Could not retrieve Reddit data this week.", top_comments=[], posts=[])

    # Filter out AutoModerator/bot posts and take up to the limit
    entries = [
        e for e in feed.entries
        if e.get("author", "").lower() not in ("/u/automoderator", "automoderator")
    ][:REDDIT_POST_LIMIT]

    if not entries:
        logger.warning(f"No Reddit RSS entries found for r/{subreddit}")
        return RedditData(posts_text="No Reddit activity found this week.", top_comments=[], posts=[])

    text_lines: list[str]           = []
    top_posts:  list[RedditComment] = []
    posts:      list[RedditPost]    = []

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

        # Structured post for per-card rendering (comments + is_media refined below)
        posts.append(RedditPost(
            title=title,
            author=author,
            url=link,
            age=age,
            selftext=snippet,
            comments=[],
            is_media=_is_media_rss(raw_summary, entry),
        ))

        # Keep legacy RedditComment list as fallback
        take_text = snippet if snippet else title
        top_posts.append(RedditComment(
            user=author,
            text=take_text[:280],
            upvotes=0,          # RSS doesn't expose upvote counts
            post=title,
        ))

    # Prefer posts with selftext for the fallback hot-takes UI
    top_posts.sort(key=lambda p: len(p["text"]), reverse=True)
    top_posts = top_posts[:TOP_COMMENTS_TARGET]

    # ── Parallel comment fetch ─────────────────────────────────────────────
    # Fire one request per post concurrently. Silently skips posts whose URLs
    # return errors (expected on GitHub Actions where Reddit's JSON API is blocked).
    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=4) as pool:
        future_to_idx = {
            pool.submit(_fetch_post_comments, posts[i]["url"]): i
            for i in range(len(posts))
            if posts[i]["url"]
        }
        fetched, skipped, media_filtered = 0, 0, 0
        for future in as_completed(future_to_idx):
            idx                  = future_to_idx[future]
            comments, is_media_json = future.result()   # never raises

            posts[idx]["comments"] = comments

            # JSON post_hint is authoritative — override the RSS-based guess when available
            if is_media_json is not None:
                posts[idx]["is_media"] = is_media_json

            if posts[idx]["is_media"]:
                media_filtered += 1
            elif comments:
                fetched += 1
                # Append comment text to the flat LLM context blob too
                text_lines.append(f"  Top comments for: {posts[idx]['title']}")
                for c in comments:
                    text_lines.append(f"    > {c[:200]}")
                text_lines.append("")
            else:
                skipped += 1

    logger.info(
        f"Reddit RSS: {len(entries)} posts — "
        f"comments fetched: {fetched}, skipped (blocked/link-only): {skipped}, "
        f"media posts filtered: {media_filtered}"
    )

    return RedditData(posts_text="\n".join(text_lines), top_comments=top_posts, posts=posts)


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
