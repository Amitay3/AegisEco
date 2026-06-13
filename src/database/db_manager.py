import os
from litellm import query
import numpy as np
from datetime import datetime
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values, Json
from dotenv import load_dotenv
from datetime import datetime, timedelta
from src.data_sentinel.ims_client import get_all_latest_rain_records, get_february_data_all_stations
from sqlalchemy import create_engine

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def save_ims_batch_to_db(records: list):
    """
    Saves a batch of rain records to the database.
    Prints skipped records that were ignored due to ON CONFLICT.
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

        cursor.execute("SELECT station_id FROM stations;")
        existing_station_ids = {row[0] for row in cursor.fetchall()}
        
        missing_stations = []
        for rec in records:
            if rec['station_id'] not in existing_station_ids:
                missing_stations.append(f"{rec['station_id']} ({rec['station_name']})")
                
        if missing_stations:
            print(f"\nSkipping {len(missing_stations)} unregistered stations: {', '.join(missing_stations)}")
            
        insert_query = """
            INSERT INTO rain_measurements (
                station_id, station_name, measurement_time, rain_amount_mm, region_id, status
            )
            SELECT v.station_id, v.station_name, v.measurement_time::timestamp, v.rain_amount_mm, v.region_id, v.status
            FROM (VALUES %s) AS v(station_id, station_name, measurement_time, rain_amount_mm, region_id, status)
            WHERE EXISTS (
                SELECT 1 FROM stations s WHERE s.station_id = v.station_id
            )
            ON CONFLICT DO NOTHING
            RETURNING station_id;
        """

        returned_rows = execute_values(cursor, insert_query, values_to_insert, fetch=True)
        conn.commit()
        
        inserted_station_ids = {row[0] for row in returned_rows} if returned_rows else set()
        
        ignored_records = []
        for rec in records:
            if rec['station_id'] in existing_station_ids and rec['station_id'] not in inserted_station_ids:
                ignored_records.append(rec)
                
        if ignored_records:
            print("\nFetched But Not Saved:")
            for rec in ignored_records:
                print(f"    {rec['station_name']} | {rec['rain_amount_mm']}mm | {rec['measurement_time']} | Reason: Already Exists (ON CONFLICT)")
                
        print(f"\nSuccessfully saved {len(inserted_station_ids)} new records to 'rain_measurements'.")

    except Exception as e:
        print(f"Database Error during save: {e}")
        if 'conn' in locals() and conn:
            conn.rollback()
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals() and conn:
            conn.close()

def save_social_update_to_db(agent_name: str, source_type: str, status: str, summary: str, details: list = None):
    """
    Records one "activity" row for an intel-gathering agent (RSS, Telegram,
    OSINT, Warnings Monitor) so the dashboard's Social Updates feed can show
    what each agent last did, even when nothing was found.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not found in environment.")
        return

    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO social_updates (agent_name, source_type, status, summary, details)
            VALUES (%s, %s, %s, %s, %s);
            """,
            (agent_name, source_type, status, summary, Json(details) if details is not None else None)
        )
        conn.commit()
    except Exception as e:
        print(f"Error saving social update: {e}")
        if 'conn' in locals() and conn:
            conn.rollback()
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
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cur = conn.cursor()
        
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


def get_live_features_for_model(basin_name: str, reference_time: datetime = None) -> pd.DataFrame:
    if reference_time is None:
        reference_time = datetime.now()
    cutoff_time = reference_time - timedelta(days=8)
    
    query = """
        SELECT * FROM raw_hourly_basin_data
        WHERE basin_name = %(basin_name)s
          AND measurement_time >= %(cutoff_time)s
          AND measurement_time <= %(reference_time)s
        ORDER BY measurement_time ASC;
    """
    
    safe_db_url = DATABASE_URL.replace("postgres://", "postgresql://")
    engine = create_engine(safe_db_url, pool_pre_ping=True)
    df = pd.read_sql(query, engine, params={"basin_name": basin_name, "cutoff_time": cutoff_time, "reference_time": reference_time})

    if df.empty:
        print(f"No data at all for {basin_name}. Cannot run.")
        return None
        
    df['measurement_time'] = pd.to_datetime(df['measurement_time'])
    df.set_index('measurement_time', inplace=True)
    

    ref_ts = pd.Timestamp(reference_time)
    db_latest = df.index.max()
    # Align timezone-awareness so the comparison doesn't raise
    if db_latest.tzinfo is None and ref_ts.tzinfo is not None:
        ref_ts = ref_ts.tz_localize(None)
    elif db_latest.tzinfo is not None and ref_ts.tzinfo is None:
        ref_ts = ref_ts.tz_localize(db_latest.tzinfo)
    latest_time = min(db_latest, ref_ts)
    full_time_grid = pd.date_range(end=latest_time, periods=192, freq='h')
    
    df = df.reindex(full_time_grid)
    
    df['basin_name'] = basin_name
    df['basin_rain_mean'] = df['basin_rain_mean'].fillna(0)
    df['basin_intensity_max'] = df['basin_intensity_max'].fillna(0)
    df['basin_rain_std'] = df['basin_rain_std'].fillna(0)
    df['basin_rain_count'] = df['basin_rain_count'].fillna(0)
    df['basin_intensity_mean'] = df['basin_intensity_mean'].fillna(0)

    df['flow'] = df['flow'].bfill().fillna(0) 
    
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

    latest_feature_vector = df.iloc[[-1]]
    
    return latest_feature_vector


if __name__ == "__main__":
    test_basin = "Zin" 
    
    print(f"Testing feature extraction for basin: {test_basin}...")
    
    latest_features = get_live_features_for_model(test_basin)
    
    if latest_features is not None:
        print("\n✅ SUCCESS! Feature vector generated.")
        print(f"Shape: {latest_features.shape} (Should be 1 row, ~38 columns)")
        
        print("\n--- LATEST FEATURE VECTOR ---")

        print(latest_features.T)
        
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