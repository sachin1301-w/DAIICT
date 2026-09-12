"""
Synthetic training/evaluation data generator for the REC fraud models.

IMPORTANT: Real, labeled REC fraud data is not publicly available. Every
label produced here is a synthetic construction meant to exercise the
pipeline end-to-end for a hackathon prototype -- it must never be presented
or reused as real historical fraud evidence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from feature_engineering import TX_FEATURE_ORDER

FRAUD_LABELS = [
    "normal", "over_issuance", "duplicate_generation", "capacity_violation",
    "retired_reuse", "rapid_transfer", "circular_trading",
]


def _normal_rows(rng: np.random.Generator, n: int) -> pd.DataFrame:
    return pd.DataFrame({
        "plant_capacity_mw": rng.uniform(10, 150, n),
        "energy_generated_mwh": rng.uniform(5, 140, n),
        "rec_quantity": None,  # filled below, tied to energy_generated_mwh
        "generation_rec_ratio": rng.normal(1.0, 0.08, n).clip(0.5, 1.6),
        "capacity_utilization": rng.uniform(0.1, 0.95, n),
        "weather_factor": rng.uniform(0.3, 1.0, n),
        "time_gap_generation_to_issuance": rng.uniform(0.1, 6, n),
        "issuance_frequency_last_24h": rng.poisson(3, n),
        "transfer_frequency_last_24h": rng.poisson(4, n),
        "transaction_velocity_last_10min": rng.poisson(1, n),
        "number_of_counterparties": rng.choice([0, 1, 2, 3, 4], n, p=[0.45, 0.3, 0.15, 0.07, 0.03]),
        "account_age_days": rng.uniform(0, 1500, n),  # 0 must be normal: a freshly onboarded generator isn't itself anomalous
        "previous_alert_count": rng.poisson(0.2, n),
        "retirement_reuse_flag": 0,
        "duplicate_generation_flag": 0,
        "source_degree": rng.integers(1, 6, n),
        "target_degree": rng.integers(1, 6, n),
        "source_betweenness": rng.uniform(0, 0.3, n),
        "target_betweenness": rng.uniform(0, 0.3, n),
        "cycle_count": 0,
        "community_size": rng.integers(1, 6, n),
        "cluster_density": rng.uniform(0, 0.4, n),
        "repeated_edge_count": rng.poisson(0.3, n),
        "label": "normal",
    })


def generate(n_normal: int = 900, n_fraud_per_type: int = 60, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    normal = _normal_rows(rng, n_normal)
    normal["rec_quantity"] = normal["energy_generated_mwh"] * normal["generation_rec_ratio"]

    frames = [normal]

    over_issuance = _normal_rows(rng, n_fraud_per_type)
    over_issuance["rec_quantity"] = over_issuance["energy_generated_mwh"] * rng.uniform(3, 6, n_fraud_per_type)
    over_issuance["generation_rec_ratio"] = over_issuance["rec_quantity"] / over_issuance["energy_generated_mwh"]
    over_issuance["label"] = "over_issuance"
    frames.append(over_issuance)

    duplicate_gen = _normal_rows(rng, n_fraud_per_type)
    duplicate_gen["rec_quantity"] = duplicate_gen["energy_generated_mwh"] * duplicate_gen["generation_rec_ratio"]
    duplicate_gen["duplicate_generation_flag"] = 1
    duplicate_gen["previous_alert_count"] = rng.poisson(1.5, n_fraud_per_type)
    duplicate_gen["label"] = "duplicate_generation"
    frames.append(duplicate_gen)

    capacity_violation = _normal_rows(rng, n_fraud_per_type)
    capacity_violation["energy_generated_mwh"] = capacity_violation["plant_capacity_mw"] * rng.uniform(8, 20, n_fraud_per_type)
    capacity_violation["rec_quantity"] = capacity_violation["energy_generated_mwh"] * capacity_violation["generation_rec_ratio"]
    capacity_violation["capacity_utilization"] = rng.uniform(1.5, 3.0, n_fraud_per_type)
    capacity_violation["label"] = "capacity_violation"
    frames.append(capacity_violation)

    retired_reuse = _normal_rows(rng, n_fraud_per_type)
    retired_reuse["rec_quantity"] = retired_reuse["energy_generated_mwh"] * retired_reuse["generation_rec_ratio"]
    retired_reuse["retirement_reuse_flag"] = 1
    retired_reuse["previous_alert_count"] = rng.poisson(1.0, n_fraud_per_type)
    retired_reuse["label"] = "retired_reuse"
    frames.append(retired_reuse)

    rapid_transfer = _normal_rows(rng, n_fraud_per_type)
    rapid_transfer["rec_quantity"] = rapid_transfer["energy_generated_mwh"] * rapid_transfer["generation_rec_ratio"]
    rapid_transfer["transaction_velocity_last_10min"] = rng.poisson(6, n_fraud_per_type) + 3
    rapid_transfer["transfer_frequency_last_24h"] = rng.poisson(15, n_fraud_per_type) + 8
    rapid_transfer["number_of_counterparties"] = rng.integers(3, 7, n_fraud_per_type)
    rapid_transfer["label"] = "rapid_transfer"
    frames.append(rapid_transfer)

    circular = _normal_rows(rng, n_fraud_per_type)
    circular["rec_quantity"] = circular["energy_generated_mwh"] * circular["generation_rec_ratio"]
    circular["cycle_count"] = rng.integers(1, 3, n_fraud_per_type)
    circular["cluster_density"] = rng.uniform(0.4, 0.9, n_fraud_per_type)
    circular["repeated_edge_count"] = rng.poisson(3, n_fraud_per_type) + 1
    circular["source_degree"] = rng.integers(4, 9, n_fraud_per_type)
    circular["target_degree"] = rng.integers(4, 9, n_fraud_per_type)
    circular["label"] = "circular_trading"
    frames.append(circular)

    df = pd.concat(frames, ignore_index=True)
    return df.sample(frac=1, random_state=seed).reset_index(drop=True)


if __name__ == "__main__":
    df = generate()
    df.to_csv("synthetic_rec_transactions.csv", index=False)
    print(f"Wrote {len(df)} synthetic rows to synthetic_rec_transactions.csv")
    print(df["label"].value_counts())
