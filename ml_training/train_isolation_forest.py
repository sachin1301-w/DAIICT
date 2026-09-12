"""
Trains the transaction-level Isolation Forest on synthetic data and saves the
three files backend/ml_service.py looks for (Mode 1):

    isolation_forest_model.pkl, scaler.pkl, feature_names.json

Run from ml_training/:
    python train_isolation_forest.py

Then copy the three output files into backend/models/ as:
    tx_isolation_forest_model.pkl, tx_scaler.pkl, tx_feature_names.json
(the "tx_" prefix in backend/config.py distinguishes this model from the
legacy REC-issuance isolation_forest_model.pkl already in that folder).
"""
from __future__ import annotations

import json

import joblib
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from feature_engineering import TX_FEATURE_ORDER, engineer_features
from generate_synthetic_fraud import generate

OUT_MODEL = "isolation_forest_model.pkl"
OUT_SCALER = "scaler.pkl"
OUT_FEATURES = "feature_names.json"


def main():
    df = generate()
    normal_only = df[df["label"] == "normal"]  # Isolation Forest trains unsupervised, on normal behaviour
    X = engineer_features(normal_only)

    scaler = StandardScaler().fit(X)
    X_scaled = scaler.transform(X)

    model = IsolationForest(n_estimators=250, contamination=0.06, random_state=42, n_jobs=-1)
    model.fit(X_scaled)

    # quick separation sanity check against the labeled fraud rows
    fraud_only = df[df["label"] != "normal"]
    X_fraud_scaled = scaler.transform(engineer_features(fraud_only))
    normal_scores = model.decision_function(X_scaled)
    fraud_scores = model.decision_function(X_fraud_scaled)
    print(f"Normal decision_function: mean={normal_scores.mean():.3f} std={normal_scores.std():.3f}")
    print(f"Fraud  decision_function: mean={fraud_scores.mean():.3f} std={fraud_scores.std():.3f}")
    print("(fraud mean should be noticeably lower/more negative than normal mean)")

    joblib.dump(model, OUT_MODEL)
    joblib.dump(scaler, OUT_SCALER)
    with open(OUT_FEATURES, "w") as f:
        json.dump(TX_FEATURE_ORDER, f, indent=2)

    print(f"Saved {OUT_MODEL}, {OUT_SCALER}, {OUT_FEATURES}")


if __name__ == "__main__":
    main()
