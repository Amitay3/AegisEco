import os
import numpy as np
from datetime import datetime
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from datetime import datetime, timedelta
from src.data_sentinel.ims_client import get_all_latest_rain_records, get_february_data_all_stations
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def save_ims_batch_to_db(records: list):
    """
    Saves a batch of rain records to the database.
    Ignores records for stations that do not exist in the 'stations' table
    to prevent Foreign Key violation errors.
    """
    if not records:
        print("No records to save.")
        return

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not found in environment.")
        return

    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()

        # Prepare the data tuples for bulk insertion
        values_to_insert = [
            (
                rec['station_id'],
                rec['station_name'],
                rec['measurement_time'],
                rec['rain_amount_mm'],
                rec.get('region_id', None),
                rec.get('status', 1)
            )
            for rec in records
        ]
        # Check which stations are missing from the local database
        cursor.execute("SELECT station_id FROM stations;")
        existing_station_ids = {row[0] for row in cursor.fetchall()}
        
        missing_stations = []
        for rec in records:
            if rec['station_id'] not in existing_station_ids:
                missing_stations.append(f"{rec['station_id']} ({rec['station_name']})")
                
        if missing_stations:
            print(f"Skipping {len(missing_stations)} unregistered stations: {', '.join(missing_stations)}")
            
        # The safe SQL query: 
        # Casts measurement_time to timestamp and filters out unknown stations.
        insert_query = """
            INSERT INTO rain_measurements (
                station_id, station_name, measurement_time, rain_amount_mm, region_id, status
            )
            SELECT v.station_id, v.station_name, v.measurement_time::timestamp, v.rain_amount_mm, v.region_id, v.status
            FROM (VALUES %s) AS v(station_id, station_name, measurement_time, rain_amount_mm, region_id, status)
            WHERE EXISTS (
                SELECT 1 FROM stations s WHERE s.station_id = v.station_id
            )
            ON CONFLICT DO NOTHING;
        """

        # Using execute_values for efficient bulk insert
        execute_values(cursor, insert_query, values_to_insert)
        conn.commit()
        
        # Determine how many rows were actually inserted (optional, but good for logging)
        inserted_count = cursor.rowcount
        print(f"Successfully saved {inserted_count} records to 'rain_measurements'.")

    except Exception as e:
        print(f"Database Error during save: {e}")
        if 'conn' in locals() and conn:
            conn.rollback() # Rollback on error
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals() and conn:
            conn.close()

def save_ims_data_to_db(record):
    if not record:
        print("No record provided to save.")
        return

    try:
        # Connect to the shared cloud database
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cur = conn.cursor()
        
        # SQL Query using named placeholders to match the dictionary keys
        insert_query = """
        INSERT INTO rain_measurements (
            station_id, 
            rain_amount_mm, 
            measurement_time, 
            station_name, 
            region_id, 
            status
        )
        VALUES (
            %(station_id)s, 
            %(rain_amount_mm)s, 
            %(measurement_time)s, 
            %(station_name)s, 
            %(region_id)s, 
            %(status)s
        );
        """
        
        # Execute using the record dictionary directly
        cur.execute(insert_query, record)
        
        print(f"Successfully saved {record['rain_amount_mm']}mm for {record['station_name']} (ID: {record['station_id']})")
        
        cur.close()
        conn.close()

    except Exception as e:
        print(f"Database error: {e}")

def fetch_latest_all_stations():
    records = get_all_latest_rain_records()
    for record in records:
        save_ims_data_to_db(record)

def fetch_feb_records():
    feb_records = get_february_data_all_stations()
    save_ims_batch_to_db(feb_records)


def get_live_features_for_model(basin_name: str) -> pd.DataFrame:
    cutoff_time = datetime.now() - timedelta(days=8)
    
    query = """
        SELECT * FROM raw_hourly_basin_data 
        WHERE basin_name = %(basin_name)s AND measurement_time >= %(cutoff_time)s
        ORDER BY measurement_time ASC;
    """
    
    conn = psycopg2.connect(DATABASE_URL)
    df = pd.read_sql(query, conn, params={"basin_name": basin_name, "cutoff_time": cutoff_time})
    conn.close()

    # --- COLD START FIX: Zero-Padding the Timeline ---
    if df.empty:
        print(f"No data at all for {basin_name}. Cannot run.")
        return None
        
    df['measurement_time'] = pd.to_datetime(df['measurement_time'])
    df.set_index('measurement_time', inplace=True)
    
    # 1. Generate a perfect, unbroken hourly grid for the last 192 hours (8 days)
    # This ends at the timestamp of your latest actual measurement
    latest_time = df.index.max()
    full_time_grid = pd.date_range(end=latest_time, periods=192, freq='h')
    
    # 2. Force your dataframe to fit this grid. Missing past hours become NaNs.
    df = df.reindex(full_time_grid)
    
    # 3. Fill the synthetic past with safe default values (zeros)
    df['basin_name'] = basin_name
    df['basin_rain_mean'] = df['basin_rain_mean'].fillna(0)
    df['basin_intensity_max'] = df['basin_intensity_max'].fillna(0)
    df['basin_rain_std'] = df['basin_rain_std'].fillna(0)
    df['basin_rain_count'] = df['basin_rain_count'].fillna(0)
    df['basin_intensity_mean'] = df['basin_intensity_mean'].fillna(0)
    
    # For flow, assume the river was at its current baseline, or just 0
    # Forward-fill and backward-fill are safer than pure 0 if it's currently flowing
    df['flow'] = df['flow'].bfill().fillna(0) 
    # -------------------------------------------------

    # Now, Pandas has 192 rows to work with, even if 191 of them are synthetically 0.
    # Recreate your exact training features in memory
    
    for lag in [1, 2, 3, 6, 12, 24]:
        df[f'Flow_lag{lag}h'] = df['flow'].shift(lag)
    df['Flow_Rate_of_Change'] = df['flow'].diff().fillna(0)
    df['Flow_Is_Active']      = (df['flow'].shift(1) > 0.1).astype(int)

    for lag in range(1, 7):
        df[f'Basin_Rain_lag{lag}h']      = df['basin_rain_mean'].shift(lag)
        df[f'Basin_Intensity_lag{lag}h'] = df['basin_intensity_max'].shift(lag)
    df['Rain_Acceleration'] = df['basin_rain_mean'].diff().fillna(0)

    df['Soil_Moisture_EWM'] = df['basin_rain_mean'].ewm(alpha=0.02, adjust=False).mean().shift(1)
    df['Rolling_Rain_24h']  = df['basin_rain_mean'].rolling(24).sum().shift(1)
    df['Rolling_Rain_72h']  = df['basin_rain_mean'].rolling(72).sum().shift(1)
    df['Rolling_Rain_168h'] = df['basin_rain_mean'].rolling(168).sum().shift(1)

    df['Month_Sin']       = np.sin(2 * np.pi * df.index.month / 12)
    df['Month_Cos']       = np.cos(2 * np.pi * df.index.month / 12)
    df['Hour_Sin']        = np.sin(2 * np.pi * df.index.hour / 24)
    df['Hour_Cos']        = np.cos(2 * np.pi * df.index.hour / 24)
    df['Is_Early_Winter'] = df.index.month.isin([10, 11]).astype(int)
    df['Is_Peak_Winter']  = df.index.month.isin([12, 1, 2]).astype(int)
    df['Is_Summer']       = df.index.month.isin([6, 7, 8, 9]).astype(int)

    df.rename(columns={
        'basin_rain_mean': 'Basin_Rain_Mean',
        'basin_intensity_max': 'Basin_Intensity_Max',
        'basin_rain_std': 'Basin_Rain_Std',
        'basin_rain_count': 'Basin_Rain_Count',
        'basin_intensity_mean': 'Basin_Intensity_Mean'
    }, inplace=True)

    df['Basin_Rain_Max'] = df['Basin_Intensity_Max']
    
    df = df.dropna()

    # Extract the very last row for the model
    latest_feature_vector = df.iloc[[-1]]
    
    return latest_feature_vector


if __name__ == "__main__":
    # Pick a basin you know you mapped in the SQL table
    test_basin = "Zin" 
    
    print(f"Testing feature extraction for basin: {test_basin}...")
    
    # Run the function
    latest_features = get_live_features_for_model(test_basin)
    
    if latest_features is not None:
        print("\n✅ SUCCESS! Feature vector generated.")
        print(f"Shape: {latest_features.shape} (Should be 1 row, ~38 columns)")
        
        print("\n--- LATEST FEATURE VECTOR ---")
        # Printing it transposed (.T) so it reads vertically like a list, 
        # otherwise Pandas will truncate columns in the console.
        print(latest_features.T)
        
        # Quick validation check:
        expected_cols = [
            'Basin_Rain_Mean', 'Basin_Intensity_Max', 'Flow_lag1h', 
            'Rolling_Rain_168h', 'Is_Peak_Winter'
        ]
        missing = [col for col in expected_cols if col not in latest_features.columns]
        if missing:
            print(f"\n⚠️ WARNING: Missing expected columns: {missing}")
        else:
            print("\n✅ All core features are present and correctly capitalized!")
            
    else:
        print("\n❌ FAILED: Function returned None. Check if the raw tables have data.")