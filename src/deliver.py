"""
deliver.py — Email delivery via Gmail SMTP with App Password.
"""

import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.config import GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL, DRY_RUN, TEAM

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _markdown_to_html(md: str) -> str:
    """
    Minimal Markdown → HTML converter sufficient for this newsletter's structure.
    Handles: h1/h2/h3 headings, bold, italic, horizontal rules, paragraphs, emoji.
    """
    lines = md.split("\n")
    html_lines = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("### "):
            html_lines.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("## "):
            html_lines.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("# "):
            html_lines.append(f"<h1>{stripped[2:]}</h1>")
        elif stripped == "---":
            html_lines.append("<hr>")
        elif stripped == "":
            html_lines.append("<br>")
        else:
            # Bold and italic
            import re
            stripped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped)
            stripped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", stripped)
            html_lines.append(f"<p>{stripped}</p>")

    body = "\n".join(html_lines)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {{
      font-family: Georgia, 'Times New Roman', serif;
      max-width: 680px;
      margin: 0 auto;
      padding: 32px 24px;
      background: #f9f9f7;
      color: #1a1a1a;
      line-height: 1.75;
    }}
    h1 {{
      font-size: 2em;
      color: #008E97;
      margin-bottom: 4px;
    }}
    h2 {{
      font-size: 1.3em;
      color: #FC4C02;
      border-left: 4px solid #FC4C02;
      padding-left: 10px;
      margin-top: 32px;
    }}
    h3 {{
      font-size: 1em;
      color: #555;
      font-weight: normal;
      margin-top: 0;
    }}
    hr {{
      border: none;
      border-top: 1px solid #ddd;
      margin: 24px 0;
    }}
    p {{
      margin: 0 0 12px;
    }}
    em {{
      color: #777;
      font-size: 0.9em;
    }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def send_email(subject: str, markdown_body: str) -> None:
    """
    Converts the Markdown newsletter to HTML and sends it via Gmail SMTP.
    If DRY_RUN is True, prints to stdout instead.

    Args:
        subject:       Email subject line.
        markdown_body: Full newsletter content in Markdown.
    """
    html_body = _markdown_to_html(markdown_body)

    if DRY_RUN:
        logger.info("DRY_RUN=true — printing newsletter to stdout instead of sending.")
        print("\n" + "=" * 70)
        print(f"SUBJECT: {subject}")
        print("=" * 70)
        print(markdown_body)
        print("=" * 70 + "\n")
        return

    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        raise ValueError(
            "GMAIL_USER and GMAIL_APP_PASSWORD must be set to send email. "
            "Use DRY_RUN=true for local testing."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL

    # Attach plain-text fallback and HTML version
    msg.attach(MIMEText(markdown_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    logger.info(f"Connecting to {SMTP_HOST}:{SMTP_PORT}...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())

    logger.info(f"✅ Newsletter sent to {RECIPIENT_EMAIL}")
