"""
One-time setup: create the 'social_updates' table used by the Social Updates feed.
Run from the project root: python scripts/setup_social_updates_table.py
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from dotenv import load_dotenv

load_dotenv()

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS social_updates (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(50) NOT NULL,
    source_type VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    summary TEXT NOT NULL,
    details JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_social_updates_agent_created
    ON social_updates (agent_name, created_at DESC);
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
        print("social_updates table is ready.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
