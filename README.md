# AegisEco

AegisEco is an AI-powered flash-flood early-warning system for Israel. It combines live
meteorological and hydrological data, 16 per-basin XGBoost flood models, a 7-agent CrewAI
verification pipeline, and a Streamlit dashboard to detect, verify, and broadcast flood
alerts in near real time.

## How it works

1. **Data ingestion** — `src/data_sentinel` pulls live rain data from the Israel
   Meteorological Service (IMS) API and river flow data from Weather2Day into a Neon
   PostgreSQL/PostGIS database (every 10 minutes).
2. **ML inference** — 16 XGBoost classifiers (one per main drainage basin) score the
   latest hourly features and flag basins likely to flood in the next 1–3 hours.
3. **Agent verification & alerting** — a sequential CrewAI pipeline (runs hourly)
   re-checks ML alerts against OSINT search, Israeli news RSS, public emergency
   Telegram channels, and official IMS warnings, then sends a Telegram alert for
   any newly-flagged basin and a
   stand-down message once a previously-alerted basin returns to normal. Each
   basin's alert state is tracked in `alert_log` so the same warning isn't
   repeated every hour.
4. **Dashboard** — a Streamlit app shows a live risk map of Israel's basins, affected
   roads, council/settlement forecasts, and role-based views (Citizen / City / Authority).

## Project Structure

```text
AegisEco/
├── main.py                      # Entry point: runs one full cycle, then schedules
│                                 # hourly (full) and 10-min (data-only) cycles
├── requirements.txt
├── .env.template                # Copy to .env and fill in your keys
│
├── src/
│   ├── crew/                    # CrewAI agent pipeline
│   │   ├── aegiseco_crew.py     # Defines the 7 agents, their tools, and task order
│   │   ├── config/
│   │   │   ├── agents.yaml      # Agent roles, goals, backstories
│   │   │   └── tasks.yaml       # Task descriptions & expected outputs
│   │   └── tools/
│   │       ├── data_tools.py    # Sync rain/flow/forecast data; RSS, Telegram, OSINT search
│   │       ├── db_tools.py      # ML inference, rainfall queries, affected-roads lookup
│   │       └── alert_tools.py   # Telegram broadcast
│   │
│   ├── data_sentinel/           # Live data ingestion
│   │   ├── ims_client.py        # IMS rain API client
│   │   └── flow_ingestor.py     # Weather2Day river-flow scraper
│   │
│   └── database/
│       └── db_manager.py        # Neon connection + feature engineering for live ML inference
│
├── models/                       # ML training pipeline & artifacts
│   ├── models/*.pkl              # 16 trained XGBoost models (one per basin)
│   ├── ML pipelines/train_model_v3.py   # Training script (temporal split, class balancing)
│   ├── scripts/                  # Feature engineering, threshold tuning, data prep
│   ├── basin_routing.py          # Sub-basin → main-basin grouping reference table
│   └── ims_data/, flow_data/, engineered_*/, organized_data/   # Raw & processed training data
│
├── frontend/                      # Streamlit dashboard
│   ├── app.py                     # Page layout, status banner, role-based tabs
│   ├── components/
│   │   └── risk_map.py            # Interactive Folium risk map + basin detail panel
│   ├── .streamlit/
│   │   └── secrets.toml           # Local-only DB credentials (gitignored, not committed)
│   ├── assets/                    # Logo & favicon
│   └── utils/
│       ├── db_connector.py        # Cached DB queries with retry/offline detection
│       └── permissions.py         # Role-based access control
│
├── scripts/                          # One-off / maintenance scripts
│   ├── simulate_flood_month.py       # Inject a synthetic flood month for demos/testing
│   ├── setup_telegram_session.py     # One-time Telegram auth
│   ├── setup_social_updates_table.py # One-time DB setup for the Social Updates feed
│   ├── setup_alert_log_table.py      # One-time DB setup for alert dedup/all-clear tracking
│   ├── check_roads.py                # Sanity-check basin → road mappings
│   └── test_rss_tool.py              # Smoke-test the RSS news feeds
│
└── data/                             # Static reference data
    ├── basins.geojson                # Basin polygons used by the risk map
    ├── basins_full_data.geojson      # Full basin geometry/attribute set
    ├── roads_data.json               # Road network for affected-roads lookup
    └── ims_to_db_mapping.csv         # IMS station → basin mapping
```

## Setup

1. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

2. **Environment variables** — copy `.env.template` to `.env` and fill in:

   | Variable | Used for |
   |---|---|
   | `GEMINI_API_KEY` / `GEMINI_BACKUP_API_KEY` | LLM powering the CrewAI agents (with fallback) |
   | `IMS_API_KEY` | Israel Meteorological Service rain data |
   | `DATABASE_URL` | Neon PostgreSQL/PostGIS connection string |
   | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Sending alerts to the Telegram channel |
   | `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | Monitoring emergency Telegram channels |
   | `CREWAI_TELEMETRY_ENABLED` | Set to `false` to disable CrewAI telemetry |

3. **Frontend secrets** — create `frontend/.streamlit/secrets.toml` (gitignored, not
   committed) with:

   ```toml
   DATABASE_URL = "your-neon-connection-string"
   ```

   Streamlit reads secrets separately from `.env`, so this needs its own copy.

4. **Telegram monitoring (optional, one-time)**:

   ```bash
   python scripts/setup_telegram_session.py
   ```

## Running the system

- **Full system** — data ingestion + 7-agent pipeline hourly, data-only sync every 10 min:

  ```bash
  python main.py
  ```

- **Dashboard**:

  ```bash
  streamlit run frontend/app.py
  ```

## The Agent Pipeline

| # | Agent | Role | Tools |
|---|---|---|---|
| 1 | Data Engineer | Syncs rain, flow, and forecast data into the database | Sync Rain Data, Sync Flow Data, Update Database Forecasts |
| 2 | Hydrological Analyst | Runs the 16 XGBoost flood models on live data | Run ML Inference on All Basins |
| 3 | OSINT Analyst | Searches the web for real-world flood reports | Search Web and News for Floods |
| 4 | RSS Analyst | Scans Israeli news feeds (Ynet, Walla, Mako, Times of Israel) | Search Israeli News RSS Feeds |
| 5 | Telegram Analyst | Monitors public emergency Telegram channels | Search Telegram Emergency Channels |
| 6 | Warnings Monitor | Parses official IMS weather warnings | Fetch IMS Warnings |
| 7 | Communications Officer | Sends new flood warnings and all-clears, avoiding repeats | Get Alert Plan, Get Affected Roads for Basin, Send Telegram Alert, Log Sent Alert |

The Telegram Analyst relies on an authenticated Telethon user session
(`aegiseco_telegram.session`, created once via `python scripts/setup_telegram_session.py`
— see Setup). If that session ever expires or gets revoked, re-run the setup script to
re-authenticate; the tool will return an error in the meantime without breaking the rest
of the cycle.

The crew runs sequentially in this order. If every LLM attempt fails, `main.py` falls
back to a rule-based check: run ML inference directly and use the same alert plan
(see below) to send a failsafe Telegram alert only for newly-flagged or newly-cleared
basins.

### Alert deduplication & all-clear

The Communications Officer's `alert_task` starts by calling the **Get Alert Plan**
tool, which compares each basin's current `main_basins_status.has_flood_alert` against
the most recent entry for that basin in `alert_log`:

- **New flood warning** — a basin just crossed into alert (or its probability rose by
  ≥15 percentage points since the last warning while still in alert) → send one
  emergency message covering all such basins, then log each as `flood_warning`.
- **All-clear** — a basin that had an active `flood_warning` has dropped back to
  normal → send one stand-down message covering all such basins, then log each as
  `all_clear`.
- **No action** — a basin's alert state hasn't changed since the last logged entry
  (already warned and still in alert, or still normal) → nothing is sent, so an
  ongoing flood doesn't trigger a fresh Telegram message every hour.

## ML Models

- 16 XGBoost classifiers, one per main drainage basin (Harod, Sorek, Ayalon, Beer Sheva,
  Dishon, Gerar, Hadera, Keziv, Kishon, Lachish, Paran, Shikma, Taninim, Yarkon, Zin,
  Alexander), predicting flood probability 1–3 hours ahead.
- Trained on 2010–2019 historical rain (IMS) and flow (Israeli Hydrological Service)
  data with a temporal train/test split to avoid data leakage.
- Each model has its own decision threshold derived from basin-specific flow-duration
  curves (`models/scripts/find_threshold.py`).
- Feature engineering (`models/scripts/merge_and_lag_v2.py`): spatial rain statistics,
  flow lags, soil-moisture EWM, rolling rain sums, and cyclical seasonality encoding.
- `src/database/db_manager.get_live_features_for_model()` reproduces this pipeline from
  live database data for real-time inference.

## Dashboard

The Streamlit dashboard (`frontend/app.py`) shows a live system-status banner (green/red
based on `main_basins_status.has_flood_alert`) and a set of tabs whose visibility depends
on the selected role:

| Tab | Citizen | City | Authority |
|---|---|---|---|
| Risk Map | ✅ | ✅ | ✅ |
| City Control Center | | ✅ | ✅ |
| Councils Info | | | ✅ |
| System Logs | | | ✅ |
| Social Updates | ✅ | ✅ | ✅ |

The role selector in the sidebar is currently a free "view-as" switcher (no real
authentication) — see `frontend/utils/permissions.py` for the access table.

- **Risk Map** (`frontend/components/risk_map.py`) — an interactive Folium map of all
  sub-basins, colored by live ML alert status. Clicking a basin shows its main basin,
  flood probability, and affected roads.
- **City Control Center** — per-municipality flood status and 6-hour rainfall forecasts.
- **Councils Info** — raw view of the `councils` table.
- **System Logs** — placeholder for a future live agent-activity feed.
- **Social Updates** — one card per intel-gathering agent (OSINT, RSS, Telegram, Warnings
  Monitor) plus a card for the Communications Officer's alert decisions, each showing its
  most recent check-in: a humanized summary (e.g. "Checked Ynet, Walla, and Mako for
  flood-related news — nothing found", or "Sent new flood warning for Harod (99%)"), a
  relative timestamp, a status badge (FINDINGS / ALL CLEAR / UNAVAILABLE), and an
  expandable list of what it found. Backed by the `social_updates` table, written to by
  the agent tools in `src/crew/tools/data_tools.py` and `src/crew/tools/db_tools.py`.

## Database

Neon PostgreSQL + PostGIS. Key tables/views:

- `rain_measurements`, `raw_flow_measurements` — raw 10-minute/hourly sensor data
- `raw_hourly_basin_data` — view joining hourly rain and flow per basin, used for ML
  feature extraction
- `basins` — basin geometries, `main_basin_name` groupings, and `main_roads`
- `main_basins_status` — latest ML inference result (alert flag + probability) per main basin
- `settlements` — councils/cities with rainfall forecasts for the City Control Center
- `social_updates` — per-run activity log from the intel-gathering agents (OSINT, RSS,
  Telegram, Warnings Monitor) and the Communications Officer's alert decisions, powering
  the dashboard's Social Updates tab
- `alert_log` — history of flood-warning and all-clear messages sent per basin, used
  to avoid repeating an active alert every hour and to detect when an all-clear is due

## Useful scripts

- `scripts/simulate_flood_month.py` — injects a realistic synthetic flood month into the
  database and runs ML inference against it, for demos/testing without waiting for real rain.
- `scripts/check_roads.py` — verifies every main basin has road data.
- `scripts/test_rss_tool.py` — checks all RSS feeds are reachable and returning results.
- `scripts/setup_telegram_session.py` — one-time Telegram auth (see Setup).
- `scripts/setup_social_updates_table.py` — one-time creation of the `social_updates` table
  used by the Social Updates tab.
- `scripts/setup_alert_log_table.py` — one-time creation of the `alert_log` table used
  for alert deduplication and all-clear tracking.
