"""
scrape.py — Public data scrapers: Google News RSS and Reddit JSON API.
"""

import feedparser
import requests
import logging

from src.config import (
    TEAM,
    get_seasonal_keyword,
)

logger = logging.getLogger(__name__)

# Number of items to pull from each source
NEWS_ITEM_LIMIT = 6
REDDIT_POST_LIMIT = 5
REDDIT_COMMENT_LIMIT = 3


def fetch_general_news() -> str:
    """
    Scrapes the top Google News RSS headlines for the team.
    Returns a plain-text blob suitable for LLM input.
    """
    query = TEAM["news_query"]
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    logger.info(f"Fetching general news: {url}")

    feed = feedparser.parse(url)
    entries = feed.entries[:NEWS_ITEM_LIMIT]

    if not entries:
        logger.warning("No general news entries found.")
        return "No news articles found for this team this week."

    lines = []
    for entry in entries:
        title = entry.get("title", "").strip()
        summary = entry.get("summary", "").strip()
        lines.append(f"• {title}\n  {summary}")

    return "\n\n".join(lines)


def fetch_reddit_sentiment() -> str:
    """
    Scrapes the top weekly posts and top comments from the team subreddit
    using Reddit's public JSON API — no credentials required.
    Returns a plain-text blob suitable for LLM input.
    """
    subreddit_name = TEAM["subreddit"]
    url = f"https://www.reddit.com/r/{subreddit_name}/top.json?t=week&limit={REDDIT_POST_LIMIT}"
    headers = {"User-Agent": "BleacherBot/1.0 (newsletter automation; read-only)"}
    logger.info(f"Fetching Reddit sentiment from r/{subreddit_name} (public JSON API)")

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"Reddit fetch failed: {e}")
        return "Could not retrieve Reddit sentiment this week."

    posts = data.get("data", {}).get("children", [])

    if not posts:
        logger.warning(f"No Reddit posts found in r/{subreddit_name}")
        return "No Reddit activity found for this team this week."

    lines = []
    for post_wrapper in posts:
        post = post_wrapper.get("data", {})
        title = post.get("title", "").strip()
        score = post.get("score", 0)
        selftext = post.get("selftext", "").strip()

        lines.append(f"### Post: {title} (↑{score})")
        if selftext and len(selftext) > 20:
            lines.append(f"Body: {selftext[:400]}")

        # Fetch top comments for this post
        post_id = post.get("id", "")
        if post_id:
            comments_url = f"https://www.reddit.com/r/{subreddit_name}/comments/{post_id}.json?limit={REDDIT_COMMENT_LIMIT}&sort=top"
            try:
                c_resp = requests.get(comments_url, headers=headers, timeout=10)
                c_resp.raise_for_status()
                c_data = c_resp.json()
                comments = c_data[1].get("data", {}).get("children", [])
                for comment in comments[:REDDIT_COMMENT_LIMIT]:
                    body = comment.get("data", {}).get("body", "").strip().replace("\n", " ")
                    c_score = comment.get("data", {}).get("score", 0)
                    if body and body != "[deleted]":
                        lines.append(f"  └ Comment (↑{c_score}): {body[:300]}")
            except Exception as e:
                logger.warning(f"Could not fetch comments for post {post_id}: {e}")

        lines.append("")

    return "\n".join(lines)



def fetch_offseason_news() -> str:
    """
    Scrapes Google News RSS with a seasonally-adjusted keyword appended,
    giving context on front-office moves, drafts, or upcoming events.
    """
    base_query = TEAM["news_query"]
    seasonal_kw = get_seasonal_keyword()
    # URL-encode the seasonal keyword (replace spaces with +)
    seasonal_encoded = seasonal_kw.replace(" ", "+").replace("/", "+")
    query = f"{base_query}+{seasonal_encoded}"
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    logger.info(f"Fetching offseason/seasonal news: {url}")

    feed = feedparser.parse(url)
    entries = feed.entries[:NEWS_ITEM_LIMIT]

    if not entries:
        logger.warning("No offseason news entries found.")
        return "No offseason or future-looking news found for this team this week."

    lines = []
    for entry in entries:
        title = entry.get("title", "").strip()
        summary = entry.get("summary", "").strip()
        lines.append(f"• {title}\n  {summary}")

    return "\n\n".join(lines)
