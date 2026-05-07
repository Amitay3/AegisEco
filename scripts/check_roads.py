"""
Quick check: print affected roads for all 16 main basins.
Run from the project root: python scripts/check_roads.py
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from dotenv import load_dotenv

load_dotenv()

MAIN_BASINS = [
    "Alexander", "Ayalon", "Beer Sheva", "Dishon", "Gerar",
    "Hadera", "Harod", "Keziv", "Kishon", "Lachish",
    "Paran", "Shikma", "Sorek", "Taninim", "Yarkon", "Zin",
]

def check_roads():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not set.")
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    no_roads = []

    for basin in MAIN_BASINS:
        cur.execute(
            """
            SELECT DISTINCT unnest(main_roads) AS road
            FROM basins
            WHERE main_basin_name = %s
              AND main_roads IS NOT NULL
              AND array_length(main_roads, 1) > 0
            ORDER BY road;
            """,
            (basin,)
        )
        rows = cur.fetchall()

        if not rows:
            no_roads.append(basin)
            print(f"\n[{basin}] — no roads found")
        else:
            print(f"\n[{basin}] — {len(rows)} road(s):")
            for (road,) in rows:
                print(f"  - {road}")

    cur.close()
    conn.close()

    print("\n" + "=" * 50)
    if no_roads:
        print(f"Basins with NO roads ({len(no_roads)}): {', '.join(no_roads)}")
    else:
        print("All 16 basins have road data.")

if __name__ == "__main__":
    check_roads()
