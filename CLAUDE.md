# Mekhani — Development Guide

**Positronica Labs** | Multi-platform freelance job automation  
**Repo:** github.com/G10hdz/Mekhani (privado)  
**Created:** 2026-04-11

---

## What this project does

End-to-end agentic system that scrapes job listings on Upwork, Fiverr, and Freelancer, scores them against a freelancer profile, generates personalized proposals via Claude API, creates Google Docs with Mermaid diagrams, and notifies by Telegram.

Imports all shared logic from **positronica_core** (`../positronica_core/`).

---

## Stack

- Python 3.11+
- positronica_core (shared library — local editable install)
- Playwright (browser automation for Upwork MCP)
- Upwork MCP server at `/home/gio/Tools/upwork-mcp` (vanooo/upwork-mcp)
- Apify client (Fiverr scraping)
- Freelancer.com official API (OAuth 2.0)
- Google Docs API (OAuth 2.0)
- Claude 3.5 Sonnet (proposal generation)
- APScheduler (runs at 9am + 6pm)
- python-telegram-bot (notifications)
- SQLite (local DB, WAL mode)

---

## Project Rules

- Feature branches always, never push directly to main
- Credentials in `.env`, never hardcoded
- Dependencies in `requirements.txt` with pinned versions
- Tests in `tests/` with pytest
- Logging: stdout + `logs/mekhani.log`, no silent failures
- `load_dotenv()` must be the FIRST thing in `main.py`
- Run varlock before any push near credentials
- `--dry-run` flag must prevent all real applications

---

## Directory Structure

```
Mekhani/
├── CLAUDE.md                      # This file
├── README.md                      # User guide
├── .env.example                   # All env vars documented
├── .gitignore
├── requirements.txt               # Depends on ../positronica_core
├── main.py                        # CLI: --once, --stats, --test-upwork, --dry-run
├── scheduler.py                   # APScheduler orchestration
├── config/
│   ├── profiles.yaml              # Freelancer skill profiles
│   └── platforms.yaml             # Per-platform API config + keywords
├── scrapers/
│   ├── base.py                    # Abstract BaseScraper
│   ├── upwork.py                  # Upwork MCP integration
│   ├── fiverr.py                  # Apify actor wrapper
│   └── freelancer.py              # Freelancer.com REST API
├── generators/
│   ├── proposal.py                # Claude API: 35-word preview + full proposal
│   └── docs.py                    # Google Doc + local markdown export
├── pipelines/
│   ├── score_and_filter.py        # Multi-profile scoring
│   └── apply_and_notify.py        # Apply + Doc + Telegram
├── tests/
│   ├── test_scrapers.py
│   └── test_generators.py
└── logs/
    └── mekhani.log
```

---

## First-Time Setup

### 1. Install dependencies

```bash
cd /home/gio/Vscode-projects/Mekhani
pip install --break-system-packages -r requirements.txt
playwright install chromium
```

### 2. Configure .env

```bash
cp .env.example .env
# Edit .env with real values
```

### 3. Setup Upwork MCP

```bash
# Install (one time)
git clone https://github.com/vanooo/upwork-mcp /home/gio/Tools/upwork-mcp
cd /home/gio/Tools/upwork-mcp
uv sync

# Login (browser opens — log in manually)
uv run upwork-mcp --login

# Validate session
uv run upwork-mcp --check
```

### 4. Setup Google Docs OAuth

1. Go to https://console.cloud.google.com
2. Create a new project (or use existing)
3. Enable **Google Docs API** and **Google Drive API**
4. Go to **APIs & Services > Credentials**
5. Create **OAuth 2.0 Client ID** → Desktop application
6. Download JSON → save as `~/.mekhani/credentials.json`
7. First run will open browser for consent → `token.json` auto-saved

```bash
mkdir -p ~/.mekhani
mv ~/Downloads/credentials*.json ~/.mekhani/credentials.json
```

### 5. Setup Apify (Fiverr)

1. Sign up free at https://apify.com
2. Go to **Settings > Integrations > API tokens**
3. Copy API token → set as `APIFY_API_KEY` in `.env`
4. The scraper uses actor: `automation-lab/fiverr-scraper`

### 6. Setup Freelancer OAuth

1. Register at https://developers.freelancer.com
2. Create application → get client ID + secret
3. Complete OAuth 2.0 flow to get access token
4. Set `FREELANCER_OAUTH_TOKEN` in `.env`

---

## Usage

```bash
# Run pipeline once (debug / dry-run)
python main.py --once
python main.py --once --dry-run   # no real applications

# Check DB stats
python main.py --stats

# Test platform connections
python main.py --test-upwork
python main.py --test-freelancer
python main.py --test-fiverr

# Start full scheduler (runs at 9am + 6pm)
python main.py
```

---

## Auto-start on Boot (Systemd)

```bash
# Copy service file
sudo cp mekhani.service /etc/systemd/system/mekhani.service

# Enable
sudo systemctl daemon-reload
sudo systemctl enable mekhani
sudo systemctl start mekhani
sudo systemctl status mekhani

# Logs
journalctl -u mekhani -f
```

`mekhani.service` contents:
```ini
[Unit]
Description=Mekhani — Multi-Platform Freelance Job Automation
After=network.target

[Service]
Type=simple
User=gio
WorkingDirectory=/home/gio/Vscode-projects/Mekhani
EnvironmentFile=/home/gio/Vscode-projects/Mekhani/.env
ExecStart=/usr/bin/python3 main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## Shared Library (positronica_core)

All core logic lives in `../positronica_core/`. Import like:

```python
from positronica_core.db import Job, init_db, bulk_insert_jobs
from positronica_core.config import settings
from positronica_core.filters import match_cv, score_job
from positronica_core.llm import ClaudeClient
from positronica_core.notifiers import TelegramNotifier, GoogleDocsClient
```

If positronica_core changes break Mekhani, check the core changelog first.

---

## Error Handling

| Error | Action |
|-------|--------|
| Upwork MCP session expired | Run `uv run upwork-mcp --login` in `/home/gio/Tools/upwork-mcp` |
| Google Docs token expired | Delete `~/.mekhani/token.json`, run again to re-auth |
| Apify quota exceeded | Check plan at apify.com, or skip Fiverr for the day |
| Claude API error | Check `ANTHROPIC_API_KEY`, verify account has credits |
| Telegram flood wait | Bot auto-retries — check `logs/mekhani.log` |

---

## Phase Status

- [x] Phase 1: Core infrastructure (positronica_core + Mekhani skeleton)
- [x] Phase 2: Platforms & Scrapers (Upwork MCP, Freelancer API, Fiverr Apify)
- [ ] Phase 3: Generation & Notification (proposals, Google Docs, Telegram)
- [ ] Phase 4: Orchestration & Boot (scheduler, systemd, end-to-end test)
