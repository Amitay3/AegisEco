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


# Re-alert for a basin that's still above threshold if its probability has
# climbed by at least this many percentage points since the last warning —
# otherwise an hours-long flood would only ever produce a single message.
ALERT_ESCALATION_THRESHOLD_PCT = 15.0


def _get_alert_plan():
    """
    Compares the latest ML status per basin (main_basins_status) against the
    last alert logged for that basin (alert_log). Returns three lists of
    (basin_name, probability, previous_probability) tuples:
    - new_alerts: basins that need a fresh flood-warning message
    - all_clears: basins whose previously-sent warning should be lifted
    - no_action: basins that already match their last logged alert state
    """
    db_url = os.getenv("DATABASE_URL")
    conn = psycopg2.connect(db_url)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT main_basin_name, has_flood_alert, flood_probability
            FROM main_basins_status
            WHERE has_flood_alert IS NOT NULL;
        """)
        statuses = cursor.fetchall()

        cursor.execute("""
            SELECT DISTINCT ON (main_basin_name)
                main_basin_name, alert_type, flood_probability
            FROM alert_log
            ORDER BY main_basin_name, sent_at DESC;
        """)
        last_alerts = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
        cursor.close()
    finally:
        conn.close()

    new_alerts, all_clears, no_action = [], [], []

    for basin, has_alert, probability in statuses:
        probability = float(probability) if probability is not None else 0.0
        last_type, last_prob = last_alerts.get(basin, (None, None))
        last_prob = float(last_prob) if last_prob is not None else None

        if has_alert:
            if last_type != "flood_warning":
                new_alerts.append((basin, probability, last_prob))
            elif last_prob is not None and probability - last_prob >= ALERT_ESCALATION_THRESHOLD_PCT:
                new_alerts.append((basin, probability, last_prob))
            else:
                no_action.append((basin, probability, "active warning already sent"))
        else:
            if last_type == "flood_warning":
                all_clears.append((basin, probability, last_prob))
            else:
                no_action.append((basin, probability, "normal, no active warning"))

    return new_alerts, all_clears, no_action


def _format_alert_plan(new_alerts, all_clears, no_action) -> str:
    """Formats the alert plan lists into a plain-text report for the LLM."""
    lines = []

    if new_alerts:
        lines.append("NEW FLOOD WARNINGS TO SEND (draft ONE emergency message covering all of these basins):")
        for basin, prob, last_prob in new_alerts:
            if last_prob is None:
                lines.append(f"- {basin}: {prob:.1f}% (no prior warning active)")
            else:
                lines.append(f"- {basin}: {prob:.1f}% (ESCALATION - prior warning sent at {last_prob:.1f}%, risk has increased)")
    else:
        lines.append("NEW FLOOD WARNINGS TO SEND: none.")

    lines.append("")

    if all_clears:
        lines.append("ALL-CLEAR NOTICES TO SEND (draft ONE separate message covering all of these basins - their flood warning is now resolved):")
        for basin, prob, last_prob in all_clears:
            prior = f"{last_prob:.1f}%" if last_prob is not None else "unknown"
            lines.append(f"- {basin}: now {prob:.1f}% (was {prior} when last warned)")
    else:
        lines.append("ALL-CLEAR NOTICES TO SEND: none.")

    lines.append("")

    lines.append("NO ACTION (do not mention these basins in any Telegram message):")
    if no_action:
        for basin, prob, note in no_action:
            lines.append(f"- {basin}: {prob:.1f}% ({note})")
    else:
        lines.append("- (none)")

    return "\n".join(lines)


@tool("Get Alert Plan")
def get_alert_plan_tool() -> str:
    """
    Compares the latest ML inference results against the history of alerts
    already sent (see 'Log Sent Alert'), and returns which basins need a NEW
    flood warning, which need an ALL-CLEAR (a previously warned basin has
    returned to normal), and which need no action (already warned with no
    major change, or still normal). Call this BEFORE deciding whether to send
    any Telegram alert, so the same warning isn't repeated every hour.
    """
    try:
        new_alerts, all_clears, no_action = _get_alert_plan()
    except Exception as e:
        return f"Database query failed: {e}"
    return _format_alert_plan(new_alerts, all_clears, no_action)


def _log_alert(main_basin_name: str, alert_type: str, flood_probability: float) -> str:
    db_url = os.getenv("DATABASE_URL")
    conn = psycopg2.connect(db_url)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO alert_log (main_basin_name, alert_type, flood_probability)
            VALUES (%s, %s, %s);
            """,
            (main_basin_name, alert_type, flood_probability)
        )
        conn.commit()
        cursor.close()
    finally:
        conn.close()
    return f"Logged {alert_type} for {main_basin_name} at {flood_probability:.1f}%."


@tool("Log Sent Alert")
def log_alert_tool(main_basin_name: str, alert_type: str, flood_probability: float) -> str:
    """
    Records that a Telegram alert was sent for a basin, so future runs don't
    repeat it. 'alert_type' must be exactly 'flood_warning' or 'all_clear'.
    Call this once for EACH basin included in a message you just sent.
    """
    if alert_type not in ("flood_warning", "all_clear"):
        return "Error: alert_type must be 'flood_warning' or 'all_clear'."
    try:
        return _log_alert(main_basin_name, alert_type, float(flood_probability))
    except Exception as e:
        return f"Database error while logging alert: {e}"