# Lawbot — Your AI Legal Agent

Lawbot is a personal AI legal agent that works for you over WhatsApp and SMS.

You tell it your situation once. It understands your case, finds lawyers, calls them on your behalf, collects their responses, and sends you back a clear recommendation on who to choose and why.

---

## What it does

1. **You text Lawbot** on WhatsApp or SMS describing your situation
2. **Lex (the AI)** asks follow-up questions to fully understand your case
3. **Lawbot finds lawyers** in your area using Google Places, filtered by practice area
4. **Lawbot calls each lawyer** via AI phone call, explains your case, and asks structured questions
5. **You get a report** — lawyer by lawyer breakdown with costs, assessments, and a clear recommendation
6. **You reply with a number** (1, 2, or 3) and Lawbot sends you that lawyer's direct contact info

---

## Core value

> You never explain your situation multiple times again.
> You never have to figure out "which lawyer is better" on your own.

---

## Features

- WhatsApp + SMS intake via Twilio
- AI intake interview powered by Claude
- Lawyer discovery via Google Places API
- Outbound AI phone calls to lawyers (Twilio Voice + Claude)
- Structured data collection from each call (fee, assessment, next steps)
- Comparison report with a single clear recommendation
- Internal review system — past users rate lawyers after their case, improving future recommendations
- 7-day automated follow-up to collect outcome and rating

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Messaging | Twilio (WhatsApp + SMS) |
| Voice calls | Twilio Voice |
| AI | Anthropic Claude |
| Lawyer search | Google Places API |
| Database | SQLite (Railway persistent volume) |
| Server | Flask + Gunicorn |
| Hosting | Railway |

---

## Project structure

```
lawbot/
├── execution/                  # Python scripts (deterministic logic)
│   ├── webhook_server.py       # Flask server — entry point
│   ├── conversation_manager.py # AI intake conversation
│   ├── lawyer_finder.py        # Google Places lawyer search
│   ├── phone_caller.py         # Outbound call initiator
│   ├── call_handler.py         # AI conversation during live call
│   ├── recommendation_engine.py# Comparison + report generation
│   ├── feedback_handler.py     # Post-case review collection
│   ├── followup_scheduler.py   # 7-day follow-up background job
│   ├── notifier.py             # WhatsApp/SMS message sender
│   └── db.py                   # Database schema + helpers
├── directives/                 # SOPs (natural language instructions)
│   ├── intake_interview.md
│   ├── lawyer_outreach_call.md
│   ├── recommendation.md
│   ├── feedback_collection.md
│   └── setup.md
├── Procfile                    # Railway process definitions
├── railway.json                # Railway config
├── requirements.txt
└── .env.example                # Environment variable template
```

---

## Getting started

See [`directives/setup.md`](directives/setup.md) for full setup instructions.

**You will need:**
- Anthropic API key
- Twilio account (WhatsApp + SMS + Voice)
- Google Places API key
- Railway account (for hosting)

---

## Branch workflow

| Branch | Purpose |
|--------|---------|
| `main` | Production — protected, auto-deploys to Railway |
| `develop` | All active development happens here |

To make a change: work on `develop` → open a pull request → merge into `main` → Railway redeploys automatically.

---

## Security

- No API keys are stored in code or committed to the repository
- All secrets are managed via Railway environment variables
- `.env` is gitignored — never committed
- Main branch is protected — requires pull request approval to merge
