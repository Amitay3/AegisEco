"""
Test the RSS news tool feed by feed.
Run from the project root:  python scripts/test_rss_tool.py

Shows per-feed: total articles fetched, how many passed the flood keyword filter,
and the matched headlines so you can verify each source is live and working.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import feedparser
from datetime import datetime, timedelta

FEEDS = {
    "Ynet":            "https://www.ynet.co.il/Integration/StoryRss2.xml",
    "Walla":           "https://rss.walla.co.il/feed/1",
    "Mako (Ch12)":     "https://rss.mako.co.il/rss/News-n.xml",
    "Times of Israel": "https://www.timesofisrael.com/feed/",
}

FLOOD_KEYWORDS = [
    "שיטפון", "שיטפונות", "הצפה", "הצפות", "נחל", "ניקוז",
    "flood", "flash flood", "flooding", "wadi", "overflow",
    "גשם", "עדשת מים", "נגר", "מי גשם"
]

cutoff = datetime.now() - timedelta(hours=24)

print(f"Checking RSS feeds — cutoff: past 24h ({cutoff.strftime('%Y-%m-%d %H:%M')})\n")
print("=" * 60)

total_matches = 0

for source, url in FEEDS.items():
    print(f"\n[{source}]")
    print(f"  URL: {url}")

    try:
        feed = feedparser.parse(url)
        entries = feed.entries

        if not entries:
            print(f"  ⚠️  No entries returned — feed may be down or blocked")
            continue

        print(f"  ✅ Fetched {len(entries)} article(s)")

        recent = 0
        matches = []

        for entry in entries:
            title   = entry.get("title", "")
            summary = entry.get("summary", "")
            text    = (title + " " + summary).lower()
            link    = entry.get("link", "")

            published = entry.get("published_parsed")
            if published:
                pub_dt = datetime(*published[:6])
                if pub_dt >= cutoff:
                    recent += 1
                if pub_dt < cutoff:
                    continue

            if any(kw.lower() in text for kw in FLOOD_KEYWORDS):
                matches.append(f"    → {title}\n      {link}")

        print(f"  📅 Articles from past 24h: {recent}")

        if matches:
            print(f"  🚨 Flood keyword matches: {len(matches)}")
            for m in matches:
                print(m)
            total_matches += len(matches)
        else:
            print(f"  ✅ No flood keywords matched (normal if no active floods)")

    except Exception as e:
        print(f"  ❌ Error: {e}")

print("\n" + "=" * 60)
print(f"Total flood keyword matches across all feeds: {total_matches}")
