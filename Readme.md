# FitCover India — Wellness Data Platform (MVP)

Python/FastAPI web app for an Indian insurtech wellness platform. Users connect **Garmin** and **Fitbit**, receive a daily **wellness score**, and unlock **Vitality-style rewards**. You are the health data provider; insurers consume data via API.

## Why Python?

For this product, Python is a strong fit:

- **Health scoring & analytics** — pandas/numpy later for actuarial models
- **Insurer integrations** — easy CSV/API exports, batch jobs, ETL
- **ML readiness** — risk prediction models when you scale
- **Team familiarity** — if your team knows Python, ship faster

Use TypeScript/React later if you need a highly interactive mobile-first UI. For this MVP (server-rendered webapp), Python is simpler and equally capable.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env
python run.py
```

Open [http://localhost:8000](http://localhost:8000)

1. Register an account
2. Click **Load demo data** on the dashboard
3. Or connect Garmin/Fitbit under **Devices** (requires API credentials)

## Project structure

```
Insurtech/
├── app/
│   ├── main.py              # FastAPI routes & pages
│   ├── models.py            # SQLAlchemy models
│   ├── sync.py              # Device sync, scoring, tiers
│   ├── wellness_score.py    # Score engine
│   ├── tiers.py             # Vitality tier rules
│   ├── providers/           # Garmin & Fitbit OAuth
│   └── templates/           # HTML pages (Jinja2)
├── requirements.txt
├── run.py
└── .env.example
```

## Environment variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Default: `sqlite:///./dev.db` |
| `JWT_SECRET` | Session signing key |
| `APP_URL` | Base URL for OAuth callbacks |
| `FITBIT_CLIENT_ID` / `FITBIT_CLIENT_SECRET` | Fitbit developer app |
| `GARMIN_CONSUMER_KEY` / `GARMIN_CONSUMER_SECRET` | Garmin developer program |
| `INSURER_API_KEY` | Key for insurer export API |

OAuth callbacks:

- Fitbit: `{APP_URL}/devices/fitbit/callback`
- Garmin: `{APP_URL}/devices/garmin/callback`

## Insurer API

```bash
curl -H "x-insurer-api-key: YOUR_KEY" \
  "http://localhost:8000/api/insurer/users?email=user@example.com"
```

## Features

- Direct Garmin (OAuth 1.0a) & Fitbit (OAuth 2.0) connections
- Unified daily metrics merged across devices
- Wellness score 0–100 (activity, cardio, recovery, consistency)
- Vitality tiers — rewards only, **never downgrade**
- Cashbacks & coupons you manage
- Demo data mode for local testing

## Not in MVP

- Apple Health / Google Health (need mobile app)
- Smartwatch apps
- Premium increases (rewards-only model)
