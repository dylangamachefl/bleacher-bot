# 🐬 Bleacher Bot

A zero-cost, headless automated NFL newsletter delivered to your inbox every Monday morning. Powered by Google News RSS, Reddit, and Gemma 3 27B via Google AI Studio.

## How It Works

```
Google News RSS ──┐
Reddit API ────────┼──► [ThreadPoolExecutor: 3 parallel LLM calls] ──► Gmail SMTP ──► 📬
Seasonal RSS ─────┘
```

Three threads fire simultaneously — each writes one section of the newsletter — then the results are stitched into a styled HTML email.

| Section | Source | Voice |
|---|---|---|
| 📰 **The Front Page** | Google News RSS | Dramatic sports journalist |
| 🍺 **The Watercooler** | Reddit r/miamidolphins | Die-hard fan, funny |
| 🏈 **The War Room** | Seasonal RSS | Front-office analyst |

---

## Setup

### 1. Clone & Setup

```powershell
git clone https://github.com/YOUR_USERNAME/bleacher-bot
cd bleacher-bot

# One-command setup: creates .venv, installs deps, copies .env.example → .env
.\setup.ps1
```

To activate the venv in future sessions:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 2. Create a `.env` file

```env
# LLM — Google AI Studio
GEMINI_API_KEY=your_key_here

# Gmail (use an App Password, not your real password)
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=xxxx_xxxx_xxxx_xxxx

# Team (defaults to Miami Dolphins if omitted)
TEAM_NAME=Miami Dolphins
TEAM_SUBREDDIT=miamidolphins
TEAM_NEWS_QUERY=Miami+Dolphins+NFL
```

### 3. Run Locally (Dry Run — no email sent)

```bash
DRY_RUN=true python main.py
```

### 4. Run for Real

```bash
python main.py
```

---

## GitHub Actions (Automated Weekly Delivery)

Push to GitHub and add the following **Repository Secrets** under  
`Settings → Secrets and variables → Actions → New repository secret`:

| Secret | Value |
|---|---|
| `GEMINI_API_KEY` | Your Google AI Studio API key |
| `GMAIL_USER` | Your Gmail address |
| `GMAIL_APP_PASSWORD` | Gmail App Password |
| `TEAM_NAME` | e.g. `Miami Dolphins` |
| `TEAM_SUBREDDIT` | e.g. `miamidolphins` |
| `TEAM_NEWS_QUERY` | e.g. `Miami+Dolphins+NFL` |

The workflow runs **every Monday at 12:00 UTC** (8 AM ET). You can also trigger it manually from the **Actions** tab using the "Run workflow" button.

---

## Switching Teams

No code changes needed — just update your GitHub Secrets or `.env`:

```env
TEAM_NAME=Philadelphia Eagles
TEAM_SUBREDDIT=eagles
TEAM_NEWS_QUERY=Philadelphia+Eagles+NFL
```

---

## Getting Credentials

- **Google AI Studio API Key:** https://aistudio.google.com/apikey
- **Gmail App Password:** https://myaccount.google.com/apppasswords (requires 2FA)
- **Reddit:** no credentials needed — uses the public JSON API (`reddit.com/r/{subreddit}/top.json`)

---

## Running Tests

```bash
# Config/unit tests (no network needed)
python -m pytest tests/test_config.py -v

# Scraper smoke tests (requires internet)
python -m pytest tests/test_scrape.py -v -m network
```
