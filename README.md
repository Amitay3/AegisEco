# AegisEco — AI Flash Flood Early Warning System

**Live Dashboard: [aegiseco.streamlit.app](https://aegiseco.streamlit.app)**

AegisEco is an AI-powered flash-flood early-warning system for Israel. It monitors live meteorological and hydrological data around the clock, runs 16 per-basin machine learning flood models, and deploys a 7-agent AI verification pipeline that cross-references real-world reports before broadcasting alerts — minimizing both false alarms and missed events.

---

## The Problem

Flash floods in Israel kill people and cause massive infrastructure damage every year, yet existing alert systems are largely manual, slow, or basin-agnostic. By the time an official warning reaches the public, the flood may already be in motion. AegisEco aims to bridge that gap with automated, continuous, data-driven detection — giving emergency services and the public an earlier signal.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     DATA SOURCES                        │
│   IMS API (rain stations)    Weather2Day (river flow)   │
└────────────────────┬────────────────────────────────────┘
                     │  every 10 minutes
                     ▼
┌─────────────────────────────────────────────────────────┐
│           Neon PostgreSQL + PostGIS Database            │
│  rain_measurements  │  raw_flow_measurements  │  ...    │
└────────────────────┬────────────────────────────────────┘
                     │  every hour
          ┌──────────┴──────────┐
          ▼                     ▼
┌─────────────────┐   ┌────────────────────────────────┐
│  16 XGBoost     │   │     7-Agent CrewAI Pipeline    │
│  ML Models      │   │  (OSINT · RSS · Telegram · IMS │
│  (per basin)    │   │   Warnings · Communications)   │
└────────┬────────┘   └────────────────┬───────────────┘
         └──────────────┬──────────────┘
                        ▼
           ┌────────────────────────┐
           │   Telegram Alerts      │
           │   Streamlit Dashboard  │
           └────────────────────────┘
```

---

## How It Works — End to End

### 1. Live Data Ingestion (`src/data_sentinel/`)

Every 10 minutes, two parallel scrapers run:

- **IMS Client** (`ims_client.py`) — queries the Israel Meteorological Service API concurrently across all rain stations using 10 threads. Each reading includes station ID, rainfall amount, timestamp, and the geographic region it belongs to (`region_id`). Readings older than 24 hours are discarded.
- **Flow Ingestor** (`flow_ingestor.py`) — fetches river flow data from Weather2Day. Hebrew station names are mapped to English basin names via a hardcoded routing table. When multiple stations feed the same basin, the highest flow reading is kept.

Both write into the Neon PostgreSQL database, which aggregates readings into hourly basin-level views for ML consumption.

### 2. Machine Learning Inference (`src/crew/tools/db_tools.py`)

Every hour, 16 XGBoost models run in sequence — one per main drainage basin. Each model:

1. Loads its `.pkl` file containing the trained model, feature names, decision threshold, and flood stage reference.
2. Calls `db_manager.get_live_features_for_model()` to reconstruct the same 38-feature vector used during training (spatial rain stats, flow lags, soil moisture EWM, rolling rain sums, cyclical seasonality).
3. Runs `predict_proba` and compares the output against the basin's own tuned decision threshold.
4. Writes `has_flood_alert` (bool) and `flood_probability` (float) to `main_basins_status`.

The result is a per-basin binary flood flag plus probability, updated every hour.

### 3. AI Verification Pipeline (`src/crew/`)

Once inference completes, a 7-agent CrewAI sequential pipeline verifies and acts on the results:

| # | Agent | What It Does |
|---|---|---|
| 1 | **Data Engineer** | Syncs rain, flow, and city forecast data into the database |
| 2 | **Hydrological Analyst** | Runs the 16 XGBoost models and reports per-basin flood probabilities |
| 3 | **OSINT Analyst** | Searches the web for real-time flood reports using Hebrew and English flood keywords, scoped to Israeli results |
| 4 | **RSS Analyst** | Scans Israeli news feeds (Ynet, Walla, Mako, Times of Israel) for flood-related headlines |
| 5 | **Telegram Analyst** | Monitors public emergency Telegram channels via Telethon |
| 6 | **Warnings Monitor** | Parses official IMS weather warnings |
| 7 | **Communications Officer** | Sends new flood warnings and all-clears via Telegram; avoids duplicates using `alert_log` |

Agents run sequentially — each one's output is available as context to the next. The LLM (Gemini) authors messages and gathers corroborating evidence, but routing decisions (which basins get alerts) are made entirely by deterministic Python logic in `_get_alert_plan()`.

### 4. Alert Logic — Deterministic, Not LLM-Driven

A key design principle: **the LLM decides nothing about who gets alerted.**

`_get_alert_plan()` in `db_tools.py` is pure Python. It compares `main_basins_status` (current ML result) against `alert_log` (last action taken per basin) and produces three lists:

- **New alert** — basin just crossed into flood territory, or its probability rose ≥15 points since last warning → send one message covering all such basins
- **All-clear** — previously-alerted basin returned to normal → send one stand-down message
- **No action** — state unchanged since last logged entry → nothing sent (prevents hourly spam)

The LLM's job is to format the message text and incorporate corroborating evidence from agents 3–6. The decision itself is code.

### 5. Streamlit Dashboard (`frontend/`)

The dashboard shows a live view of the system state, auto-refreshing every 60 seconds.

| Tab | Citizen | City | Authority |
|---|---|---|---|
| Risk Map | ✅ | ✅ | ✅ |
| City Control Center | | ✅ | ✅ |
| Councils Info | | | ✅ |
| Social Updates | ✅ | ✅ | ✅ |

- **Risk Map** — interactive Folium map of all sub-basins, colored red (alert) or blue (normal) based on live ML results. Clicking a basin shows flood probability and affected roads.
- **City Control Center** — per-municipality flood status and 6-hour rainfall forecasts.
- **Social Updates** — one card per agent showing its most recent activity: what it searched, what it found, and what action was taken. Backed by the `social_updates` table.

---

## Machine Learning Details

**16 XGBoost classifiers**, one per main drainage basin:

- **Training data**: 2010–2019 historical IMS rain and Israeli Hydrological Service flow data
- **Target**: binary flood flag (`flow > basin_flood_stage_m3s`) 1–3 hours ahead
- **Split**: temporal at `2016-01-01` (no random split — avoids data leakage in time series)
- **Class imbalance**: handled via `scale_pos_weight = (non-flood hours) / (flood hours)`, which makes the model weight missed floods proportionally more than false positives
- **Per-basin thresholds**: each model has its own `decision_threshold` (ranging from 1% to 30%), tuned from flow-duration curves. A basin flagging at "3% probability" is meaningful — it reflects 30× above that basin's normal baseline, not a human-intuitive percentage.

The live inference pipeline (`db_manager.get_live_features_for_model()`) reproduces all 38 features identically from the live database — matching the offline training pipeline in `models/scripts/merge_and_lag_v2.py`.

---

## Project Structure

```text
AegisEco/
├── main.py                          # Scheduler: full cycle hourly, data-only every 10 min
├── requirements.txt
├── .env.template                    # Environment variable reference
│
├── src/
│   ├── crew/                        # CrewAI agent pipeline
│   │   ├── aegiseco_crew.py         # 7 agents, tools, sequential task order
│   │   ├── config/
│   │   │   ├── agents.yaml          # Agent roles, goals, backstories
│   │   │   └── tasks.yaml           # Task prompts and expected outputs
│   │   └── tools/
│   │       ├── data_tools.py        # Data sync, OSINT search, RSS, Telegram reading
│   │       ├── db_tools.py          # ML inference, rainfall queries, alert plan
│   │       └── alert_tools.py       # Telegram broadcast
│   │
│   ├── data_sentinel/               # Live data ingestion
│   │   ├── ims_client.py            # IMS rain API — concurrent, 10 threads
│   │   └── flow_ingestor.py         # Weather2Day river flow scraper
│   │
│   └── database/
│       └── db_manager.py            # DB connection + live feature engineering for ML
│
├── models/
│   ├── models/*.pkl                 # 16 trained XGBoost models
│   ├── ML pipelines/train_model_v3.py   # Training script
│   ├── scripts/                     # Feature engineering, threshold tuning, data prep
│   └── basin_routing.py             # Sub-basin → main basin routing table
│
├── frontend/
│   ├── app.py                       # Main Streamlit app
│   ├── components/risk_map.py       # Folium map + basin detail panel
│   └── utils/
│       ├── db_connector.py          # Cached DB queries with retry/offline detection
│       └── permissions.py           # Role-based access control
│
├── scripts/
│   ├── simulate_flood_month.py      # Inject synthetic flood data for demos
│   ├── cleanup_simulation.py        # Revert simulate_flood_month.py changes
│   └── setup_telegram_session.py    # One-time Telegram auth for channel monitoring
│
└── data/
    ├── basins.geojson               # Basin polygons for the risk map
    ├── roads_data.json              # Road network for affected-roads lookup
    └── ims_to_db_mapping.csv        # IMS station → basin mapping
```

---

## Database Schema

Neon PostgreSQL + PostGIS. Key tables:

| Table / View | Purpose |
|---|---|
| `rain_measurements` | Raw 10-minute rain readings from IMS stations |
| `raw_flow_measurements` | Raw hourly river flow readings from Weather2Day |
| `raw_hourly_basin_data` | View: joins rain + flow per basin per hour — ML feature source |
| `main_basins_status` | Latest ML result per basin: `has_flood_alert`, `flood_probability`, `last_inference_time` |
| `alert_log` | History of flood warnings and all-clears sent per basin — drives deduplication |
| `social_updates` | Agent activity feed powering the Social Updates dashboard tab |
| `basins` | Basin geometries, sub-basin → main basin grouping, affected roads per basin |
| `settlements` | Councils/cities with 6-hour rainfall forecasts for the City Control Center |

---

## Tech Stack

| Layer | Technology |
|---|---|
| ML models | XGBoost, scikit-learn, pandas, numpy |
| Agent framework | CrewAI (sequential, 7 agents) |
| LLM | Google Gemini 2.5 Flash (with fallback chain) |
| Data ingestion | Python, requests, Telethon, feedparser |
| Web search | DDGS (DuckDuckGo Search — no API key required) |
| Database | Neon PostgreSQL + PostGIS |
| Dashboard | Streamlit, Folium, streamlit-folium |
| Scheduling | APScheduler |
| Deployment | Railway (backend worker + Streamlit web service) |

