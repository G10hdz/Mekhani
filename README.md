# Mekhani

Multi-platform freelance job automation — Upwork + Fiverr + Freelancer.com

**By Positronica Labs** | Built on `positronica_core` shared library

---

## What it does

1. **Scrapes** job listings from Upwork (MCP), Fiverr (Apify), and Freelancer (API)
2. **Scores** them against your skills profile (keyword matching + hybrid scoring)
3. **Generates** personalized proposals via Claude API (35-word preview + full proposal)
4. **Creates** a Google Doc with job breakdown and Mermaid diagram for each match
5. **Notifies** you on Telegram with the doc link and job details
6. **Runs automatically** at 9am + 6pm via APScheduler (or systemd)

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/G10hdz/Mekhani
cd Mekhani

# 2. Install
pip install -r requirements.txt
playwright install chromium

# 3. Configure
cp .env.example .env
# Edit .env with your API keys (see CLAUDE.md for each platform's setup)

# 4. Test once
python main.py --once --dry-run

# 5. Start scheduler
python main.py
```

---

## Platform Setup

| Platform | Method | Setup |
|----------|--------|-------|
| **Upwork** | MCP browser automation | See CLAUDE.md §3 |
| **Fiverr** | Apify actor | Sign up apify.com, get API key |
| **Freelancer** | Official REST API | Register at developers.freelancer.com |
| **Google Docs** | OAuth 2.0 | See CLAUDE.md §4 |
| **Telegram** | Bot token | Create bot via @BotFather |

---

## Configuration

Copy `.env.example` → `.env` and fill in:

```env
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
UPWORK_MCP_PATH=/home/gio/Tools/upwork-mcp
GOOGLE_DOCS_CREDENTIALS_JSON=~/.mekhani/credentials.json
APIFY_API_KEY=...
FREELANCER_OAUTH_TOKEN=...
MEKHANI_SCHEDULE_HOURS=9,18
MEKHANI_MIN_SCORE=0.4
```

---

## Profiles

Configure your skills in `config/profiles.yaml`:

```yaml
name: my_profile
telegram_chat_id: "123456789"

skills:
  python: 0.20
  aws: 0.15
  react: 0.10
  fastapi: 0.10

core_skills: [python, aws, react]
min_score: 0.4

preferences:
  remote_preferred: true
  hard_exclusions: [intern, junior]
```

Multiple profiles supported — each gets their own notifications.

---

## Commands

```bash
python main.py               # Start scheduler (runs forever)
python main.py --once        # Run pipeline once
python main.py --once --dry-run  # Run without applying
python main.py --stats       # Show DB stats
python main.py --test-upwork # Test Upwork MCP connection
```

---

## Architecture

```
Upwork (MCP) ──┐
Fiverr (Apify) ─┼──→ [Scraper] ──→ [SQLite dedup] ──→ [Scorer]
Freelancer (API) ┘                                         │
                                                           ↓
                                               [Claude: generate proposal]
                                                           │
                                                           ↓
                                               [Google Docs: create + export]
                                                           │
                                                           ↓
                                               [Telegram: notify with link]
```

---

## Shared Library

Mekhani imports core logic from `positronica_core`:

- `positronica_core.db` — Job model, SQLite CRUD, deduplication
- `positronica_core.filters` — Keyword matching + hybrid scoring
- `positronica_core.llm` — Claude API wrapper
- `positronica_core.config` — Settings from .env
- `positronica_core.notifiers` — Telegram + Google Docs

---

## Status

- [x] Phase 1: Core infrastructure
- [x] Phase 2: Scrapers (Upwork, Fiverr, Freelancer)
- [ ] Phase 3: Proposals + Google Docs + Telegram
- [ ] Phase 4: Scheduler + systemd boot

---

## Related Projects

- `positronica_core` — Shared library (future: Ergane migration)
- `Ergane` — Job search automation for Mexico (uses own internal copy)
- `Metis` — AI agent orchestrator (LangGraph + Telegram)
