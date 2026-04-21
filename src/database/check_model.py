import joblib
from src.database.db_manager import get_live_features_for_model

# ==========================================
# 1. Initialization
# ==========================================
MODEL_FILE = r'models/models/model_harod_flood_1h.pkl' 
print(f"Loading AI Brain from: {MODEL_FILE}...")

agent_brain = joblib.load(MODEL_FILE)
model = agent_brain['model']
required_features = agent_brain['feature_names']
decision_threshold = agent_brain.get('decision_threshold', 0.03)
flood_stage_m3s = agent_brain.get('flood_stage_m3s', 'Unknown')

print(f"✅ Model Loaded Successfully!")
print(f"   👉 Target Basin:      {agent_brain.get('basin_name', 'Unknown')}")
print(f"   👉 Expected Features: {len(required_features)} columns")
print(f"   👉 Alert Threshold:   {decision_threshold * 100:.1f}%")
print("-" * 50)

# ==========================================
# 2. Inference Function
# ==========================================
def run_model_inference(basin_name):
    print(f"\n[1] Fetching live data and building feature pipeline for: {basin_name}...")
    live_features_df = get_live_features_for_model(basin_name)
    
    if live_features_df is None or live_features_df.empty:
        print(f"Error: Could not generate features for {basin_name}.")
        return None, False

    print(f"Features generated successfully! Shape: {live_features_df.shape}")
    
    # Optional: Print a snapshot of the most important calculated features
    print("\n[2] Snapshot of Key Generated Features:")
    key_cols = [c for c in ['Basin_Rain_Mean', 'flow', 'Flow_lag1h', 'Rolling_Rain_168h', 'Soil_Moisture_EWM'] if c in live_features_df.columns]
    if key_cols:
        print(live_features_df[key_cols].to_string(index=False))

    print(f"\n[3] Aligning columns to match XGBoost training state...")
    df_ready = live_features_df[required_features]
    print(f"Ready for inference. Passing 1 row with exactly {len(df_ready.columns)} columns.")

    print(f"\n[4] Running XGBoost Prediction...")
    # predict_proba returns a 2D array: [[Probability_Class_0, Probability_Class_1]]
    raw_probabilities = model.predict_proba(df_ready)[0]
    prob_no_flood = raw_probabilities[0]
    flood_probability = raw_probabilities[1]
    
    is_alert_triggered = flood_probability >= decision_threshold
    
    # --- FINAL OUTPUT DISPLAY ---
    print("\n" + "="*45)
    print(f"🧠 INFERENCE RESULTS ({basin_name})")
    print("="*45)
    print(f"Probability of Normal Flow (Class 0): {prob_no_flood*100:.2f}%")
    print(f"Probability of Flash Flood (Class 1): {flood_probability*100:.2f}%")
    print(f"Model Alert Threshold:                {decision_threshold*100:.2f}%")
    
    if is_alert_triggered:
        print(f"\n🚨 STATUS: RED ALERT TRIGGERED! 🚨")
        print(f"Expected flow to exceed {flood_stage_m3s} m3/s.")
    else:
        print(f"\n✅ STATUS: NORMAL (No Alert).")
        
    print("="*45 + "\n")
    
    return flood_probability, is_alert_triggered

# ==========================================
# 3. Execution
# ==========================================
if __name__ == "__main__":
    run_model_inference("Harod")