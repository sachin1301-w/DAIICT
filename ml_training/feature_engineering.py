"""
Canonical feature schema for the continuous transaction-level Isolation
Forest (must match backend/ml_service.py's TX_FEATURE_ORDER exactly, since
a model trained here is meant to be dropped into backend/models/ and loaded
by the running app).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TX_FEATURE_ORDER = [
    "plant_capacity_mw", "energy_generated_mwh", "rec_quantity", "generation_rec_ratio",
    "capacity_utilization", "weather_factor", "time_gap_generation_to_issuance",
    "issuance_frequency_last_24h", "transfer_frequency_last_24h", "transaction_velocity_last_10min",
    "number_of_counterparties", "account_age_days", "previous_alert_count",
    "retirement_reuse_flag", "duplicate_generation_flag",
    "source_degree", "target_degree", "source_betweenness", "target_betweenness",
    "cycle_count", "community_size", "cluster_density", "repeated_edge_count",
]


def engineer_features(raw: pd.DataFrame) -> pd.DataFrame:
    """raw must already contain plant_capacity_mw, energy_generated_mwh and
    rec_quantity; this derives the ratio/utilization columns from them if
    they are not already present, and fills anything still missing with 0."""
    df = raw.copy()

    if "generation_rec_ratio" not in df:
        df["generation_rec_ratio"] = np.where(
            df["energy_generated_mwh"] > 0, df["rec_quantity"] / df["energy_generated_mwh"], 1.0
        )
    if "capacity_utilization" not in df:
        df["capacity_utilization"] = np.where(
            df["plant_capacity_mw"] > 0, df["energy_generated_mwh"] / (df["plant_capacity_mw"] * 6), 0.0
        )

    for col in TX_FEATURE_ORDER:
        if col not in df:
            df[col] = 0

    return df[TX_FEATURE_ORDER].fillna(0)
