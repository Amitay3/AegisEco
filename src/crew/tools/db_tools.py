import os
import psycopg2
from crewai.tools import tool
from dotenv import load_dotenv
import joblib
import glob
from src.database.db_manager import get_live_features_for_model


load_dotenv()

@tool("Query High Rainfall Events")
def get_high_rainfall_events(threshold_mm: float) -> str:
    """
    Queries the database for any rain measurements that exceeded the given threshold in mm.
    Returns a formatted string of the results to be analyzed by the agent.
    """
    # Use the DB URL from your .env file
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
        
        # Execute the query safely with the parameter
        cur.execute(query, (threshold_mm,))
        rows = cur.fetchall()

        if not rows:
            return f"No stations recorded rainfall above {threshold_mm}mm."

        result = f"Found {len(rows)} records exceeding {threshold_mm}mm:\n"
        for row in rows:
            station_name, m_time, rain = row
            # Format the output so the LLM can easily read it
            result += f"- Station '{station_name}' at {m_time}: {rain}mm\n"

        return result
        
    except Exception as e:
        return f"Database query failed: {e}"
        
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()


# Ensure you also have the import for get_live_features_for_model here
# from src.database.db_manager import get_live_features_for_model

@tool("Run ML Inference on All Basins")
def run_all_basins_inference_tool() -> str:
    """
    Extracts live features from the database and runs the XGBoost machine learning 
    models for all main river basins. Returns a formatted report of flood probabilities.
    """
    # List of basins for which you have a ready model. You can update this list accordingly.
    basins_with_models = ["Beer Sheva", "Harod", "Sorek", "Alexander", "Ayalon", "Dishon", "Gerar", "Hadera", "Keziv", "Kishon", "Lachish", "Paran", "Shikma", "Taninim", "Yarkon", "Zin"] 
    results_report = ["📊 AegisEco ML Inference Report:\n"]
    
    # Since we are running from main.py, we use an absolute path straight from the root directory
    models_dir = os.path.join(os.getcwd(), "models", "models")
    
    for basin in basins_with_models:
        try:
            # Convert basin name to file format (e.g., "Beer Sheva" -> "beer_sheva")
            file_basin_name = basin.lower().replace(' ', '_')
            
            # 1. Dynamic search for the model using the file-formatted name
            search_pattern = os.path.join(models_dir, f'model_{file_basin_name}_flood_*.pkl')
            matching_files = glob.glob(search_pattern)
            
            if not matching_files:
                results_report.append(f"[{basin}] ❌ Error: No model file found matching pattern.")
                continue
                
            # Take the first matching file found
            model_file = matching_files[0]
            
            # 2. Extract the time horizon from the filename (e.g., '1h', '2h', '3h') for the report
            time_horizon = os.path.basename(model_file).split('_')[-1].replace('.pkl', '')
            
            # 3. Load the model
            agent_brain = joblib.load(model_file)
            model = agent_brain['model']
            required_features = agent_brain['feature_names']
            threshold = agent_brain.get('decision_threshold', 0.03)
            
            # 4. Prepare the data - IMPORTANT: We use the original 'basin' with the space here!
            df = get_live_features_for_model(basin)
            
            if df is None or df.empty:
                results_report.append(f"[{basin}] ⚠️ Error: Could not generate live features.")
                continue
                
            df_ready = df[required_features]
            flood_probability = model.predict_proba(df_ready)[0][1]
            
            # 5. Formulate the alert with explicit mention of the forecast horizon!
            if flood_probability >= threshold:
                results_report.append(f"🚨 CRITICAL ALERT - {basin}: Flash flood expected in {time_horizon}! (Probability: {flood_probability*100:.1f}%)")
            else:
                results_report.append(f"✅ {basin} ({time_horizon} forecast): Status Normal (Probability: {flood_probability*100:.1f}%)")
                
        except Exception as e:
            results_report.append(f"[{basin}] ❌ Inference execution failed: {str(e)}")
            
    return "\n".join(results_report)