import os
import requests
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from dotenv import load_dotenv
from crewai.tools import tool
import re
from duckduckgo_search import DDGS
from datetime import datetime
from crewai.tools import tool
from langchain_community.tools import DuckDuckGoSearchResults

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from datetime import timezone, timedelta

# Internal Imports
from src.data_sentinel.ims_client import get_all_latest_rain_records
from src.database.db_manager import save_ims_batch_to_db
from src.data_sentinel.flow_ingestor import AegisEcoDataIngestor

WARNINGS_URL = "https://ims.gov.il/sites/default/files/ims_data/rss/alert/rssAlert_general_country_en.xml"
FORECAST_URL = "https://ims.gov.il/sites/default/files/ims_data/xml_files/isr_cities_1week_6hr_forecast.xml" 

# Use absolute pathing
MAPPING_FILE = os.path.join(os.getcwd(), "data", "ims_to_db_mapping.csv")

# Tool 1: Sync Rain Data from IMS to Database
@tool("Sync Rain Data")
def sync_rain_data_tool() -> str:
    """
    Fetches the latest 10-minute measurements from the IMS API and saves them 
    directly to the PostGIS database.
    Use this tool to perform the entire data ingestion process in one step.
    """
    records = get_all_latest_rain_records()
    
    if not records:
        return "Warning: Failed to fetch records from IMS or no records available."
    
    save_ims_batch_to_db(records)
    return f"Success: Fetched {len(records)} records from IMS and saved to the database."

# Tool 2: Fetch Active IMS Warnings
@tool("Fetch IMS Warnings")
def fetch_ims_warnings_tool() -> str:
    """
    Fetches active weather warnings from the IMS RSS feed.
    Filters out warnings that have already expired based on the 'until' timestamp.
    Returns a text summary of active warnings.
    """
    try:
        response = requests.get(WARNINGS_URL, timeout=10)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        items = root.findall('.//item')
        
        if not items:
            return "No active warnings currently in the IMS feed."
            
        # Define Israel timezone for accurate expiration checking against local time (LT)
        try:
            israel_tz = ZoneInfo("Asia/Jerusalem")
        except NameError:
            israel_tz = timezone(timedelta(hours=3))
            
        now = datetime.now(israel_tz)
        active_warnings_count = 0
        warnings_text = "Active IMS Warnings found:\n"
        
        for item in items:
            # Smart extraction of text even from embedded HTML tags
            title_elem = item.find('title')
            title = "".join(title_elem.itertext()).strip() if title_elem is not None else 'No Title'
            
            desc_elem = item.find('description')
            description = "".join(desc_elem.itertext()).strip() if desc_elem is not None else 'No Description'
            
            # Extract the expiration time using Regex: 'until DD/MM HH'
            match = re.search(r'until\s+(\d{2})/(\d{2})\s+(\d{2})', description)
            if match:
                day = int(match.group(1))
                month = int(match.group(2))
                hour = int(match.group(3))
                year = now.year
                
                # Handle edge case: warning issued in December valid until January
                if month == 1 and now.month == 12:
                    year += 1
                    
                try:
                    expiration_time = datetime(year, month, day, hour, 0, tzinfo=israel_tz)
                    
                    # If current time is strictly greater than expiration time, skip this warning
                    if now > expiration_time:
                        continue
                except ValueError:
                    pass
            
            # Add to text only if it hasn't expired or didn't match the regex format
            active_warnings_count += 1
            warnings_text += f"- Title: {title}\n  Details: {description}\n\n"
            
        if active_warnings_count == 0:
            return "No active warnings currently in the IMS feed."
            
        return warnings_text
        
    except Exception as e:
        return f"Error fetching warnings: {str(e)}"

# Helper function for Tool 3
def _get_target_time_windows():
    """Helper: Calculates the current and next 6-hour IMS forecast windows."""
    now = datetime.now()
    hour = now.hour
    
    if hour >= 21:
        current_hour, next_hour = 21, 3
        current_date, next_date = now, now + timedelta(days=1)
    elif hour >= 15:
        current_hour, next_hour = 15, 21
        current_date, next_date = now, now
    elif hour >= 9:
        current_hour, next_hour = 9, 15
        current_date, next_date = now, now
    elif hour >= 3:
        current_hour, next_hour = 3, 9
        current_date, next_date = now, now
    else:
        current_hour, next_hour = 21, 3
        current_date, next_date = now - timedelta(days=1), now

    current_window_str = current_date.replace(hour=current_hour, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S")
    next_window_str = next_date.replace(hour=next_hour, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S")
    
    return current_window_str, next_window_str

# Parse the IMS forecast XML for tool 3
def _parse_xml_to_dict():
    """Helper: Fetches XML and returns a dictionary of {IMS_LocationId: (CurrentRain, NextRain)}"""
    response = requests.get(FORECAST_URL, timeout=10)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    
    current_window, next_window = _get_target_time_windows()
    forecast_dict = {}
    
    for location in root.findall('.//Location'):
        meta = location.find('LocationMetaData')
        if meta is None: continue
            
        loc_id = meta.find('LocationId').text
        current_rain = 0.0
        next_rain = 0.0
        
        data_node = location.find('LocationData')
        if data_node is not None:
            for forecast in data_node.findall('Forecast'):
                f_time = forecast.find('ForecastTime').text
                rain_node = forecast.find('Rain')
                
                if rain_node is not None and rain_node.text:
                    rain_amount = float(rain_node.text)
                else:
                    rain_amount = 0.0
                
                if f_time == current_window:
                    current_rain = rain_amount
                elif f_time == next_window:
                    next_rain = rain_amount
                    
        forecast_dict[loc_id] = (current_rain, next_rain)
        
    return forecast_dict

# Tool 3: Update Forecasts in Database
@tool("Update Database Forecasts")
def update_forecasts_tool() -> str:
    """
    Fetches the latest 6-hour rainfall forecasts for 80 cities from the IMS XML feed,
    cross-references them with the internal mapping file, and updates the 'current_6h_forecast' 
    and 'next_6h_forecast' columns in the 'settlements' database table.
    Returns a success or error message.
    """
    load_dotenv()
    
    try:
        mapping_df = pd.read_csv(MAPPING_FILE)
    except FileNotFoundError:
        return f"Error: Could not find mapping file at '{MAPPING_FILE}'."

    mapping_df = mapping_df.dropna(subset=['Matched_DB_ID'])
    forecast_dict = _parse_xml_to_dict()
    
    update_data = []
    for index, row in mapping_df.iterrows():
        ims_id = str(row['IMS_ID'])
        db_id = int(row['Matched_DB_ID'])
        
        if ims_id in forecast_dict:
            current_rain, next_rain = forecast_dict[ims_id]
            update_data.append((current_rain, next_rain, db_id))
    
    if not update_data:
        return "Warning: No valid matches found to update."
        
    db_url = os.getenv("DATABASE_URL")
    
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        update_query = """
            UPDATE settlements AS s
            SET 
                current_6h_forecast = v.current_rain,
                next_6h_forecast = v.next_rain
            FROM (VALUES %s) AS v(current_rain, next_rain, settlement_id)
            WHERE s.settlement_id = v.settlement_id;
        """
        
        execute_values(cursor, update_query, update_data)
        conn.commit()
        return f"Database successfully updated with the latest forecasts for {len(update_data)} locations."
        
    except Exception as e:
        return f"Database Error during update: {str(e)}"
    finally:
        if 'conn' in locals() and conn:
            cursor.close()
            conn.close()

# Tool 4: Sync Flow Data from Weather2Day API to Database
@tool("Sync Flow Data")
def sync_flow_data_tool() -> str:
    """
    Fetches the latest river flow measurements from the Weather2Day API 
    and saves them directly to the PostGIS database.
    """
    try:
        ingestor = AegisEcoDataIngestor()
        live_map_data = ingestor.fetch_live_data()
        
        if not live_map_data:
            return "Warning: No flow data fetched from API."
            
        ingestor.save_to_neon(live_map_data)
        return f"Success: Fetched and saved {len(live_map_data)} river flow records to the database."
    except Exception as e:
        return f"Error syncing flow data: {str(e)}"
    

@tool("Search Israeli News RSS Feeds")
def search_israeli_rss_tool() -> str:
    """
    Fetches and searches major Israeli news RSS feeds (Ynet, Walla, Mako, N12, Times of Israel)
    for flash flood reports published in the last 24 hours.
    No input required — searches all feeds automatically.
    """
    import feedparser

    FEEDS = {
        "Ynet":             "https://www.ynet.co.il/Integration/StoryRss2.xml",
        "Walla":            "https://rss.walla.co.il/feed/1",
        "Mako (Ch12)":      "https://rss.mako.co.il/rss/News-n.xml",
        "Times of Israel":  "https://www.timesofisrael.com/feed/",
    }

    FLOOD_KEYWORDS = [
        "שיטפון", "שיטפונות", "הצפה", "הצפות", "נחל", "ניקוז",
        "flood", "flash flood", "flooding", "wadi", "overflow",
        "גשם", "עדשת מים", "נגר", "מי גשם"
    ]

    cutoff = datetime.now() - timedelta(hours=24)
    found = []

    for source, url in FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                text = (title + " " + summary).lower()

                if not any(kw.lower() in text for kw in FLOOD_KEYWORDS):
                    continue

                published = entry.get("published_parsed")
                if published:
                    pub_dt = datetime(*published[:6])
                    if pub_dt < cutoff:
                        continue

                link = entry.get("link", "")
                found.append(f"[{source}] {title}\n  {link}")

        except Exception as e:
            found.append(f"[{source}] Error fetching feed: {e}")

    if not found:
        return "No flood-related articles found in Israeli news RSS feeds in the past 24 hours."

    return f"Found {len(found)} flood-related article(s) in Israeli news feeds:\n\n" + "\n\n".join(found)


@tool("Search Telegram Emergency Channels")
def search_telegram_channels_tool() -> str:
    """
    Searches public Israeli Telegram emergency channels for flood-related messages
    posted in the last 24 hours. Requires TELEGRAM_API_ID, TELEGRAM_API_HASH,
    and an authenticated session file (run scripts/setup_telegram_session.py once).
    """
    from telethon.sync import TelegramClient

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")

    if not api_id or not api_hash:
        return "Error: TELEGRAM_API_ID or TELEGRAM_API_HASH missing from environment."

    CHANNELS = [
        "pikud_haoref",      # IDF Home Front Command
        "mdais",             # Magen David Adom
        "meteo_tech",        # MeteoTech weather alerts
        "rainil",            # Rain alerts Israel
    ]

    FLOOD_KEYWORDS = [
        "שיטפון", "הצפה", "נחל", "גשם חזק", "אזהרה", "סכנה",
        "flood", "flash flood", "wadi", "alert", "warning"
    ]

    session_path = os.path.join(os.getcwd(), "aegiseco_telegram")
    cutoff = datetime.now() - timedelta(hours=24)
    results = []

    try:
        with TelegramClient(session_path, int(api_id), api_hash) as client:
            for channel in CHANNELS:
                try:
                    messages = client.get_messages(channel, limit=100)
                    for msg in messages:
                        if not msg.date or not msg.text:
                            continue
                        msg_time = msg.date.replace(tzinfo=None)
                        if msg_time < cutoff:
                            continue
                        if any(kw.lower() in msg.text.lower() for kw in FLOOD_KEYWORDS):
                            results.append(
                                f"[@{channel} | {msg_time.strftime('%H:%M')}]\n{msg.text[:300]}"
                            )
                except Exception as e:
                    results.append(f"[@{channel}] Could not fetch: {e}")

    except Exception as e:
        return f"Telegram client error: {e}. Run scripts/setup_telegram_session.py to authenticate."

    if not results:
        return "No flood-related messages found in Telegram emergency channels in the past 24 hours."

    return f"Found {len(results)} flood-related Telegram message(s):\n\n" + "\n\n".join(results)


@tool("Search Web and News for Floods")
def search_flood_news_tool(query: str) -> str:
    """
    Searches the open web and news sites for real-time reports of flash floods.
    Input should be a specific search query (e.g., 'Israel flash flood Harod', 'שיטפון בנחל').
    """
    current_date = datetime.now().strftime("%B %Y")
    enhanced_query = f"{query} {current_date}"
    
    try:
        with DDGS() as ddgs:            
            results = list(ddgs.text(enhanced_query, max_results=5, timelimit='d'))
            
        if not results:
            return f"No recent news found from the past day for query: '{enhanced_query}'."
            
        formatted_results = f"Search Results for '{enhanced_query}' (Past day ONLY):\n"
        for r in results:
            formatted_results += f"- Title: {r.get('title')}\n  Snippet: {r.get('body')}\n  Link: {r.get('href')}\n\n"
            
        return formatted_results
        
    except Exception as e:
        return f"Error performing search: {str(e)}"