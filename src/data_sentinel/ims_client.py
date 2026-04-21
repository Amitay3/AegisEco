import requests
import time
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
load_dotenv()

# Configuration     
API_TOKEN = os.getenv("IMS_API_KEY")
STATION_ID = 21        
BASE_URL = "https://api.ims.gov.il/v1/envista/stations"

headers = {
    'Authorization': f'ApiToken {API_TOKEN}'
}

def get_rain_data_by_station(station_id):
    # 1. Fetch metadata
    meta_url = f"{BASE_URL}/{station_id}"
    meta_response = requests.get(meta_url, headers=headers)
    
    if meta_response.status_code != 200:
        print(f"Error fetching metadata: {meta_response.status_code}")
        return None

    station_info = meta_response.json()
    
    # Extract station-level metadata for the table
    station_name = station_info.get('name')
    region_id = station_info.get('regionId')
    
    rain_channel_id = None
    for monitor in station_info.get('monitors', []):
        if monitor.get('name') == 'Rain':
            rain_channel_id = monitor.get('channelId')
            break

    if not rain_channel_id:
        print(f"Rain channel not found for station {station_id}")
        return None

    # 2. Fetch latest measurement
    data_url = f"{BASE_URL}/{station_id}/data/{rain_channel_id}/latest"
    data_response = requests.get(data_url, headers=headers)

    if data_response.status_code == 200:
        result = data_response.json()
        
        if result.get('data') and len(result['data']) > 0:
            latest_measure = result['data'][0]
            channel_data = latest_measure['channels'][0]
            
            # Map API response to Database fields
            data_record = {
                "station_id": int(station_id),
                "rain_amount_mm": float(channel_data['value']),
                "measurement_time": latest_measure['datetime'],
                "station_name": station_name,
                "region_id": region_id,
                "status": int(channel_data['status'])
            }
            
            return data_record
    else:
        print(f"Error fetching data: {data_response.status_code}")
        return None
    
def get_all_latest_rain_records():
    """
    Fetches the single most recent 10-minute measurement for every station.
    Returns a list of records ready for the db_manager.
    """
    all_latest_records = []
    
    # 1. Get the master list of stations
    response = requests.get(BASE_URL, headers=headers)
    if response.status_code != 200:
        print("Failed to fetch stations list")
        return []

    stations = response.json()

    for station in stations:
        station_id = station.get('stationId')
        station_name = station.get('name')
        region_id = station.get('regionId')
        
        # Find the Rain channel ID
        rain_channel_id = next((m.get('channelId') for m in station.get('monitors', []) 
                                if m.get('name') == 'Rain'), None)

        if not rain_channel_id:
            continue

        # 2. Use the /latest endpoint for this specific channel
        # Format: /stations/{stationId}/data/{channelId}/latest
        data_url = f"{BASE_URL}/{station_id}/data/{rain_channel_id}/latest"
        data_resp = requests.get(data_url, headers=headers)

        if data_resp.status_code == 200 and data_resp.text.strip():
            try:
                data_json = data_resp.json()
                # The /latest endpoint returns the most recent measurement(s) in the 'data' array
                if data_json.get('data') and len(data_json['data']) > 0:
                    measure = data_json['data'][0]
                    channel_data = measure['channels'][0]
                    
                    # Create the record structure for your db_manager
                    data_record = {
                        "station_id": int(station_id),
                        "rain_amount_mm": float(channel_data['value']),
                        "measurement_time": measure['datetime'],
                        "station_name": station_name,
                        "region_id": region_id,
                        "status": int(channel_data['status'])
                    }
                    
                    # Log successful fetch
                    print(f"Fetched Latest: {station_name} | {data_record['rain_amount_mm']}mm")
                    all_latest_records.append(data_record)
                        
            except requests.exceptions.JSONDecodeError:
                        # This happens if the API returns non-JSON text (like an HTML error page)
                        print(f"Station: {station_name} - API returned non-JSON response.")
                
        elif data_resp.status_code == 204:
                    # 204 means "No Content" - the 'proper' way the API tells you there's no data
                    print(f"Station: {station_name} - No data available (204).")
        else:
            # Status 204 means the station is likely offline or hasn't reported recently
            if data_resp.status_code != 204:
                print(f"Station: {station_name} - Failed (Status {data_resp.status_code})")

    print(f"\n Successfully collected {len(all_latest_records)} latest records.")
    return all_latest_records

def get_february_data_all_stations():
    """
    Fetches every 10-minute measurement for February 2026 for all stations.
    """
    all_feb_records = []
    
    # 1. Get the master list of stations
    response = requests.get(BASE_URL, headers=headers)
    if response.status_code != 200:
        print("Failed to fetch stations list")
        return []

    stations = response.json()

    for station in stations:
        station_id = station.get('stationId')
        station_name = station.get('name')
        region_id = station.get('regionId')
        
        rain_channel_id = next((m.get('channelId') for m in station.get('monitors', []) 
                                if m.get('name') == 'Rain'), None)

        if not rain_channel_id:
            continue

        # 2. Use the /monthly endpoint for February 2026
        # Format: /stations/{stationId}/data/{channelId}/monthly/2026/02
        data_url = f"{BASE_URL}/{station_id}/data/{rain_channel_id}/monthly/2026/02"
        data_resp = requests.get(data_url, headers=headers)

        if data_resp.status_code == 200 and data_resp.text.strip():
            try:
                data_json = data_resp.json()
                measurements = data_json.get('data', [])
                
                # IMPORTANT: Loop through ALL measurements in the monthly array
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
                    
                    # Filter out hardware errors (-9999) and invalid data
                    if data_record['rain_amount_mm'] >= 0 and data_record['status'] == 1:
                        all_feb_records.append(data_record)
                        
            except requests.exceptions.JSONDecodeError:
                print(f"Station: {station_name} - API returned non-JSON response.")
        
        # Add a tiny sleep to be polite to the IMS API rate limits
        time.sleep(0.1)

    print(f"\n Total records collected for February: {len(all_feb_records)}")
    return all_feb_records

def get_rain_last_hour(station_id):
    """Calculates total rainfall sum in the last 60 minutes (6 measurements)."""
    
    # 1. Fetch metadata to get station_info
    meta_url = f"{BASE_URL}/{station_id}"
    meta_response = requests.get(meta_url, headers=headers)
    
    if meta_response.status_code != 200:
        print(f"Error fetching metadata: {meta_response.status_code}")
        return 0.0

    station_info = meta_response.json()
    
    # 2. Extract rain_channel_id
    rain_channel_id = None
    for monitor in station_info.get('monitors', []):
        if monitor.get('name') == 'Rain':
            rain_channel_id = monitor.get('channelId')
            break

    if not rain_channel_id:
        print(f"Rain channel not found for station {station_id}")
        return 0.0
        
    # 3. Fetch daily data
    daily_url = f"{BASE_URL}/{station_id}/data/{rain_channel_id}/daily"
    resp = requests.get(daily_url, headers=headers)
    
    if resp.status_code == 200:
        data = resp.json().get('data', [])
        # Get the 6 most recent 10-minute measurements
        recent_6 = data[-6:] 
        total_hour = sum(m['channels'][0]['value'] for m in recent_6 if m['channels'][0]['status'] == 1)
        
        print(f"Station {station_id} | Last Hour Total: {total_hour:.2f}mm")
        return total_hour
    return 0.0

if __name__ == "__main__":
    # get_rain_data_by_station(STATION_ID)
    get_all_latest_rain_records()
    # analyze_rain_trend(STATION_ID)