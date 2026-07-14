# RimAI — Zimbabwe Agricultural Intelligence Platform

[![Tests](https://github.com/TereraiC/RimAI-AI4I-2026/actions/workflows/tests.yml/badge.svg)](https://github.com/TereraiC/RimAI-AI4I-2026/actions/workflows/tests.yml)

An AI-powered agricultural intelligence platform combining machine learning yield/risk
prediction, explainable AI, weather intelligence, and institutional decision support for
Zimbabwe's farmers, AGRITEX extension officers, and Ministry of Agriculture.

Built for the **2026 AI for Impact Challenge (AI4I) — Track 3: Development**.

---

## Architecture

```
Data Layer (real: FAOSTAT, NASA POWER, NOAA ENSO — synthetic: disclosed agronomic augmentation)
        │
        ▼
Feature Engineering (rainfall anomaly, soil moisture proxy, NDVI proxy, ENSO phase, ...)
        │
        ▼
Machine Learning Models (Ridge regression — yield · XGBoost — risk classification)
        │
        ▼
Explanation Engine  →  Economic Impact Engine  →  Recommendation Engine
        │
        ▼
Farmer / AGRITEX / Ministry / Admin Dashboards (Flask + Jinja2, one shared pipeline)
```

See the full technical design and AI-necessity rationale in the written proposal
(`docs/` in the submission package, not this repo).

## Project Structure

```
rimai/
├── app.py                    # Flask application: routes, auth, RBAC, DB schema
├── core/                     # Prediction & reasoning engines
│   ├── harvest_model.py          Yield (Ridge) + risk (XGBoost) prediction, PROVINCE_META
│   ├── crop_advisor.py           Combines weather + rotation + pest + prediction into one analysis
│   ├── explanation_engine.py     Turns model output into cited "why" explanations
│   ├── agronomy_engine.py        Crop rotation and pest-risk rule logic
│   ├── farm_manager.py           Farm Health Score, Daily Brief, Smart Calendar, Farm Memory
│   └── rimai_assistant_free.py   Rule-grounded Virtual Agronomist chat (no external LLM)
├── data_pipeline/            # Data ingestion, synthetic data management, model validation
│   ├── fetch_faostat.py          Real FAOSTAT yield history (with disclosed fallback)
│   ├── build_master_dataset.py   Merges yield history with NASA POWER weather
│   ├── weather_service.py        Live per-farm weather via NASA POWER
│   ├── backtest_yield_model.py   Walk-forward backtest (train-on-past, predict-next-year)
│   └── synthetic_registry.py     Dataset registry: real/synthetic/hybrid, gaps, confidence notes
├── dashboards/                # Route-support modules for each role dashboard
│   ├── admin.py                  Model performance, pipeline health, backtest metrics
│   ├── agritex.py                 Priority queue, ward risk table, field visit logging
│   └── ministry.py                National food security index, policy simulator inputs
├── integrations/               # External channels
│   ├── whatsapp_service.py       Twilio WhatsApp alerts (demo-mode fallback if unconfigured)
│   ├── email_service.py          SMTP email alerts
│   └── proactive_alerts.py       Background watcher + alert/email table management
├── templates/                  # Jinja2 templates for all dashboards
├── data/{raw,processed}/       # Data pipeline inputs/outputs (populated at runtime)
├── models/                     # Trained model artifacts (populated at runtime, not committed)
├── tests/                      # pytest unit tests
├── requirements.txt
└── .gitignore
```

## Setup

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Running

```bash
python app.py
```

The app starts on `http://localhost:5000`. On first run it will:
1. Create `rimai.db` (SQLite) with all required tables and seed data.
2. Train the yield/risk models (`core/harvest_model.py`) — a few seconds, no GPU required.
3. Start a background thread that checks for proactive alerts every 120 seconds.

### Demo accounts

| Username | Password | Role |
|---|---|---|
| `demo` | `rimai2026` | Farmer |
| `officer` | `officer2026` | AGRITEX Officer |
| `ministry` | `ministry2026` | Ministry |
| `admin` | `admin2026` | Admin |

### Optional: live WhatsApp / email alerts

Without credentials, WhatsApp and email alerts run in a fully-logged **demo mode** (visible
in the WhatsApp/Email dashboard) rather than failing. To enable live delivery, set:

```bash
export TWILIO_ACCOUNT_SID=...
export TWILIO_AUTH_TOKEN=...
export EMAIL_SMTP_HOST=... EMAIL_SMTP_PORT=587 EMAIL_SMTP_USER=... EMAIL_SMTP_PASSWORD=...
export EMAIL_FROM=...   # defaults to EMAIL_SMTP_USER if not set
```

### Refreshing real data

FAOSTAT and NASA POWER are called live by default. If either is unreachable
(rate-limited, network-restricted, etc.), the pipeline falls back to a disclosed,
clearly-labelled representative dataset rather than crashing — see
`data_pipeline/fetch_faostat.py` and `data_pipeline/build_master_dataset.py`.

```bash
python -c "from data_pipeline.fetch_faostat import run_pipeline; run_pipeline()"
python -c "from data_pipeline.build_master_dataset import build_master_dataset; build_master_dataset()"
python -c "from data_pipeline.backtest_yield_model import run_backtest; run_backtest()"
```

## Testing

```bash
pytest tests/ -v
```

22 tests covering: yield/risk prediction consistency (a real bug found in QA, where the
separately-trained yield regressor and risk classifier could disagree), the admin
backtest-metrics schema normalization (another real bug — the real walk-forward backtest
output used different field names than the dashboard expected), the synthetic data
registry, and a fresh-database schema regression test (confirms every table/column the
app queries actually exists — two of these, `field_visits`/`input_allocations` and
`users.full_name`, were missing from the original schema and only worked by accident on
a long-lived development database).

## Data Sources & Provenance

Every dataset RimAI uses is classified **real**, **synthetic**, or **hybrid** in a
dedicated registry, viewable live at `/admin/data-provenance` (login as `admin`):

- **Real:** FAOSTAT national maize yield history (2000–2024), NASA POWER weather
  (rainfall, temperature, humidity), NOAA ENSO phase index.
- **Synthetic (disclosed):** farm-level features with no Zimbabwe dataset yet available
  at this granularity — soil moisture proxy, NDVI proxy, fertiliser rate, planting date,
  previous yield — generated with agronomically-calibrated formulas, not blended silently
  with real records.
- **Known gaps:** livestock records, market price history, AGRITEX inspection reports,
  and disease observation logs have no real data source yet — disclosed, not hidden.

## Deploying a Persistent Demo URL

Running via Colab + ngrok only stays live while that notebook session is open — not
reliable for a judge clicking the link days later. This repo includes ready-to-use
deployment config for free-tier persistent hosting:

**Render.com (recommended, ~2 minutes):**
1. Push this repo to GitHub.
2. On [render.com](https://render.com), New → Blueprint → connect the repo.
   `render.yaml` in this repo configures the build and start commands automatically.
3. Render deploys `gunicorn app:app` on the free tier and gives you a permanent
   `https://rimai-xxxx.onrender.com` URL.

**PythonAnywhere (manual, ~10 minutes):** upload the repo, create a virtualenv,
`pip install -r requirements.txt`, and point a Flask web app at `app:app` in the
PythonAnywhere web console.

Either way, that URL is what should go in the "Demo URL" field of the AI4I submission
portal — not a Colab/ngrok link.

## License

Core dependencies (Flask, scikit-learn, XGBoost, pandas, numpy) are permissively
licensed open-source software (BSD / Apache-2.0 / MIT family). No proprietary model
licences are in use.
