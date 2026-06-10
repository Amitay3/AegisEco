"""
Populate the two underlying tables that feed the raw_hourly_basin_data view:
  • rain_measurements       (aggregated per basin via ims_station_basin_mapping)
  • raw_flow_measurements   (direct basin-level flow)

Run from the project root:
    python scripts/simulate_flood_month.py

Then run a single pipeline cycle:
    python main.py          (press Ctrl+C after the first cycle completes)

Storm timeline (relative to NOW):
    > 9 days ago  : dry baseline
    6 – 9 days ago: pre-storm buildup
    2 – 6 days ago: flood peak        ← fully inside the 8-day ML window
    0 – 2 days ago: slow recession    ← still above threshold → models fire
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()  # must run before any db_manager imports so DATABASE_URL is set
np.random.seed(42)

# ── Configure which basins flood ───────────────────────────────
FLOOD_BASINS = ["Harod", "Sorek", "Ayalon"]

ALL_BASINS = [
    "Beer Sheva", "Harod", "Sorek", "Alexander", "Ayalon", "Dishon",
    "Gerar", "Hadera", "Keziv", "Kishon", "Lachish", "Paran",
    "Shikma", "Taninim", "Yarkon", "Zin",
]

DAYS_OF_HISTORY = 35   # >= 8 so all ML rolling features have enough history

# Anchor the simulation to a winter date so seasonal features fire correctly.
# get_live_features_for_model will be called with this same reference time.
REFERENCE_TIME = datetime(2026, 1, 20, 12, 0, 0, tzinfo=timezone.utc)

# Storm phase boundaries (days before REFERENCE_TIME)
BUILDUP_START = 9
PEAK_START    = 6


def _phase_values(days_before_end: float, is_flood: bool) -> tuple[float, float]:
    """Return (rain_mm, flow_m3s) for a given phase."""
    if not is_flood:
        rain = max(0.0, np.random.normal(0.1, 0.2)) if np.random.random() < 0.12 else 0.0
        flow = max(0.05, np.random.normal(0.15, 0.07))
        return rain, flow

    if days_before_end > BUILDUP_START:
        rain = max(0.0, np.random.normal(0.1, 0.2)) if np.random.random() < 0.08 else 0.0
        flow = max(0.05, np.random.normal(0.25, 0.08))

    elif days_before_end > PEAK_START:
        p = (BUILDUP_START - days_before_end) / (BUILDUP_START - PEAK_START)
        # Rain only 35% of hours during buildup — bursty, not continuous
        rain = max(0.0, np.random.normal(0.8 + 4.0 * p, 1.0)) if np.random.random() < 0.35 else 0.0
        flow = max(0.1,  np.random.normal(0.5 + 5.0 * p, 0.8))

    else:
        # Peak extends to the current moment so the model sees active flood conditions
        # Rain 60% of hours — heavy but bursty
        rain = max(0.0, np.random.normal(6.0, 2.0)) if np.random.random() < 0.60 else 0.0
        flow = max(0.0,  np.random.normal(10.0, 2.0))

    return rain, flow


def main():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not set.")
        sys.exit(1)

    now          = REFERENCE_TIME
    window_start = now - timedelta(days=DAYS_OF_HISTORY + 1)

    print(f"Simulation range : {window_start.strftime('%Y-%m-%d')} → {now.strftime('%Y-%m-%d %H:%M UTC')} (winter anchor)")
    print(f"Flood basins     : {', '.join(FLOOD_BASINS)}")
    print(f"Storm timeline   : buildup {BUILDUP_START}d ago → peak {PEAK_START}d ago → now (active peak)\n")

    conn = psycopg2.connect(db_url)
    cur  = conn.cursor()

    # ── Step 1: fetch one representative station per basin ────────
    # ims_station_basin_mapping.basin_name already holds main basin names
    cur.execute(
        """
        SELECT DISTINCT ON (basin_name) station_id, station_name, basin_name
        FROM ims_station_basin_mapping
        WHERE basin_name != 'Unmapped'
        ORDER BY basin_name, station_id
        """
    )
    station_rows = cur.fetchall()
    basin_to_station = {row[2]: (row[0], row[1]) for row in station_rows}

    missing = [b for b in ALL_BASINS if b not in basin_to_station]
    if missing:
        print(f"⚠️  No station mapping found for: {', '.join(missing)}")
        print("   These basins will have rain_mean=0 in the view (flow still simulated).\n")

    # ── Step 2: clear existing rows in simulation range ────────
    cur.execute(
        "DELETE FROM rain_measurements WHERE measurement_time >= %s AND measurement_time <= %s",
        (window_start, now),
    )
    print(f"Cleared {cur.rowcount:,} rows from rain_measurements.")

    cur.execute(
        "DELETE FROM raw_flow_measurements WHERE measurement_time >= %s AND measurement_time <= %s",
        (window_start, now),
    )
    print(f"Cleared {cur.rowcount:,} rows from raw_flow_measurements.\n")

    # ── Step 3: generate and insert data ───────────────────────
    rain_rows = []
    flow_rows = []

    total_hours = DAYS_OF_HISTORY * 24
    current = window_start

    while current <= now:
        for basin in ALL_BASINS:
            days_before_end = (now - current).total_seconds() / 86400
            is_flood        = basin in FLOOD_BASINS
            rain, flow      = _phase_values(days_before_end, is_flood)

            # rain_measurements — one row per station per hour
            if basin in basin_to_station:
                station_id, station_name = basin_to_station[basin]
                rain_rows.append((
                    station_id,
                    station_name,
                    current,
                    round(rain, 4),
                    None,   # region_id — nullable
                    1,      # status
                ))

            # raw_flow_measurements — one row per basin per hour
            flow_rows.append((
                basin,
                current,
                round(float(flow), 4),
                None,   # original_hebrew_name — nullable
            ))

        current += timedelta(hours=1)

    # Insert rain in batches
    rain_sql = """
        INSERT INTO rain_measurements
            (station_id, station_name, measurement_time, rain_amount_mm, region_id, status)
        VALUES %s
        ON CONFLICT DO NOTHING
    """
    execute_values(cur, rain_sql, rain_rows, page_size=1000)
    print(f"Inserted {len(rain_rows):,} rows into rain_measurements.")

    # Insert flow in batches
    flow_sql = """
        INSERT INTO raw_flow_measurements
            (basin_name, measurement_time, flow_m3s, original_hebrew_name)
        VALUES %s
        ON CONFLICT DO NOTHING
    """
    execute_values(cur, flow_sql, flow_rows, page_size=1000)
    print(f"Inserted {len(flow_rows):,} rows into raw_flow_measurements.")

    conn.commit()
    cur.close()
    conn.close()

    print(f"\nTotal: {len(rain_rows) + len(flow_rows):,} rows across both tables.")
    print(f"({total_hours}h × {len(ALL_BASINS)} basins)\n")

    print("── ML inference self-test (reference_time = simulation anchor) ─")
    from src.crew.tools.db_tools import _run_all_basins_inference
    from src.database.db_manager import get_live_features_for_model
    print(_run_all_basins_inference(reference_time=REFERENCE_TIME))

    print("\n── Feature vectors for flood basins ────────────────────────")
    for basin in FLOOD_BASINS:
        df = get_live_features_for_model(basin, reference_time=REFERENCE_TIME)
        if df is not None:
            print(f"\n[{basin}]")
            print(df.T.to_string())
        else:
            print(f"\n[{basin}] ⚠️  No features returned")

    print("\n── To restore real data ────────────────────────────────────")
    print(f"    DELETE FROM rain_measurements")
    print(f"      WHERE measurement_time >= '{window_start.date()}';")
    print(f"    DELETE FROM raw_flow_measurements")
    print(f"      WHERE measurement_time >= '{window_start.date()}';")
    print("\n  Then re-run the Data Engineer agent or python main.py")


if __name__ == "__main__":
    main()
