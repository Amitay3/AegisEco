import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import joblib
import os

from xgboost import XGBClassifier
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score

# ==========================================
# 1. Settings / Configuration
# ==========================================
DATASET_FILE = r'../organized_data/AegisEco_Sorek_ML_Dataset_v3.csv'

HORIZON = 1  # Predict how many hours ahead

filename = os.path.basename(DATASET_FILE)
basin_name = filename.split('_')[1].capitalize()

BASIN_THRESHOLDS = {
    'Sorek': 10.0,
    'Dishon': 8.0,
    'Harod': 4.0,
    'Kishon': 50.0,
    'Zin': 8.0,
    'Keziv': 8.0,
    'Ayalon': 27.0,
    'Yarkon': 50.0,
    'Alexander': 50.0,
    'Taninim': 8.0,
    'Lachish': 80.0,
    'Hadera': 61.0,
    'Beer': 25.0,
    'Paran': 4.5,
    'Shikma': 5.0,
    'Gerar': 8.0,
}

FLOOD_THRESHOLD = BASIN_THRESHOLDS.get(basin_name, 5.0)

print(f"Booting up AegisEco {basin_name} Early Warning Agent...")
print(f"Flood threshold: {FLOOD_THRESHOLD} m3/s")
print(f"Prediction horizon: {HORIZON} hours ahead")

# ==========================================
# 2. Data Loading
# ==========================================
df = pd.read_csv(DATASET_FILE, index_col='DateTime', parse_dates=True)
print(f"Loaded {len(df):,} hours | {df.index[0].date()} → {df.index[-1].date()}")

# ==========================================
# 3. Create Target (future flood)
# ==========================================
df = df.copy()

df[f'Flood_In_{HORIZON}h'] = (
    df['Flow'].shift(-HORIZON) > FLOOD_THRESHOLD
).astype(int)

df = df.dropna()

# ==========================================
# 4. Separate Features and Target
# ==========================================
TARGET_COL = f'Flood_In_{HORIZON}h'

X = df.drop(columns=['Flow', TARGET_COL])
y = df[TARGET_COL]

print(f"\nFeatures: {X.shape[1]}")
print(f"Positive class (flood): {(y==1).sum()} ({100*(y==1).mean():.2f}%)")

# ==========================================
# 5. Train/Test Split
# ==========================================
split_time = pd.Timestamp('2016-01-01')

X_train = X[X.index <= split_time]
X_test  = X[X.index >  split_time]
y_train = y[y.index <= split_time]
y_test  = y[y.index >  split_time]

print(f"\nTrain samples: {len(X_train):,} | Floods: {(y_train==1).sum()}")
print(f"Test samples:  {len(X_test):,}  | Floods: {(y_test==1).sum()}")

# ==========================================
# 6. Class Balancing
# ==========================================
scale_pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)

print(f"\nScale_pos_weight: {scale_pos_weight:.2f}")

# ==========================================
# 7. Train Model
# ==========================================
print("\nTraining XGBoost Classifier...")

model = XGBClassifier(
    n_estimators=600,
    learning_rate=0.05,
    max_depth=5,
    subsample=0.8,
    colsample_bytree=0.8,
    scale_pos_weight=scale_pos_weight,
    eval_metric='logloss',
    random_state=42,
    n_jobs=-1
)

model.fit(
    X_train, y_train,
    eval_set=[(X_test, y_test)],
    verbose=100
)

# ==========================================
# 8. Prediction
# ==========================================
y_proba = model.predict_proba(X_test)[:, 1]

THRESHOLD = 0.3
y_pred = (y_proba > THRESHOLD).astype(int)

# ==========================================
# 9. Performance Evaluation
# ==========================================
print(f"\n=== Flood Prediction ({HORIZON}h ahead) ===")
print(f"Decision threshold: {THRESHOLD}")

print("\nClassification Report:")
print(classification_report(y_test, y_pred))

print("Confusion Matrix:")
print(confusion_matrix(y_test, y_pred))

auc = roc_auc_score(y_test, y_proba)
print(f"ROC-AUC: {auc:.4f}")

# ==========================================
# 10. Feature Importance
# ==========================================
importances = pd.Series(
    model.feature_importances_,
    index=X.columns
).sort_values(ascending=True)

plt.figure(figsize=(12, 8))
importances.plot(kind='barh')
plt.title(f'AegisEco {basin_name}: Feature Importance (Flood {HORIZON}h)')
plt.tight_layout()
plt.show()

# ==========================================
# 11. Probabilities Over Time Graph
# ==========================================
plt.figure(figsize=(14, 5))
plt.plot(y_test.index, y_proba, label='Flood Probability', color='orange')
plt.axhline(y=THRESHOLD, linestyle='--', label='Decision Threshold')
plt.title(f'Flood Probability Over Time ({HORIZON}h Ahead)')
plt.legend()
plt.tight_layout()
plt.show()

# ==========================================
# 12. Save the Model
# ==========================================
agent_brain = {
    'basin_name': basin_name,
    'model': model,
    'model_type': 'xgboost_classifier',
    'prediction_horizon_hours': HORIZON,
    'flood_stage_m3s': FLOOD_THRESHOLD,
    'decision_threshold': THRESHOLD,
    'feature_names': X.columns.tolist(),
}

output_name = f'model_{basin_name.lower()}_flood_{HORIZON}h.pkl'
joblib.dump(agent_brain, output_name)

print(f"\nSaved -> {output_name}")