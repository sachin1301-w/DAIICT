# REC Guard -- Renewable Energy Certificate Fraud Detection

A continuously-running prototype: simulated renewable-energy generation and
REC trading flows through validation, ML anomaly detection, graph-based
fraud detection and a real local blockchain, live, with a React dashboard
that updates without a manual refresh.

```
Simulated Generation -> SQLite -> Rule Validation -> ML (Isolation Forest)
                                        |
                                  Graph Detection (NetworkX)
                                        |
                              Blockchain (Solidity + Hardhat + Web3.py)
                                        |
                               Fraud Decision Engine
                                        |
                          Risk Score + Classification -> Live Dashboard
```

The simulator ticks every few seconds, every tick runs the full pipeline,
and results stream to the dashboard over a WebSocket. See
[`backend/pipeline.py`](backend/pipeline.py) for the exact 15-step flow.

## Stack

- **Blockchain**: Solidity smart contract (`contracts/RECRegistry.sol`), Hardhat local node, Web3.py integration (`backend/blockchain_service.py`) -- a real chain, not a simulated ledger.
- **Backend**: FastAPI + SQLAlchemy + SQLite (`backend/`)
- **ML**: scikit-learn Isolation Forest (+ optional XGBoost), `backend/ml_service.py`
- **Graph**: NetworkX, `backend/graph_service.py`
- **Frontend**: React + Vite + Tailwind CSS + Recharts + vis-network (`frontend/`)

## Quick start

Three processes, in order, each in its own terminal.

### 1. Blockchain

```bash
cd contracts
npm install
npx hardhat node
```

Leave this running. **Its chain state is in-memory** -- every time you
(re)start `hardhat node`, you must redeploy and reseed (next step) before
the backend can talk to it.

In a second terminal, once the node is up:

```bash
cd contracts
npx hardhat run scripts/deploy.js --network localhost
npx hardhat run scripts/seed_roles.js --network localhost
```

This writes `backend/chain/contract_abi.json`, `contract_address.json` and
`wallets.json` (10 persona wallets -- Admin, Issuer, 2 Generators, 4
Traders, Regulator, Auditor -- using Hardhat's well-known local dev
accounts). Run `npx hardhat test` first if you want to see the contract's
own test suite (6 tests covering role permissions, duplicate IDs, transfer
ownership checks, freeze/unfreeze/revoke).

### 2. Backend

```bash
cd backend
pip install -r requirements.txt
python app.py
```

Serves the API + WebSocket on `http://localhost:8000`. On first run it
creates `rec_fraud.db`, seeds 5 generators (2 linked to real Hardhat
wallets, so their issuances/transfers actually settle on-chain), runs a
handful of warm-up pipeline ticks, and auto-starts the background simulator
(every 5s, 15% chance of an injected fraud scenario -- both configurable
live from the dashboard's Simulation Control page).

If `backend/models/tx_isolation_forest_model.pkl` doesn't exist, the app
auto-trains a fallback model on synthetic data at startup (Mode 2, see
`ml_service.py`) so it never crashes for lack of a model file.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### Docker (best-effort)

`docker-compose.yml` wires all three services together (untested end-to-end
in this environment -- the native quick-start above is the verified path).

## What's real vs. simulated

- **Blockchain**: real. `contracts/RECRegistry.sol` is a genuine Solidity
  contract with role-based access control (OpenZeppelin `AccessControl`),
  deployed to a real local Hardhat chain, called via Web3.py with actual
  signed transactions and mined blocks. `GET /api/blockchain/status` shows
  the live chain ID and block number.
- **Data**: synthetic. Generation readings, entities, and fraud patterns are
  simulator-generated, not real REC market data (none is publicly
  available -- see `ml_training/README.md` for the full disclosure).
- **ML**: the two `.pkl` files this project started with (`isolation_forest_model.pkl`,
  `xgboost_risk_model.pkl` in `backend/models/`) were trained on a different,
  earlier plant/vintage-level feature schema (verified directly via
  `feature_names_in_`), together with their real `LabelEncoder`s
  (`label_encoder_fuel.pkl`, `label_encoder_state.pkl`,
  `label_encoder_status.pkl`, also in `backend/models/`). Both original
  models run on **every** REC issuance (`pipeline.process_generation_event`
  calls `ml_service.score_generation_event`, blended into the decision
  alongside the transaction-level model -- see `ml_service.py`'s module
  docstring for the two real constraints the encoders reveal: the fuel
  encoder only ever saw `{solar, wind}`, the status encoder only ever saw
  `{"retired"}`). The continuous simulator *also* uses a second model
  (`tx_isolation_forest_model.pkl`) matching the richer transaction+graph
  feature schema this build calls for, since no pretrained model for that
  schema existed -- see `ml_training/` to train it deliberately instead of
  relying on the auto-trained fallback.

## Known limitations

- Entities the simulator invents on the fly (e.g. `"EcoRetail Ltd"`) have no
  real wallet/private key, so their blockchain transactions are gracefully
  marked "pending sync" (off-chain SQLite state still updates normally --
  see `pipeline.py`'s `TxResult.pending_sync` handling). Only the ~10
  seeded persona wallets in `backend/chain/wallets.json` can actually settle
  on-chain.
- SQLite + a single-process dev server: fine for a demo, not for
  production concurrency.
- The auto-trained fallback ML model is a small synthetic-data model, not a
  rigorously validated one -- expect "mild anomaly" band scores on some
  legitimate transactions rather than a clean 0. Decisions are still
  well-calibrated (see `fraud_decision.py`'s per-signal thresholds) because
  they gate on rule/graph signals crossing hard thresholds, not on ML score
  alone.

## Project layout

```
backend/        FastAPI app, SQLAlchemy models, pipeline, ML/graph/blockchain services
contracts/      Solidity contract + Hardhat project (compile/deploy/test)
ml_training/    Standalone scripts to train a better tx-level model (Colab-friendly)
frontend/       React + Vite dashboard
```
