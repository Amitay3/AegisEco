import os
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("IMS_API_KEY")
BASE_URL = "https://api.ims.gov.il/v1/envista/stations"

def _get_ims_session():
    """Creates a robust session for IMS API."""
    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=20, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        'Authorization': f'ApiToken {API_TOKEN}',
        'Content-Type': 'application/json'
    })
    return session

def _fetch_single_station_latest(session, station_id, station_name, region_id, rain_channel_id):
    """Fetches data and returns a categorized dictionary instead of printing directly."""
    data_url = f"{BASE_URL}/{station_id}/data/{rain_channel_id}/latest"
    try:
        response = session.get(data_url, timeout=15)
        
        if response.status_code == 200 and response.text.strip():
            data_json = response.json()
            
            if data_json.get('data') and len(data_json['data']) > 0:
                measure = data_json['data'][0]
                channel_data = measure['channels'][0]
                
                measure_time_str = measure['datetime']
                
                # Parse datetime to check if it's within the last 24 hours
                try:
                    measure_time = datetime.fromisoformat(measure_time_str.replace('Z', '+00:00'))
                    if measure_time.tzinfo is None:
                        measure_time = measure_time.replace(tzinfo=timezone.utc)
                    
                    if datetime.now(timezone.utc) - measure_time > timedelta(hours=24):
                        return {"category": "skipped", "name": station_name, "reason": "Older than 24 hours", "time": measure_time_str}
                except ValueError:
                    pass # Fallback if datetime parsing fails

                data_record = {
                    "station_id": int(station_id),
                    "rain_amount_mm": float(channel_data['value']),
                    "measurement_time": measure_time_str,
                    "station_name": station_name,
                    "region_id": region_id,
                    "status": int(channel_data['status'])
                }
                return {"category": "success", "name": station_name, "amount": data_record['rain_amount_mm'], "time": measure_time_str, "record": data_record}
                
        elif response.status_code == 204:
            return {"category": "error", "name": station_name, "reason": "No data available (204)"}
        else:
            return {"category": "error", "name": station_name, "reason": f"HTTP Error {response.status_code}"}
            
    except requests.exceptions.JSONDecodeError:
        return {"category": "error", "name": station_name, "reason": "API returned non-JSON response"}
    except Exception as e:
        return {"category": "error", "name": station_name, "reason": f"Connection error: {str(e)}"}
        
    return {"category": "error", "name": station_name, "reason": "Unknown error"}

def get_all_latest_rain_records():
    """Fetches records concurrently, categorizes them, prints formatted logs, and returns the valid data."""
    session = _get_ims_session()
    
    try:
        response = session.get(BASE_URL, timeout=10)
        response.raise_for_status()
        stations = response.json()
    except Exception as e:
        print(f"Failed to fetch master stations list: {e}")
        return []

    tasks = []
    results = {"success": [], "error": [], "skipped": []}
    valid_records = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        for station in stations:
            station_id = station.get('stationId')
            station_name = station.get('name')
            region_id = station.get('regionId')
            
            rain_channel_id = next((m.get('channelId') for m in station.get('monitors', []) 
                                    if m.get('name') == 'Rain'), None)

            if rain_channel_id:
                future = executor.submit(
                    _fetch_single_station_latest, session, station_id, station_name, region_id, rain_channel_id
                )
                tasks.append(future)

        for future in as_completed(tasks):
            res = future.result()
            if res:
                results[res["category"]].append(res)
                if res["category"] == "success":
                    valid_records.append(res["record"])

    # --- FORMATTED PRINTING ---
    if results["success"]:
        print("\nFetched Latest:")
        for item in results["success"]:
            rain_text = f"{item['amount']}mm"
            print(f"    {item['name']:<30} | {rain_text:<8} | {item['time']}")
            
    if results["error"]:
        print("\nDid Not Fetch:")
        for item in results["error"]:
            print(f"    {item['name']:<30} | {item['reason']}")
            
    if results["skipped"]:
        print("\nSkipped (Not from last 24h):")
        for item in results["skipped"]:
            print(f"    {item['name']:<30} | {item['time']:<25} | {item['reason']}")

    print(f"\nSuccessfully collected {len(valid_records)} valid, recent records.")
    return valid_records

def get_february_data_all_stations():
    """
    Fetches every 10-minute measurement for February 2026 for all stations.
    Note: Updated to use the robust session without concurrency to respect long historical API limits.
    """
    all_feb_records = []
    session = _get_ims_session()
    
    try:
        response = session.get(BASE_URL, timeout=10)
        response.raise_for_status()
        stations = response.json()
    except Exception as e:
        print("Failed to fetch stations list")
        return []

    for station in stations:
        station_id = station.get('stationId')
        station_name = station.get('name')
        region_id = station.get('regionId')
        
        rain_channel_id = next((m.get('channelId') for m in station.get('monitors', []) 
                                if m.get('name') == 'Rain'), None)

        if not rain_channel_id:
            continue

        data_url = f"{BASE_URL}/{station_id}/data/{rain_channel_id}/monthly/2026/02"
        try:
            data_resp = session.get(data_url, timeout=15)

            if data_resp.status_code == 200 and data_resp.text.strip():
                data_json = data_resp.json()
                measurements = data_json.get('data', [])
                
                for measure in measurements:
                    channel_data = measure['channels'][0]
                    data_record = {
                        "station_id": int(station_id),
                        "rain_amount_mm": float(channel_data['value']),
                        "measurement_time": measure['datetime'],
                        "station_name": station_name,
                        "region_id": region_id,
                        "status": int(channel_data['status'])
                    }
                    
                    if data_record['rain_amount_mm'] >= 0 and data_record['status'] == 1:
                        all_feb_records.append(data_record)
                        
        except requests.exceptions.JSONDecodeError:
            print(f"Did Not Fetch: {station_name} | API returned non-JSON response")
        except Exception as e:
            print(f"Did Not Fetch: {station_name} | Connection error: {str(e)}")
            
        time.sleep(0.1)

    print(f"\n Total records collected for February: {len(all_feb_records)}")
    return all_feb_records

def get_rain_last_hour(station_id):
    """Calculates total rainfall sum in the last 60 minutes."""
    session = _get_ims_session()
    meta_url = f"{BASE_URL}/{station_id}"
    
    try:
        meta_response = session.get(meta_url, timeout=10)
        meta_response.raise_for_status()
        station_info = meta_response.json()
        
        rain_channel_id = next((m.get('channelId') for m in station_info.get('monitors', []) 
                                if m.get('name') == 'Rain'), None)

        if not rain_channel_id:
            print(f"Rain channel not found for station {station_id}")
            return 0.0
            
        daily_url = f"{BASE_URL}/{station_id}/data/{rain_channel_id}/daily"
        resp = session.get(daily_url, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json().get('data', [])
            recent_6 = data[-6:] 
            total_hour = sum(m['channels'][0]['value'] for m in recent_6 if m['channels'][0]['status'] == 1)
            
            print(f"Station {station_id} | Last Hour Total: {total_hour:.2f}mm")
            return total_hour
            
    except Exception as e:
        print(f"Failed to calculate last hour data for {station_id}: {e}")
        
    return 0.0

if __name__ == "__main__":
    get_all_latest_rain_records()