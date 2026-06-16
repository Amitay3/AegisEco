"""
One-time setup: create the 'alert_log' table used to track which basins have
an active flood warning, so the Communications Officer doesn't repeat the
same warning every hour and can send an all-clear once conditions improve.
Run from the project root: python scripts/setup_alert_log_table.py
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from dotenv import load_dotenv

load_dotenv()

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS alert_log (
    id SERIAL PRIMARY KEY,
    main_basin_name VARCHAR(50) NOT NULL,
    alert_type VARCHAR(20) NOT NULL CHECK (alert_type IN ('flood_warning', 'all_clear')),
    flood_probability NUMERIC,
    sent_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_log_basin_sent
    ON alert_log (main_basin_name, sent_at DESC);
"""

def main():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not set.")
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
        conn.commit()
        print("alert_log table is ready.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
