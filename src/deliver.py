"""
deliver.py — HTML renderer and email delivery.

render_report() consumes the ReportData + raw scraper output and produces
a fully self-contained HTML file that mirrors the two-column dashboard
layout from example.jsx. The file is sent as an email attachment so we
can use full modern CSS without email-client constraints.
"""

import smtplib
import logging
import html as html_lib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from src.config import GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL, DRY_RUN, TEAM
from src.compose import ReportData
from src.scrape import NewsData, RedditData

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


# ── Small HTML helpers ────────────────────────────────────────────────────────

def e(text: str) -> str:
    """HTML-escape a string."""
    return html_lib.escape(str(text))


def impact_color(impact: str) -> str:
    return {"High": "#ef4444", "Medium": "#f59e0b"}.get(impact, "#3b82f6")


def sentiment_color(score: int) -> str:
    if score >= 65:
        return "#22c55e"   # green
    elif score >= 40:
        return "#f59e0b"   # amber
    else:
        return "#ef4444"   # red


# ── Section renderers ─────────────────────────────────────────────────────────

def _render_header(report: ReportData, primary_color: str) -> str:
    return f"""
    <header style="background:{primary_color}; padding:24px 32px; box-shadow:0 2px 8px rgba(0,0,0,0.15);">
      <div style="max-width:1100px; margin:0 auto; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
        <div>
          <h1 style="margin:0; font-family:'Playfair Display',Georgia,serif; font-size:1.9rem; font-weight:700; color:#fff; letter-spacing:-0.3px;">
            Bleacher Bot Weekly
          </h1>
          <p style="margin:4px 0 0; font-size:0.85rem; color:rgba(255,255,255,0.7);">
            Intelligence Report &mdash; {e(report['team_name'])}
          </p>
        </div>
        <div style="text-align:right;">
          <p style="margin:0; font-size:0.7rem; font-weight:600; text-transform:uppercase; letter-spacing:0.1em; color:rgba(255,255,255,0.6);">
            {e(report['season_note'])}
          </p>
          <p style="margin:2px 0 0; font-size:1.1rem; font-weight:600; color:#fff;">
            {e(report['date'])}
          </p>
        </div>
      </div>
    </header>"""


def _render_executive_summary(report: ReportData) -> str:
    return f"""
    <section style="background:#fff; border-radius:12px; border:1px solid #e2e8f0; padding:24px; box-shadow:0 1px 3px rgba(0,0,0,0.06);">
      <h2 style="margin:0 0 14px; font-size:1rem; font-weight:700; display:flex; align-items:center; gap:8px; padding-bottom:12px; border-bottom:1px solid #f1f5f9; color:#0f172a;">
        &#9889; Executive Summary
      </h2>
      <p style="margin:0; color:#475569; line-height:1.75; font-size:0.97rem;">
        {e(report['executive_summary'])}
      </p>
    </section>"""


def _render_sentiment(report: ReportData) -> str:
    score     = report['sentiment_score']
    label     = report['sentiment_label']
    trend     = report['sentiment_trend']
    breakdown = report['sentiment_breakdown']
    keywords  = report['sentiment_keywords']
    sc        = sentiment_color(score)

    keyword_chips = "".join(
        f'<span style="background:#f1f5f9; color:#475569; font-size:0.75rem; padding:4px 10px; border-radius:6px; border:1px solid #e2e8f0;">#{e(kw)}</span>'
        for kw in keywords
    )

    # SVG circular progress
    circumference = 100  # matches stroke-dasharray coordinate system
    svg_progress  = f"""
      <svg width="120" height="120" viewBox="0 0 36 36" style="transform:rotate(-90deg);">
        <path stroke="#f1f5f9" stroke-width="3" fill="none"
          d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"/>
        <path stroke="{sc}" stroke-width="3" fill="none"
          stroke-dasharray="{score},{circumference}"
          stroke-linecap="round"
          d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"/>
      </svg>
      <div style="position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center;">
        <span style="font-size:1.6rem; font-weight:900; color:#0f172a; line-height:1;">{score}</span>
        <span style="font-size:0.65rem; color:#94a3b8;">/100</span>
      </div>"""

    return f"""
    <section style="background:#fff; border-radius:12px; border:1px solid #e2e8f0; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.06);">
      <!-- Section header bar -->
      <div style="background:#1e293b; padding:14px 20px; display:flex; justify-content:space-between; align-items:center;">
        <h2 style="margin:0; font-size:0.95rem; font-weight:700; color:#fff; display:flex; align-items:center; gap:8px;">
          &#128172; r/{e(TEAM['subreddit'])} Sentiment Radar
        </h2>
        <span style="background:rgba(34,197,94,0.15); color:#4ade80; font-size:0.7rem; padding:3px 10px; border-radius:20px; border:1px solid rgba(34,197,94,0.3); font-weight:600;">
          {e(label)}
        </span>
      </div>

      <div style="padding:20px 24px;">
        <!-- Score + breakdown row -->
        <div style="display:flex; gap:32px; align-items:center; padding-bottom:20px; border-bottom:1px solid #f1f5f9; margin-bottom:20px; flex-wrap:wrap;">
          <!-- Circular score -->
          <div style="display:flex; flex-direction:column; align-items:center; gap:8px; flex-shrink:0;">
            <div style="position:relative; width:120px; height:120px;">
              {svg_progress}
            </div>
            <p style="margin:0; font-size:0.75rem; color:{sc}; font-weight:600;">
              &#8599; {e(trend)}
            </p>
          </div>

          <!-- Breakdown bars + keywords -->
          <div style="flex:1; min-width:200px;">
            <div style="margin-bottom:16px;">
              <div style="display:flex; justify-content:space-between; font-size:0.72rem; color:#94a3b8; font-weight:600; margin-bottom:5px;">
                <span>Positive ({breakdown['positive']}%)</span>
                <span>Neutral ({breakdown['neutral']}%)</span>
                <span>Negative ({breakdown['negative']}%)</span>
              </div>
              <div style="display:flex; height:10px; border-radius:20px; overflow:hidden; gap:2px;">
                <div style="background:#22c55e; width:{breakdown['positive']}%;"></div>
                <div style="background:#cbd5e1; width:{breakdown['neutral']}%;"></div>
                <div style="background:#f87171; width:{breakdown['negative']}%;"></div>
              </div>
            </div>
            <div>
              <p style="margin:0 0 8px; font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.1em; color:#94a3b8;">Trending Topics</p>
              <div style="display:flex; flex-wrap:wrap; gap:6px;">
                {keyword_chips}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>"""


def _render_hot_takes(reddit_data: RedditData) -> str:
    comments = reddit_data['top_comments']
    if not comments:
        return ""

    rows = ""
    for c in comments:
        rows += f"""
        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px; display:flex; gap:12px; align-items:flex-start;">
          <div style="display:flex; flex-direction:column; align-items:center; flex-shrink:0; padding-top:2px;">
            <span style="color:#f97316; font-size:1rem;">&#9650;</span>
            <span style="font-size:0.7rem; font-weight:700; color:#64748b; margin-top:2px;">{e(str(c['upvotes']))}</span>
          </div>
          <div style="min-width:0;">
            <p style="margin:0 0 3px; font-size:0.72rem; color:#94a3b8; font-weight:600;">{e(c['user'])}</p>
            <p style="margin:0; font-size:0.85rem; color:#334155; line-height:1.55;">{e(c['text'])}</p>
            <p style="margin:4px 0 0; font-size:0.7rem; color:#cbd5e1; font-style:italic;">{e(c['post'])}</p>
          </div>
        </div>"""

    return f"""
    <section style="background:#fff; border-radius:12px; border:1px solid #e2e8f0; padding:24px; box-shadow:0 1px 3px rgba(0,0,0,0.06);">
      <h2 style="margin:0 0 14px; font-size:1rem; font-weight:700; padding-bottom:12px; border-bottom:1px solid #f1f5f9; color:#0f172a; display:flex; align-items:center; gap:8px;">
        &#128293; Top Community Takes
      </h2>
      <div style="display:flex; flex-direction:column; gap:10px;">
        {rows}
      </div>
    </section>"""


def _render_news_feed(general_news: NewsData, primary_color: str) -> str:
    items = general_news['items']
    if not items:
        return ""

    rows = ""
    for item in items:
        # Assign impact based on position — first two are "High", next two "Medium", rest "Low"
        idx    = items.index(item)
        impact = "High" if idx < 2 else ("Medium" if idx < 4 else "Low")
        ic     = impact_color(impact)
        link   = item.get('url', '')

        title_html = (
            f'<a href="{e(link)}" style="color:#0f172a; text-decoration:none;" target="_blank">{e(item["title"])}</a>'
            if link else e(item["title"])
        )

        rows += f"""
        <div style="display:flex; gap:14px; align-items:flex-start; padding:10px; border-radius:8px; border-left:4px solid {ic}; transition:background 0.15s;"
             onmouseover="this.style.background='#f8fafc'" onmouseout="this.style.background='transparent'">
          <div style="flex:1; min-width:0;">
            <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px; flex-wrap:wrap;">
              <span style="font-size:0.65rem; font-weight:700; background:#f1f5f9; color:#64748b; padding:2px 6px; border-radius:4px; text-transform:uppercase; white-space:nowrap;">{e(item['source'])}</span>
              <span style="font-size:0.72rem; color:#94a3b8;">{e(item['date'])}</span>
            </div>
            <h3 style="margin:0; font-size:0.88rem; font-weight:600; color:#0f172a; line-height:1.4;">{title_html}</h3>
          </div>
        </div>"""

    return f"""
    <section style="background:#fff; border-radius:12px; border:1px solid #e2e8f0; padding:24px; box-shadow:0 1px 3px rgba(0,0,0,0.06);">
      <h2 style="margin:0 0 14px; font-size:1rem; font-weight:700; padding-bottom:12px; border-bottom:1px solid #f1f5f9; color:#0f172a; display:flex; align-items:center; gap:8px;">
        &#128240; Latest Headlines
      </h2>
      <div style="display:flex; flex-direction:column; gap:4px;">
        {rows}
      </div>
    </section>"""


def _render_war_room(report: ReportData, offseason_news: NewsData, primary_color: str) -> str:
    items = report['war_room_items']

    bullets = ""
    for item in items:
        bullets += f"""
        <li style="padding:10px 0; border-bottom:1px solid #f1f5f9; list-style:none;">
          <span style="font-size:0.75rem; font-weight:700; color:#0f172a;">{e(item['title'])}</span>
          <p style="margin:3px 0 0; font-size:0.82rem; color:#64748b; line-height:1.5;">{e(item['summary'])}</p>
        </li>"""

    # Also show offseason news links in the sidebar
    news_links = ""
    for item in offseason_news['items'][:4]:
        link = item.get('url', '')
        title_html = (
            f'<a href="{e(link)}" style="color:#475569; text-decoration:none;" target="_blank">{e(item["title"])}</a>'
            if link else e(item["title"])
        )
        news_links += f"""
        <li style="padding:8px 0; border-bottom:1px solid #f8fafc; list-style:none; font-size:0.8rem; line-height:1.45; color:#475569;">
          {title_html}
          <span style="display:block; font-size:0.68rem; color:#94a3b8; margin-top:2px;">{e(item['source'])} &middot; {e(item['date'])}</span>
        </li>"""

    return f"""
    <div style="background:#fff; border-radius:12px; border:1px solid #e2e8f0; padding:24px; box-shadow:0 1px 3px rgba(0,0,0,0.06);">
      <h2 style="margin:0 0 6px; font-size:1rem; font-weight:700; padding-bottom:12px; border-bottom:1px solid #f1f5f9; color:#0f172a; display:flex; align-items:center; gap:8px;">
        &#127919; War Room
      </h2>
      <p style="margin:0 0 14px; font-size:0.82rem; color:#64748b; line-height:1.55;">{e(report['war_room_intro'])}</p>
      <ul style="margin:0; padding:0;">
        {bullets}
      </ul>
      {"<h3 style='margin:20px 0 10px; font-size:0.75rem; font-weight:700; text-transform:uppercase; letter-spacing:0.1em; color:#94a3b8;'>Related Reading</h3><ul style='margin:0; padding:0;'>" + news_links + "</ul>" if news_links else ""}
    </div>"""


# ── Master renderer ───────────────────────────────────────────────────────────

def render_report(
    report:         ReportData,
    general_news:   NewsData,
    reddit_data:    RedditData,
    offseason_news: NewsData,
) -> str:
    """
    Renders all data into a fully self-contained HTML document.
    Uses a two-column layout (8/4 split) matching the example.jsx design.
    """
    primary_color = "#005F66"   # Dolphins teal; swap per team if desired

    header           = _render_header(report, primary_color)
    exec_summary     = _render_executive_summary(report)
    sentiment        = _render_sentiment(report)
    hot_takes        = _render_hot_takes(reddit_data)
    news_feed        = _render_news_feed(general_news, primary_color)
    war_room         = _render_war_room(report, offseason_news, primary_color)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{e(report['team_name'])} Weekly Brief &mdash; {e(report['date'])}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #f1f5f9;
      font-family: 'Inter', system-ui, sans-serif;
      color: #1e293b;
      min-height: 100vh;
    }}
    .layout {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 24px 16px 60px;
      display: grid;
      grid-template-columns: 1fr 340px;
      grid-template-rows: auto;
      gap: 20px;
    }}
    .main-col  {{ display: flex; flex-direction: column; gap: 20px; }}
    .side-col  {{ display: flex; flex-direction: column; gap: 20px; }}
    footer     {{ grid-column: 1 / -1; text-align: center; color: #94a3b8; font-size: 0.78rem; padding-top: 8px; border-top: 1px solid #e2e8f0; }}
    @media (max-width: 760px) {{
      .layout {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>

  {header}

  <div class="layout">

    <div class="main-col">
      {exec_summary}
      {sentiment}
      {hot_takes}
      {news_feed}
    </div>

    <div class="side-col">
      {war_room}
    </div>

    <footer>
      <p>AI-Generated Report &bull; Bleacher Bot &bull; Not affiliated with the NFL or {e(report['team_name'])}</p>
    </footer>

  </div>

</body>
</html>"""


# ── Email delivery ────────────────────────────────────────────────────────────

def _plain_text_intro(team_name: str) -> str:
    return (
        f"Your {team_name} weekly intelligence report is attached.\n\n"
        f"Open the HTML file in any browser to view the full dashboard.\n\n"
        f"— Bleacher Bot"
    )


def send_email(subject: str, html: str) -> None:
    """
    Sends the rendered HTML report as a file attachment via Gmail SMTP.
    In DRY_RUN mode, writes newsletter_preview.html to the project root.

    Args:
        subject: Email subject line.
        html:    Fully rendered HTML string from render_report().
    """
    team_name = TEAM["name"]

    if DRY_RUN:
        preview_path = "newsletter_preview.html"
        logger.info(f"DRY_RUN=true — writing HTML preview to {preview_path}")
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n✅ Preview written to: {preview_path}")
        print("   Open it in a browser to see the rendered report.\n")
        return

    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        raise ValueError(
            "GMAIL_USER and GMAIL_APP_PASSWORD must be set. "
            "Use DRY_RUN=true for local testing."
        )

    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"bleacher-bot-{date_str}.html"

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT_EMAIL

    msg.attach(MIMEText(_plain_text_intro(team_name), "plain"))

    attachment = MIMEBase("text", "html")
    attachment.set_payload(html.encode("utf-8"))
    encoders.encode_base64(attachment)
    attachment.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(attachment)

    logger.info(f"Connecting to {SMTP_HOST}:{SMTP_PORT}...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())

    logger.info(f"✅ Report sent to {RECIPIENT_EMAIL} (attachment: {filename})")
