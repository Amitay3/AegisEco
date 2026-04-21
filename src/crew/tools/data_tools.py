import os
import requests
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from dotenv import load_dotenv
from crewai.tools import tool

# Internal Imports using absolute paths
from src.data_sentinel.ims_client import get_all_latest_rain_records
from src.database.db_manager import save_ims_batch_to_db
from src.data_sentinel.flow_ingestor import AegisEcoDataIngestor


# --- CONSTANTS ---
WARNINGS_URL = "https://ims.gov.il/sites/default/files/ims_data/rss/alert/rssAlert_general_country_en.xml"
FORECAST_URL = "https://ims.gov.il/sites/default/files/ims_data/xml_files/isr_cities_1week_6hr_forecast.xml" 

# Use absolute pathing from the current working directory (AegisEco Root)
MAPPING_FILE = os.path.join(os.getcwd(), "data", "ims_to_db_mapping.csv")

# TOOL 1: SYNC REAL-TIME RAIN DATA
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

# TOOL 2: IMS WARNINGS
@tool("Fetch IMS Warnings")
def fetch_ims_warnings_tool() -> str:
    """
    Fetches active weather warnings from the IMS RSS feed.
    Returns a text summary of active warnings.
    """
    try:
        response = requests.get(WARNINGS_URL, timeout=10)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        items = root.findall('.//item')
        
        if not items:
            return "No active warnings currently in the IMS feed."
            
        warnings_text = "Active IMS Warnings found:\n"
        for item in items:
            title = item.find('title').text if item.find('title') is not None else 'No Title'
            description = item.find('description').text if item.find('description') is not None else 'No Description'
            description = description.replace("<p style='padding-bottom:30px;'>", "").replace("</p>", "").strip()
            
            warnings_text += f"- Title: {title}\n  Details: {description}\n\n"
            
        return warnings_text
        
    except Exception as e:
        return f"Error fetching warnings: {str(e)}"


# TOOL 3: FORECAST UPDATER
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

# TOOL 4: UPDATE CITIES RAIN FORECASTS
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