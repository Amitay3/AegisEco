import joblib
import pandas as pd
import numpy as np
from datetime import datetime

# ==========================================
# 1. Load the new model (Classification)
# ==========================================
MODEL_FILE = r'../models/model_sorek_flood_1h.pkl'
print(f"Waking up AI Agent from {MODEL_FILE}...")

agent_brain        = joblib.load(MODEL_FILE)
model              = agent_brain['model']
flood_threshold    = agent_brain['flood_stage_m3s']
required_features  = agent_brain['feature_names']
basin_name         = agent_brain['basin_name']
prediction_horizon = agent_brain.get('prediction_horizon_hours', 3) 
decision_threshold = agent_brain.get('decision_threshold', 0.03)  

print(f"Agent {basin_name} v3 awake.")
print(f"Flood condition: > {flood_threshold} m3/s")
print(f"Prediction Horizon: {prediction_horizon} hours ahead")
print(f"Alert Trigger (Probability): {decision_threshold*100:.1f}%")

# ==========================================
# 2. Data Preparation (Remains the same, just ordered to match your features)
# ==========================================
now = datetime.now()
month = now.month

live_data = {
    # Very significant rain for one hour
    'Basin_Rain_Mean':      12.0,  
    'Basin_Rain_Max':       18.0,
    'Basin_Rain_Std':       3.0,
    'Basin_Rain_Count':     2,
    'Basin_Intensity_Max':  15.0,
    'Basin_Intensity_Mean': 10.0,

    # Getting really close to the threshold (Orange alert)
    'Flow_lag1h':           6.0,    
    'Flow_lag2h':           5.5,    
    'Flow_lag3h':           0.4,    
    'Flow_lag6h':           0.1,
    'Flow_lag12h':          0.0,
    'Flow_lag24h':          0.0,
    # Sharp rising rate of 1.7 m3/s per hour
    'Flow_Rate_of_Change':  2.5,    
    'Flow_Is_Active':       1,

    # --- Wet winter soil ---
    'Soil_Moisture_EWM':    8.5,
    'Rolling_Rain_24h':     35.0,
    'Rolling_Rain_72h':     60.0,
    'Rolling_Rain_168h':    90.0,

    # --- Rain in the last few hours that built the wave ---
    'Basin_Rain_lag1h':     10.0,
    'Basin_Intensity_lag1h':8.0,
    'Basin_Rain_lag2h':     6.0,
    'Basin_Intensity_lag2h':5.0,
    'Basin_Rain_lag3h':     2.0,
    'Basin_Intensity_lag3h':1.5,
    'Basin_Rain_lag4h':     0.5,
    'Basin_Intensity_lag4h':0.5,
    'Basin_Rain_lag5h':     0.0,
    'Basin_Intensity_lag5h':0.0,
    'Basin_Rain_lag6h':     0.0,
    'Basin_Intensity_lag6h':0.0,
    # Rain is intensifying
    'Rain_Acceleration':    2.0,    

    # --- January ---
    'Month_Sin':    np.sin(2 * np.pi * 1 / 12),
    'Month_Cos':    np.cos(2 * np.pi * 1 / 12),
    'Hour_Sin':     np.sin(2 * np.pi * 14 / 24),
    'Hour_Cos':     np.cos(2 * np.pi * 14 / 24),
    'Is_Early_Winter': 0,
    'Is_Peak_Winter':  1,
    'Is_Summer':       0,
}

df_live  = pd.DataFrame(live_data, index=[0])

# Ensure all columns required by the model are present, if anything is missing put 0
for col in required_features:
    if col not in df_live.columns:
        df_live[col] = 0.0

# Force correct column order
df_ready = df_live[required_features]

# ==========================================
# 3. Prediction (Probability instead of quantity!)
# ==========================================
print("\nAnalyzing incoming data...")

# Use predict_proba instead of predict
# Which takes the second column [1] representing the probability for class "1" (flood)
flood_probability = model.predict_proba(df_ready)[0][1] 

print(f"Probability of flood in {prediction_horizon}h: {flood_probability*100:.2f}%")

# ==========================================
# 4. Decision
# ==========================================
if flood_probability >= decision_threshold:
    print(f"\n[!!!] AEGISECO FLOOD ALERT [!!!]")
    print(f"Agent {basin_name} has triggered an alert!")
    print(f"Confidence: {flood_probability*100:.1f}% (Threshold is {decision_threshold*100:.1f}%)")
    print(f"Warning: Expected flow to exceed {flood_threshold} m3/s in exactly {prediction_horizon} hours.")
    print("Dispatching warnings to relevant authorities!")
else:
    print(f"\n[OK] AegisEco Status: Normal.")
    print(f"Confidence of flood is only {flood_probability*100:.1f}%, which is below the {decision_threshold*100:.1f}% trigger.")