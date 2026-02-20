# Bleacher Bot

A zero-cost, automated NFL intelligence report delivered to your inbox every Monday morning. Scrapes Google News RSS and Reddit RSS, runs the data through Gemma 3 27B via Google AI Studio, and emails you a self-contained HTML dashboard as an attachment.

## Report Preview

![Bleacher Bot Report](docs/preview.png)

The report is a two-column HTML dashboard with:

| Section | Source |
|---|---|
| ⚡ **Executive Summary** | LLM synthesis of all scraped data |
| 💬 **Sentiment Radar** | Reddit RSS — score, breakdown, trending topics, top posts |
| 📰 **Latest Headlines** | Google News RSS — linked, sourced, timestamped |
| 🎯 **War Room** | LLM analysis of offseason/roster news + related reading links |

---

## How It Works

```
Google News RSS ──┐
Reddit RSS ────────┼──► Single LLM call (Gemma 3 27B) → JSON → HTML renderer → Gmail SMTP → 📬
Seasonal RSS ─────┘
```

1. **Scrape** — Three RSS feeds run in parallel: general news, Reddit hot posts, offseason/roster news
2. **Compose** — A single LLM call returns a validated JSON payload (Pydantic) with sentiment score, executive summary, war room items, and keywords
3. **Render** — A pure Python HTML renderer builds the dashboard from the JSON + raw scraper data
4. **Deliver** — The HTML file is sent as an email attachment (opens in any browser, full modern CSS)

---

## Setup

### 1. Clone & install

```bash
git clone https://github.com/YOUR_USERNAME/bleacher-bot
cd bleacher-bot
python -m venv .venv

# Windows
.\.venv\Scripts\Activate.ps1

# Mac/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Create a `.env` file

```env
# LLM — get your key at https://aistudio.google.com/apikey
GEMINI_API_KEY=your_key_here

# Gmail — use an App Password, not your real password
# Enable at https://myaccount.google.com/apppasswords (requires 2FA)
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=xxxx_xxxx_xxxx_xxxx

# Team (defaults to Miami Dolphins if omitted)
TEAM_NAME=Miami Dolphins
TEAM_SUBREDDIT=miamidolphins
TEAM_NEWS_QUERY=Miami+Dolphins+NFL
```

### 3. Dry run (no email sent — writes `newsletter_preview.html`)

```bash
DRY_RUN=true python main.py
```

Open `newsletter_preview.html` in a browser to preview the report.

### 4. Send for real

```bash
python main.py
```

---

## GitHub Actions — Automated Weekly Delivery

Push to GitHub and add the following secrets under
`Settings → Secrets and variables → Actions → New repository secret`:

| Secret | Value |
|---|---|
| `GEMINI_API_KEY` | Google AI Studio API key |
| `GMAIL_USER` | Your Gmail address |
| `GMAIL_APP_PASSWORD` | Gmail App Password |
| `TEAM_NAME` | e.g. `Miami Dolphins` |
| `TEAM_SUBREDDIT` | e.g. `miamidolphins` |
| `TEAM_NEWS_QUERY` | e.g. `Miami+Dolphins+NFL` |

The workflow fires **every Monday at 12:00 UTC** (8 AM ET). Trigger it manually anytime from the **Actions** tab → **Run workflow**.

---

## Switching Teams

No code changes needed — just update your `.env` or GitHub Secrets:

```env
TEAM_NAME=Philadelphia Eagles
TEAM_SUBREDDIT=eagles
TEAM_NEWS_QUERY=Philadelphia+Eagles+NFL
```

---

## Project Structure

```
bleacher-bot/
├── main.py              # Pipeline: scrape → compose → render → deliver
├── src/
│   ├── scrape.py        # Google News RSS + Reddit RSS scrapers
│   ├── compose.py       # LLM prompt, Pydantic validation, ReportData assembly
│   ├── deliver.py       # HTML renderer + Gmail SMTP delivery
│   ├── llm.py           # google-genai wrapper (Gemma 3 27B)
│   └── config.py        # Env vars, team config, seasonal keyword logic
├── .github/
│   └── workflows/
│       └── newsletter.yml
└── requirements.txt
```

---

## Running Tests

```bash
# Unit tests — no network needed
python -m pytest tests/test_config.py -v

# Scraper smoke tests — requires internet
python -m pytest tests/test_scrape.py -v -m network
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `feedparser` | RSS parsing (Google News + Reddit) |
| `requests` | HTTP requests |
| `google-genai` | Google AI Studio SDK (Gemma 3 27B) |
| `pydantic` | LLM JSON output validation |
| `python-dotenv` | `.env` loading |
