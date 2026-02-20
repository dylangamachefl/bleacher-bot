"""
deliver.py — Email delivery via Gmail SMTP with App Password.

The newsletter HTML is sent as a file attachment rather than the email
body. This lets us use full modern CSS (Google Fonts, custom properties,
grid) without worrying about email client rendering quirks.
"""

import re
import smtplib
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from src.config import GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL, DRY_RUN, TEAM

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# Regex compiled once
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"\*(.+?)\*")


def _inline_markup(text: str) -> str:
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    return text


def _markdown_to_html(md: str) -> str:
    """
    Converts the newsletter Markdown into a standalone HTML file.

    Structure produced:
      - Masthead  (h1 title + date subtitle)
      - Content   (three section cards, one per ## heading)
      - Footer    (attribution line after the final ---)

    Because this is a browser-rendered file attachment — not an inline
    email body — we can use Google Fonts, CSS custom properties, and
    modern layout freely.
    """
    # Split footer off at the last `---` in the document
    last_hr = md.rfind("\n---")
    if last_hr != -1:
        main_md = md[:last_hr]
        footer_md = md[last_hr + 4:].strip()
    else:
        main_md = md
        footer_md = ""

    masthead_lines: list[str] = []
    content_lines: list[str] = []
    in_card = False
    in_ul = False       # tracking whether we're inside an open <ul>
    in_blockquote = False  # tracking whether we're inside an open <blockquote>
    zone = "masthead"

    def _close_open_blocks() -> None:
        """Close any open list or blockquote before emitting a non-list/quote line."""
        nonlocal in_ul, in_blockquote
        if in_ul:
            content_lines.append("</ul>")
            in_ul = False
        if in_blockquote:
            content_lines.append("</blockquote>")
            in_blockquote = False

    for line in main_md.split("\n"):
        s = line.strip()

        if s.startswith("# "):
            _close_open_blocks()
            masthead_lines.append(f'<h1>{s[2:]}</h1>')
            zone = "masthead"

        elif s.startswith("### ") and zone == "masthead":
            masthead_lines.append(f'<p class="date">{s[4:]}</p>')

        elif s.startswith("## "):
            _close_open_blocks()
            zone = "content"
            if in_card:
                content_lines.append("</div>")
            content_lines.append(f'<div class="card"><h2>{s[3:]}</h2>')
            in_card = True

        elif s.startswith("### "):
            _close_open_blocks()
            content_lines.append(f'<h3>{s[4:]}</h3>')

        elif s.startswith("- ") and zone == "content":
            # Bullet list item — open <ul> if not already inside one
            if in_blockquote:
                content_lines.append("</blockquote>")
                in_blockquote = False
            if not in_ul:
                content_lines.append("<ul>")
                in_ul = True
            content_lines.append(f"<li>{_inline_markup(s[2:])}</li>")

        elif s.startswith("> ") and zone == "content":
            # Blockquote line — open <blockquote> if not already inside one
            if in_ul:
                content_lines.append("</ul>")
                in_ul = False
            if not in_blockquote:
                content_lines.append('<blockquote>')
                in_blockquote = True
            content_lines.append(f"<p>{_inline_markup(s[2:])}</p>")

        elif s in ("---", ""):
            # A blank line closes an open blockquote (signals end of quote + attribution)
            # but not a list (lists can have blank lines between items from the LLM)
            if in_blockquote:
                content_lines.append("</blockquote>")
                in_blockquote = False

        else:
            _close_open_blocks()
            text = _inline_markup(s)
            if zone == "masthead":
                masthead_lines.append(f"<p>{text}</p>")
            else:
                content_lines.append(f"<p>{text}</p>")

    _close_open_blocks()
    if in_card:
        content_lines.append("</div>")

    footer_html = (
        f"<p>{_inline_markup(footer_md)}</p>" if footer_md else "<p>Bleacher Bot</p>"
    )

    masthead_html = "\n      ".join(masthead_lines)
    content_html = "\n      ".join(content_lines)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{TEAM["name"]} Weekly Brief</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap" rel="stylesheet">
  <style>
    :root {{
      --teal:        #005F66;
      --teal-light:  #007A82;
      --orange:      #FC4C02;
      --bg:          #F0EDEA;
      --card-bg:     #FFFFFF;
      --card-border: #E2DED9;
      --text:        #1C1C1C;
      --text-muted:  #6B6560;
      --radius:      10px;
    }}

    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      background: var(--bg);
      color: var(--text);
      font-family: 'Source Serif 4', Georgia, serif;
      font-size: 17px;
      line-height: 1.75;
      padding: 40px 16px 60px;
    }}

    /* ── Page wrapper ───────────────────────────────────────────── */
    .page {{
      max-width: 680px;
      margin: 0 auto;
    }}

    /* ── Masthead ────────────────────────────────────────────────── */
    .masthead {{
      background: var(--teal);
      border-radius: var(--radius) var(--radius) 0 0;
      padding: 40px 40px 32px;
      text-align: center;
    }}
    .masthead h1 {{
      font-family: 'Playfair Display', Georgia, serif;
      font-size: 2.2rem;
      font-weight: 700;
      color: #fff;
      letter-spacing: -0.3px;
      line-height: 1.2;
      margin-bottom: 10px;
    }}
    .masthead .date {{
      font-size: 0.75rem;
      font-weight: 600;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: rgba(255, 255, 255, 0.55);
    }}

    /* ── Content area ────────────────────────────────────────────── */
    .content {{
      background: var(--card-bg);
      padding: 28px 32px 32px;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }}

    /* ── Section cards ───────────────────────────────────────────── */
    .card {{
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      padding: 24px 28px;
      background: #FDFCFB;
    }}
    .card h2 {{
      font-family: 'Source Serif 4', Georgia, serif;
      font-size: 0.68rem;
      font-weight: 600;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--orange);
      border-bottom: 1.5px solid var(--orange);
      padding-bottom: 9px;
      margin-bottom: 16px;
    }}
    .card p {{
      font-size: 1rem;
      line-height: 1.8;
      color: var(--text);
    }}
    .card strong {{
      font-weight: 600;
      color: var(--text);
    }}
    .card em {{
      font-style: italic;
      color: var(--text-muted);
    }}

    /* ── Bullet lists (War Room) ─────────────────────────────────── */
    .card ul {{
      margin: 10px 0 0 0;
      padding: 0;
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .card li {{
      font-size: 0.97rem;
      line-height: 1.65;
      color: var(--text);
      padding-left: 16px;
      position: relative;
    }}
    .card li::before {{
      content: "–";
      position: absolute;
      left: 0;
      color: var(--orange);
      font-weight: 600;
    }}

    /* ── Blockquotes (Watercooler fan takes) ─────────────────────── */
    .card blockquote {{
      margin: 14px 0;
      padding: 12px 16px;
      border-left: 3px solid var(--orange);
      background: #FFF8F5;
      border-radius: 0 6px 6px 0;
    }}
    .card blockquote p {{
      font-size: 0.95rem;
      line-height: 1.7;
      color: var(--text);
      font-style: italic;
    }}
    .card blockquote p + p {{
      margin-top: 4px;
      font-style: normal;
      font-size: 0.82rem;
      color: var(--text-muted);
    }}

    /* ── Footer ──────────────────────────────────────────────────── */
    .footer {{
      background: var(--teal);
      border-radius: 0 0 var(--radius) var(--radius);
      padding: 16px 32px;
      text-align: center;
    }}
    .footer p, .footer em {{
      font-size: 0.72rem;
      font-style: normal;
      color: rgba(255, 255, 255, 0.4);
    }}
  </style>
</head>
<body>
  <div class="page">

    <div class="masthead">
      {masthead_html}
    </div>

    <div class="content">
      {content_html}
    </div>

    <div class="footer">
      {footer_html}
    </div>

  </div>
</body>
</html>"""


def _plain_text_intro(subject: str, team_name: str) -> str:
    """Short plain-text email body that accompanies the HTML attachment."""
    return (
        f"Your {team_name} weekly brief is attached.\n\n"
        f"Open the HTML file in any browser to read the full report.\n\n"
        f"— Bleacher Bot"
    )


def send_email(subject: str, markdown_body: str) -> None:
    """
    Renders the newsletter as an HTML file and sends it as an email
    attachment via Gmail SMTP. The email body is a short plain-text note.

    If DRY_RUN is True, writes the HTML to ./newsletter_preview.html
    instead so you can open it directly in a browser.

    Args:
        subject:       Email subject line.
        markdown_body: Full newsletter content in Markdown.
    """
    html_body = _markdown_to_html(markdown_body)
    team_name = TEAM["name"]

    if DRY_RUN:
        preview_path = "newsletter_preview.html"
        logger.info(f"DRY_RUN=true — writing HTML preview to {preview_path}")
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html_body)
        print(f"\n✅ Preview written to: {preview_path}")
        print("   Open it in a browser to see the rendered newsletter.\n")
        return

    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        raise ValueError(
            "GMAIL_USER and GMAIL_APP_PASSWORD must be set to send email. "
            "Use DRY_RUN=true for local testing."
        )

    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"bleacher-bot-{date_str}.html"

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL

    # Plain-text body — short intro pointing to the attachment
    msg.attach(MIMEText(_plain_text_intro(subject, team_name), "plain"))

    # HTML report as attachment
    attachment = MIMEBase("text", "html")
    attachment.set_payload(html_body.encode("utf-8"))
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition",
        "attachment",
        filename=filename,
    )
    msg.attach(attachment)

    logger.info(f"Connecting to {SMTP_HOST}:{SMTP_PORT}...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())

    logger.info(f"✅ Newsletter sent to {RECIPIENT_EMAIL} (attachment: {filename})")
