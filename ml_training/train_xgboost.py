"""
Optional supervised model: trains an XGBoost classifier on the synthetic
labeled data (label != "normal" -> fraud) as a second opinion alongside the
Isolation Forest. Per the spec, this is optional -- the app works fine with
Isolation Forest alone if this file is never run / the output isn't copied
into backend/models/.

Run from ml_training/:
    python train_xgboost.py
"""
from __future__ import annotations

import joblib
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from feature_engineering import engineer_features
from generate_synthetic_fraud import generate

OUT_MODEL = "xgboost_risk_model_tx.pkl"


def main():
    df = generate()
    X = engineer_features(df)
    y = (df["label"] != "normal").astype(int)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)

    scale_pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    model = XGBClassifier(
        n_estimators=250, max_depth=5, learning_rate=0.08, subsample=0.85, colsample_bytree=0.85,
        objective="binary:logistic", eval_metric="logloss", scale_pos_weight=scale_pos_weight, random_state=42,
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    print(classification_report(y_test, preds, target_names=["legitimate", "fraud"]))

    joblib.dump(model, OUT_MODEL)
    print(f"Saved {OUT_MODEL}")


if __name__ == "__main__":
    main()
