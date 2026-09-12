# ML Training (local or Google Colab)

Trains the transaction-level Isolation Forest (and an optional XGBoost model)
used by `backend/ml_service.py` for continuous, per-transaction fraud
scoring.

## Important: synthetic data disclosure

**Real, publicly-labeled REC fraud data does not exist.** Everything here is
trained on synthetic data (`generate_synthetic_fraud.py`) built to exercise
the pipeline end-to-end for a prototype -- circular trading, over-issuance,
duplicate generation, capacity violations, retired-REC reuse and rapid
transfer chains are all *simulated* patterns, not real historical fraud. Do
not present model output from this data as evidence of real-world fraud
rates or as a validated production model.

If you get access to real transaction data later, the whole point of
`feature_engineering.py` having a single `TX_FEATURE_ORDER` constant is that
you only need to fill `generate_synthetic_fraud.py`'s role with a real
labeled dataset shaped the same way -- everything downstream (training,
`backend/ml_service.py`'s inference) stays the same.

## Workflow

1. Load / generate a dataset (`generate_synthetic_fraud.py` does this for
   the prototype -- swap in real data here if you have it).
2. Feature engineering (`feature_engineering.py`) -- derives
   `generation_rec_ratio` / `capacity_utilization` and enforces the
   canonical 22-feature column order the backend expects.
3. Fit a `StandardScaler`, scale, train `IsolationForest` on the *normal*
   rows only (it's an unsupervised/semi-supervised anomaly detector).
4. Sanity-check separation: the mean `decision_function` score on held-out
   fraud rows should be visibly lower (more anomalous) than on normal rows.
5. Save with `joblib`: `isolation_forest_model.pkl`, `scaler.pkl`,
   `feature_names.json`.
6. (Optional) `train_xgboost.py` trains a supervised classifier on the same
   synthetic labels as a second signal.
7. Copy the output files into `backend/models/` -- see naming below.

## Running it

```bash
cd ml_training
pip install -r requirements.txt
python train_isolation_forest.py
python train_xgboost.py   # optional
```

## Installing the trained model into the backend

The backend distinguishes this **transaction-level** model from the
**legacy REC-issuance** model that shipped with the project (trained on a
different, plant/vintage-level feature schema). Copy files in with the
`tx_` prefix so `backend/config.py` picks them up:

```
isolation_forest_model.pkl  ->  backend/models/tx_isolation_forest_model.pkl
scaler.pkl                  ->  backend/models/tx_scaler.pkl
feature_names.json          ->  backend/models/tx_feature_names.json
```

If these files are absent, `backend/ml_service.py` auto-trains an equivalent
fallback model at startup (Mode 2) so the app never crashes for lack of a
model file -- these scripts just let you train a better one deliberately,
inspect metrics, and version it.

## Feature schema (must match `backend/ml_service.py::TX_FEATURE_ORDER`)

```
plant_capacity_mw, energy_generated_mwh, rec_quantity, generation_rec_ratio,
capacity_utilization, weather_factor, time_gap_generation_to_issuance,
issuance_frequency_last_24h, transfer_frequency_last_24h,
transaction_velocity_last_10min, number_of_counterparties, account_age_days,
previous_alert_count, retirement_reuse_flag, duplicate_generation_flag,
source_degree, target_degree, source_betweenness, target_betweenness,
cycle_count, community_size, cluster_density, repeated_edge_count
```
