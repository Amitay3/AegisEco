import os
import psycopg2
from crewai.tools import tool
from dotenv import load_dotenv
import joblib
import glob
from src.database.db_manager import get_live_features_for_model


load_dotenv()
# Tool 1: Query High Rainfall Events from Database
@tool("Query High Rainfall Events")
def get_high_rainfall_events(threshold_mm: float) -> str:
    """
    Queries the database for any rain measurements that exceeded the given threshold in mm.
    Returns a formatted string of the results to be analyzed by the agent.
    """
    db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        return "Error: DATABASE_URL is missing from environment variables."

    query = """
        SELECT station_name, measurement_time, rain_amount_mm
        FROM rain_measurements
        WHERE rain_amount_mm >= %s
        ORDER BY rain_amount_mm DESC;
    """
    
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        cur.execute(query, (threshold_mm,))
        rows = cur.fetchall()

        if not rows:
            return f"No stations recorded rainfall above {threshold_mm}mm."

        result = f"Found {len(rows)} records exceeding {threshold_mm}mm:\n"
        for row in rows:
            station_name, m_time, rain = row
            result += f"- Station '{station_name}' at {m_time}: {rain}mm\n"

        return result
        
    except Exception as e:
        return f"Database query failed: {e}"
        
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

@tool("Get Affected Roads for Basin")
def get_affected_roads_tool(main_basin_name: str) -> str:
    """
    Queries the database for all roads affected by a flood in the given main basin.
    Input must be the exact main basin name (e.g., 'Harod', 'Sorek', 'Beer Sheva').
    Returns a formatted list of road names, or a message if none are found.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return "Error: DATABASE_URL is missing from environment variables."

    query = """
        SELECT DISTINCT unnest(main_roads) AS road
        FROM basins
        WHERE main_basin_name = %s
          AND main_roads IS NOT NULL
          AND array_length(main_roads, 1) > 0
        ORDER BY road;
    """

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute(query, (main_basin_name,))
        rows = cur.fetchall()

        if not rows:
            return f"No road data found for basin '{main_basin_name}'."

        roads = [row[0] for row in rows]
        return f"Roads affected in {main_basin_name} basin:\n" + "\n".join(f"- {r}" for r in roads)

    except Exception as e:
        return f"Database query failed: {e}"
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()


def _run_all_basins_inference(reference_time=None) -> str:
    """
    Run XGBoost inference for all basins, update the main_basins_status 
    table in the database, and return a formatted report.
    """
    basins_with_models = ["Beer Sheva", "Harod", "Sorek", "Alexander", "Ayalon", "Dishon", "Gerar", "Hadera", "Keziv", "Kishon", "Lachish", "Paran", "Shikma", "Taninim", "Yarkon", "Zin"]
    results_report = ["📊 AegisEco ML Inference Report:\n"]

    models_dir = os.path.join(os.getcwd(), "models", "models")
    
    # Establish database connection
    db_url = os.getenv("DATABASE_URL")
    conn = None
    cursor = None
    
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cursor = conn.cursor()
    except Exception as e:
        return f"❌ Critical Database Error: Could not connect to update status. {e}"

    try:
        for basin in basins_with_models:
            try:
                file_basin_name = basin.lower().replace(' ', '_')
                search_pattern = os.path.join(models_dir, f'model_{file_basin_name}_flood_*.pkl')
                matching_files = glob.glob(search_pattern)

                if not matching_files:
                    results_report.append(f"[{basin}] ❌ Error: No model file found matching pattern.")
                    continue

                model_file = matching_files[0]
                time_horizon = os.path.basename(model_file).split('_')[-1].replace('.pkl', '')

                agent_brain = joblib.load(model_file)
                model = agent_brain['model']
                required_features = agent_brain['feature_names']
                threshold = agent_brain.get('decision_threshold', 0.03)

                # Pass the reference_time parameter correctly to the feature extractor
                df = get_live_features_for_model(basin, reference_time=reference_time)

                if df is None or df.empty:
                    results_report.append(f"[{basin}] ⚠️ Error: Could not generate live features.")
                    continue

                # Filter dataframe to match exactly what the model expects
                df_ready = df[required_features]
                flood_probability = model.predict_proba(df_ready)[0][1]
                
                # Determine alert status
                has_alert = bool(flood_probability >= threshold)
                probability_pct = float(flood_probability * 100)
                
                # Update the database with the latest inference results
                update_query = """
                    UPDATE main_basins_status 
                    SET has_flood_alert = %s, 
                        flood_probability = %s, 
                        last_inference_time = CURRENT_TIMESTAMP
                    WHERE main_basin_name = %s;
                """
                cursor.execute(update_query, (has_alert, probability_pct, basin))

                # Format report output
                if has_alert:
                    results_report.append(f"🚨 CRITICAL ALERT - {basin}: Flash flood expected in {time_horizon}! (Probability: {probability_pct:.1f}%)")
                else:
                    results_report.append(f"✅ {basin} ({time_horizon} forecast): Status Normal (Probability: {probability_pct:.1f}%)")

            except Exception as e:
                # Reverted to clean error message
                results_report.append(f"[{basin}] ❌ Inference execution failed: {str(e)}")
                
    finally:
        # Ensure database connections are always closed
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return "\n".join(results_report)

# Tool 2: Run ML Inference for All Basins
@tool("Run ML Inference on All Basins")
def run_all_basins_inference_tool() -> str:
    """
    Extracts live features from the database and runs the XGBoost machine learning
    models for all main river basins. Returns a formatted report of flood probabilities.
    """
    return _run_all_basins_inference()