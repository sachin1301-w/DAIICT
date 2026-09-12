"""
ML risk-scoring service. Two independent scoring paths live here:

1. Legacy REC-issuance scoring (`score_generation_event`) -- uses the two
   .pkl files supplied at the start of this project (isolation_forest_model.pkl,
   xgboost_risk_model.pkl). Their `feature_names_in_` were inspected directly
   and expect 13 plant/vintage-level features (see LEGACY_FEATURE_ORDER).
   Used by the "submit a generation reading" REC-issuance flow.

   The three real LabelEncoders these models were trained against
   (label_encoder_fuel.pkl, label_encoder_state.pkl, label_encoder_status.pkl)
   showed up in backend/models/ during this build and are loaded directly
   here rather than guessed. Two real constraints they reveal:
     - fuel encoder only ever saw {solar, wind} -- an unseen category
       (e.g. "hydro") safely falls back rather than crashing (see
       `_safe_encode`), but the model genuinely cannot distinguish it.
     - status encoder only ever saw {"retired"} -- meaning status_enc
       carries no real discriminative signal in this model; every status
       value safely encodes to the same index, matching what the model
       actually learned instead of pretending otherwise.

2. Continuous transaction-level scoring (`score_transaction`) -- the feature
   set this project spec calls for (transaction velocity, graph degree,
   betweenness, etc, see TX_FEATURE_ORDER) has no corresponding pretrained
   model, since the supplied .pkl files were trained on a different, older
   schema. Per the spec's Mode-1/Mode-2 design: if
   backend/models/tx_isolation_forest_model.pkl exists, load it (Mode 1);
   otherwise auto-train a small Isolation Forest on synthetic normal data and
   save it, so the app never crashes for lack of a model file (Mode 2). This
   is what the always-on simulator/pipeline calls for every transaction.
"""
from __future__ import annotations

import json
import logging
import warnings
from datetime import date

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

import config

logger = logging.getLogger("ml_service")

# ============================================================ legacy (REC issuance)

LEGACY_FEATURE_ORDER = [
    "plant_capacity_mw", "fuel_type_enc", "state_enc", "accreditation_year", "vintage_month",
    "generation_expected_mwh", "generation_claimed_mwh", "generation_deviation_pct",
    "num_transfers", "days_to_retirement", "self_retention_flag", "duplicate_flag", "status_enc",
]

# full state name -> the 2-letter code the real label_encoder_state.pkl was fit on
STATE_TO_CODE = {
    "gujarat": "GJ", "maharashtra": "MH", "rajasthan": "RJ", "tamil_nadu": "TN",
    "karnataka": "KA", "madhya_pradesh": "MP", "andhra_pradesh": "AP",
    "uttar_pradesh": "UP", "telangana": "TG", "haryana": "HR",
}


def _safe_encode(encoder, value: str, fallback_value: str | None = None) -> int:
    """Encode with a real LabelEncoder, falling back to its first known class
    (or an explicit fallback_value) for a category it never saw in training,
    instead of raising and crashing the pipeline."""
    classes = list(encoder.classes_)
    if value not in classes:
        value = fallback_value if fallback_value in classes else classes[0]
    return int(encoder.transform([value])[0])

# ============================================================ new (per-transaction)

TX_FEATURE_ORDER = [
    "plant_capacity_mw", "energy_generated_mwh", "rec_quantity", "generation_rec_ratio",
    "capacity_utilization", "weather_factor", "time_gap_generation_to_issuance",
    "issuance_frequency_last_24h", "transfer_frequency_last_24h", "transaction_velocity_last_10min",
    "number_of_counterparties", "account_age_days", "previous_alert_count",
    "retirement_reuse_flag", "duplicate_generation_flag",
    "source_degree", "target_degree", "source_betweenness", "target_betweenness",
    "cycle_count", "community_size", "cluster_density", "repeated_edge_count",
]


def _load(path) -> object:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return joblib.load(path)


class MLService:
    def __init__(self):
        self.legacy_iso = self.legacy_xgb = None
        if config.LEGACY_ISOLATION_FOREST_PATH.exists():
            self.legacy_iso = _load(config.LEGACY_ISOLATION_FOREST_PATH)
        if config.LEGACY_XGBOOST_PATH.exists():
            self.legacy_xgb = _load(config.LEGACY_XGBOOST_PATH)

        self.fuel_encoder = self.state_encoder = self.status_encoder = None
        if config.LEGACY_FUEL_ENCODER_PATH.exists():
            self.fuel_encoder = _load(config.LEGACY_FUEL_ENCODER_PATH)
        if config.LEGACY_STATE_ENCODER_PATH.exists():
            self.state_encoder = _load(config.LEGACY_STATE_ENCODER_PATH)
        if config.LEGACY_STATUS_ENCODER_PATH.exists():
            self.status_encoder = _load(config.LEGACY_STATUS_ENCODER_PATH)

        self.tx_model: IsolationForest
        self.tx_scaler: StandardScaler
        self._load_or_train_tx_model()

    # ------------------------------------------------------------ legacy REC-issuance scoring

    def _legacy_features(self, rec: dict) -> pd.DataFrame:
        expected = float(rec.get("generation_expected_mwh", 0) or 0)
        claimed = float(rec.get("generation_claimed_mwh", 0) or 0)
        deviation_pct = ((claimed - expected) / expected) * 100.0 if expected > 0 else 0.0

        days_to_retirement = rec.get("days_to_retirement")
        if days_to_retirement is None:
            issued, retired = rec.get("issued_date"), rec.get("retired_date")
            if issued and retired:
                days_to_retirement = (date.fromisoformat(retired) - date.fromisoformat(issued)).days
            else:
                # Verified against the model directly: a sentinel like -1/0 reads as
                # "retired same day as issued" and spikes fraud probability to ~100%
                # regardless of everything else. True missing (NaN) is what the
                # model was trained on for not-yet-retired RECs.
                days_to_retirement = np.nan

        fuel_value = str(rec.get("fuel_type", "solar")).lower()
        state_value = STATE_TO_CODE.get(str(rec.get("state", "")).lower(), str(rec.get("state", "")).upper())
        status_value = str(rec.get("status", "retired")).lower()

        row = {
            "plant_capacity_mw": float(rec.get("plant_capacity_mw", 0) or 0),
            "fuel_type_enc": _safe_encode(self.fuel_encoder, fuel_value) if self.fuel_encoder else 0,
            "state_enc": _safe_encode(self.state_encoder, state_value) if self.state_encoder else 0,
            "accreditation_year": int(rec.get("accreditation_year", date.today().year) or date.today().year),
            "vintage_month": int(rec.get("vintage_month", 1) or 1),
            "generation_expected_mwh": expected,
            "generation_claimed_mwh": claimed,
            "generation_deviation_pct": deviation_pct,
            "num_transfers": int(rec.get("num_transfers", 0) or 0),
            "days_to_retirement": days_to_retirement,
            "self_retention_flag": int(bool(rec.get("self_retention_flag", False))),
            "duplicate_flag": int(bool(rec.get("duplicate_flag", False))),
            "status_enc": _safe_encode(self.status_encoder, status_value) if self.status_encoder else 0,
        }
        return pd.DataFrame([row], columns=LEGACY_FEATURE_ORDER)

    def score_generation_event(self, rec: dict) -> dict:
        if self.legacy_iso is None:
            return {"available": False, "reason": "legacy models not found in backend/models/"}

        X = self._legacy_features(rec)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = float(self.legacy_iso.decision_function(X)[0])
            is_outlier = bool(self.legacy_iso.predict(X)[0] == -1)
            risk_proba = float(self.legacy_xgb.predict_proba(X)[0][1]) if self.legacy_xgb is not None else None

        anomaly_score = float(np.clip((0.5 - raw) * 100, 0, 100))
        risk_score = float(np.clip(risk_proba * 100, 0, 100)) if risk_proba is not None else anomaly_score
        combined = 0.5 * anomaly_score + 0.5 * risk_score

        return {
            "available": True,
            "anomaly_score": round(anomaly_score, 2),
            "is_outlier": is_outlier,
            "risk_score": round(risk_score, 2),
            "combined_score": round(combined, 2),
        }

    # ------------------------------------------------------------ transaction-level scoring

    def _load_or_train_tx_model(self) -> None:
        if config.ISOLATION_FOREST_PATH.exists() and config.SCALER_PATH.exists():
            logger.info("Mode 1: loading trained transaction Isolation Forest from disk")
            self.tx_model = _load(config.ISOLATION_FOREST_PATH)
            self.tx_scaler = _load(config.SCALER_PATH)
            return

        logger.warning("Mode 2: no transaction model found -- auto-training a fallback Isolation Forest")
        rng = np.random.default_rng(42)
        n = 800
        synthetic = pd.DataFrame({
            "plant_capacity_mw": rng.uniform(10, 150, n),
            "energy_generated_mwh": rng.uniform(5, 140, n),
            "rec_quantity": rng.uniform(5, 140, n),
            "generation_rec_ratio": rng.normal(1.0, 0.08, n).clip(0.5, 1.6),
            "capacity_utilization": rng.uniform(0.1, 0.95, n),
            "weather_factor": rng.uniform(0.3, 1.0, n),
            "time_gap_generation_to_issuance": rng.uniform(0.1, 6, n),
            "issuance_frequency_last_24h": rng.poisson(3, n),
            "transfer_frequency_last_24h": rng.poisson(4, n),
            "transaction_velocity_last_10min": rng.poisson(1, n),
            # 0 is the normal value for an ISSUE event (no counterparty involved,
            # only TRANSFERs have one) -- must be common in training, not rare,
            # or every legitimate issuance reads as a mild anomaly on this feature alone.
            "number_of_counterparties": rng.choice([0, 1, 2, 3, 4], n, p=[0.45, 0.3, 0.15, 0.07, 0.03]),
            "account_age_days": rng.uniform(0, 1500, n),  # 0 must be normal: a freshly-seeded/newly onboarded generator is not itself anomalous
            "previous_alert_count": rng.poisson(0.2, n),
            "retirement_reuse_flag": rng.choice([0, 1], n, p=[0.97, 0.03]),
            "duplicate_generation_flag": rng.choice([0, 1], n, p=[0.97, 0.03]),
            "source_degree": rng.integers(1, 6, n),
            "target_degree": rng.integers(1, 6, n),
            "source_betweenness": rng.uniform(0, 0.3, n),
            "target_betweenness": rng.uniform(0, 0.3, n),
            "cycle_count": rng.choice([0, 1], n, p=[0.95, 0.05]),
            "community_size": rng.integers(1, 6, n),
            "cluster_density": rng.uniform(0, 0.4, n),
            "repeated_edge_count": rng.poisson(0.3, n),
        })[TX_FEATURE_ORDER]

        self.tx_scaler = StandardScaler().fit(synthetic)
        X_scaled = self.tx_scaler.transform(synthetic)
        self.tx_model = IsolationForest(
            n_estimators=200, contamination=0.08, random_state=42, n_jobs=-1
        ).fit(X_scaled)

        config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.tx_model, config.ISOLATION_FOREST_PATH)
        joblib.dump(self.tx_scaler, config.SCALER_PATH)
        with open(config.FEATURE_NAMES_PATH, "w") as f:
            json.dump(TX_FEATURE_ORDER, f, indent=2)
        logger.info("Saved auto-trained fallback model to %s", config.ISOLATION_FOREST_PATH)

    def score_transaction(self, features: dict) -> dict:
        row = {k: features.get(k, 0) for k in TX_FEATURE_ORDER}
        X = pd.DataFrame([row], columns=TX_FEATURE_ORDER).fillna(0)
        X_scaled = self.tx_scaler.transform(X)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = float(self.tx_model.decision_function(X_scaled)[0])
            is_outlier = bool(self.tx_model.predict(X_scaled)[0] == -1)

        ml_score = float(np.clip((0.5 - raw) * 120, 0, 100))
        band = next((name for name, (lo, hi) in config.ML_SCORE_BANDS.items() if lo <= ml_score <= hi), "NORMAL")

        reasons = []
        means = self.tx_scaler.mean_
        stds = self.tx_scaler.scale_
        for i, feat in enumerate(TX_FEATURE_ORDER):
            if stds[i] <= 0:
                continue
            z = (row[feat] - means[i]) / stds[i]
            if abs(z) >= 2.2:
                direction = "above" if z > 0 else "below"
                reasons.append(f"{feat.replace('_', ' ')} is unusually {direction} normal (z={z:.1f})")
        if not reasons and ml_score > 60:
            reasons.append("overall feature pattern deviates from normal transaction behaviour")

        return {
            "ml_score": round(ml_score, 2),
            "prediction": "ANOMALY" if is_outlier else "NORMAL",
            "band": band,
            "reasons": reasons[:5],
            "features_used": row,
        }


_service: MLService | None = None


def get_service() -> MLService:
    global _service
    if _service is None:
        _service = MLService()
    return _service
