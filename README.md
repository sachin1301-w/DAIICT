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
- **Verification**: cryptographic tamper detection + on-chain cross-checks, `backend/verification_service.py`
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

## Resetting the Simulation

The dashboard's **Simulation Controls** card (shown at the top of the
Dashboard page, and again with more detail on the Simulation Control page)
is the way to manage a run without ever restarting the backend or frontend.

**1. Starting the project** -- follow Quick start above (Hardhat node,
deploy/seed, backend, frontend). The simulator auto-starts on backend boot
using `SIMULATION_INTERVAL_SECONDS`/`FRAUD_PROBABILITY` from `.env`/`config.py`
(5s / 15% by default).

**2. Selecting fraud probability** -- pick a preset (0/5/10/15/20/30/50%)
from the dropdown. Clicking **Start Simulation** always applies whatever is
currently selected before starting, so a fresh run uses that value from its
very first tick -- there's no separate "apply" step to remember. If the
simulator is already running, use **Apply to running simulation** instead:
it updates the live config and takes effect on the very next tick, with no
restart. Each tick still independently rolls `random.random() < fraud_probability`
(not "every Nth transaction"), so the *observed* rate over a small batch
will vary around the configured value rather than match it exactly -- the
stats line under the buttons (`Configured / Generated / Fraudulent /
Observed rate`) shows both side by side.

**3. Stopping the simulation** -- **Stop Simulation** halts the background
tick loop without touching any data already generated; RECs, transactions,
alerts and the graph all stay exactly as they were, and **Start Simulation**
resumes generating on top of them.

**4. Resetting transactions** -- **Reset Transactions** stops the simulator,
then permanently deletes every simulator-generated row: generation records,
RECs, transactions, fraud alerts, graph entities/edges and fraud clusters.
It does **not** touch `generators` (seed config), the ML model files,
`contracts/`, or anything under `backend/chain/` (deployed contract
address/ABI, wallets) -- so you never need to redeploy or reseed after a
reset, only click Start again. All connected dashboards clear their live
view immediately (via a `simulation_reset` WebSocket broadcast), not on
their next multi-second poll.

Also deliberately **not** touched: the REC Verification Portal's
`rec_verification_requests` and `rec_audit_log` tables (see the next
section). Those are a compliance/audit trail, not simulated demo data --
they're designed to survive a reset the same way real verification records
would outlive a system's test data being wiped. The Dashboard's
Verification Summary card and the Verification History page both keep
showing everything ever verified, before and after a reset.

**5. How transaction numbering restarts** -- REC/transaction/alert primary
keys are plain SQLite autoincrement integers. Deleting every row from a
table (rather than dropping it) makes SQLite reuse row ids starting at 1
again, so the very next REC or transaction created after a reset is
numbered `#0` (shown next to the REC id in the Live Feed table), and so on
from there -- no old numbers ever carry over into a new run. A regular
backend *restart* (closing the terminal and re-running `python app.py`)
is different from Reset: by design it keeps all existing data and continues
the same numbering, per the "reset is the authoritative way to start a
clean run" behavior below. Each run also gets a fresh `simulation_run_id`
(e.g. `RUN-a1b2c3d4`), shown next to the RUNNING/STOPPED pill, so you can
tell at a glance whether you're looking at the current run.

A note on the local blockchain: Hardhat's in-memory chain itself can't be
reset without restarting the `hardhat node` process, so old REC entries
technically remain on that chain after you reset the SQLite database. This
is harmless -- once the DB is cleared, nothing in the app ever looks them
up again (every blockchain call is keyed off a REC id read from the current
DB), so they simply never resurface in the UI. If you do restart the
Hardhat node itself, redeploy + reseed (step 1 of Quick start) before
starting a new simulation run, otherwise every blockchain call fails until
you do.

**6. Blockchain PASSED/FAILED/PENDING/NOT_CONNECTED** -- every REC and
transaction carries a `blockchain_status`, shown as a colored badge (with
matching text, not color alone) in the Live Feed, the Certificates table,
and fraud alert details, plus rolled up into the Dashboard's **Blockchain
Verification** card:

  - **PASSED** -- the transaction was mined and, where a hash applies (REC
    issuance), the on-chain hash matches the off-chain SQLite record.
  - **FAILED** -- either the on-chain hash didn't match (tamper detected --
    this is what actually drives a `CRITICAL` decision + freeze), or the
    chain rejected the transaction outright (e.g. an unauthorized signer).
    Never confused with an offline node -- see NOT_CONNECTED.
  - **PENDING** -- nothing has been submitted to the chain yet, most often
    because the transaction was held for fraud review (only a `LEGITIMATE`
    decision actually settles on-chain -- see `fraud_decision.py`).
  - **NOT_CONNECTED** -- the local Hardhat node was unreachable at the
    moment this was checked. The app keeps running normally in this state
    (see `blockchain_service.py`'s fail-soft design) and self-heals: the
    very next request after Hardhat comes back reconnects automatically,
    no restart needed.

  A transaction is only ever marked PASSED because it was actually verified
  -- never merely because the blockchain service happened to be available.

**7. Troubleshooting an occupied port** -- if `hardhat node` (8545),
`python app.py` (8000) or `npm run dev` (5173) refuses to start with an
"address already in use" error, something is already bound to that port
(commonly a previous run you forgot to stop). Find and stop it rather than
changing the port:

```powershell
# Windows PowerShell -- replace 8000 with 8545 / 5173 as needed
netstat -ano | findstr :8000
taskkill /F /PID <the PID number from the previous command>
```

```bash
# bash / WSL
lsof -i :8000        # find the PID
kill -9 <PID>
```

If the sidebar shows **Blockchain OFFLINE** but the port isn't the issue,
confirm `npx hardhat node` is actually running and that you redeployed +
reseeded (step 1) against *this* run of it -- every fresh `hardhat node`
process starts a brand-new chain, so a contract address from a previous run
won't exist on it. The backend self-heals once it can reach the node again
(no backend restart needed), but it only picks up a *new* contract address
on its own next reconnect attempt -- if you redeployed to a new address
while the backend was already connected to an old one, restart the backend
once so it re-reads `backend/chain/contract_address.json`.

If the dashboard looks frozen (no new rows in the Live Feed, stat cards not
updating), check the browser console for repeated WebSocket connection
errors. `frontend/src/api.js`'s `connectLiveFeed` auto-reconnects every 2s
on its own, so a one-off drop recovers by itself; if it's not recovering,
it's almost always the backend not running on the port the frontend expects
(`VITE_API_BASE`, or the page's own hostname:8000 by default) -- open
`http://<backend-host>:8000/api/health` directly in a browser tab to
confirm the API itself is reachable before assuming the WebSocket layer is
at fault.

## REC Verification Portal

Everything above is about the *simulator* generating and scoring activity
live. This section is a different, complementary feature: independently
re-checking one already-issued REC's integrity, on demand, for anyone --
an internal operator, another company, a buyer, an auditor -- who wasn't
watching the pipeline when it was issued and has no reason to just trust
whatever the database currently says.

**How to verify a REC** -- open **Verify REC** in the sidebar, enter a REC
id (copy one from the Certificates page or the Live Feed), optionally fill
in a company/verifier name to attribute the check, and click **Verify**.
This calls `POST /api/rec/{rec_id}/verify`, which:

1. Reads the REC's current data straight from SQLite (never cached).
2. Recalculates its canonical hash from `rec_id`, `generator_id`,
   `plant_capacity_mw`, `energy_generated_mwh`, `rec_quantity`,
   `generation_timestamp` and `issuance_timestamp` (see
   `verification_service.canonical_rec_hash` -- the exact same function
   runs at issuance time in `pipeline.py`, so the two can never drift apart
   by definition).
3. Compares that recalculated hash against the hash actually anchored
   on-chain (`RECRegistry.sol`'s `verifyREC`), and separately against
   quantity/owner/generator id/status the contract also stores.
4. Runs the physical-plausibility checks (negative values, REC quantity
   exceeding energy generated, energy exceeding a plausible plant ceiling).
5. Writes one `rec_verification_requests` row -- **every** attempt, success
   or failure, including an unknown REC id -- plus a hash-chained
   `rec_audit_log` entry, so the check itself becomes part of the
   permanent record.
6. Returns one of **VALID / SUSPICIOUS / INVALID / TAMPERED / NOT_FOUND /
   PENDING / UNCONFIRMED**, always with plain-language reasons, never just
   a color.

**How tamper detection actually works** -- at issuance
(`pipeline.process_generation_event`'s `LEGITIMATE` branch), the REC's
canonical hash is computed once and stored in `rec_records.generation_hash`
-- immutable from that point on, never recalculated or overwritten by
anything later in the app. Every subsequent verification recomputes the
*same* hash fresh from whatever the database says *right now* and compares
it. If nobody has touched the underlying rows, the two hashes match bit for
bit (SHA-256 is deterministic). If even one covered field changed --
`energy_generated_mwh` edited from 100 to 150, say -- the recalculated hash
comes out completely different, because that's what a cryptographic hash
is for. There's no partial match, no "close enough": either every input
byte was identical, or the hash is unrelated. That's what makes this a
real integrity check rather than a heuristic.

**How blockchain hashes protect REC integrity** -- the hash anchored at
issuance is also written on-chain (`RECRegistry.sol`'s `generation_data_hash`
field, set by `issueREC`). SQLite is a plain file an operator (or an
attacker with disk access) can edit directly; the local Hardhat chain, once
a transaction is mined, cannot be quietly edited the same way -- so
comparing "what does SQLite say right now" against "what's on chain" is a
second, independent check that doesn't share SQLite's weakness. Verification
compares three things: the current recalculated hash, the hash stored at
issuance, and the on-chain hash. All three should always agree; if the
current hash no longer matches while the on-chain hash still matches what
was originally anchored, that's specific, strong evidence the *local* copy
was edited after the fact -- which is exactly the scenario the demo below
walks through.

**How to demonstrate changing 100 MWh to 150 MWh** -- two ways:

- *Manual, for a live demo*: generate one REC (Simulation Control's manual
  form, or let the simulator issue one), note its `rec_id` from the Live
  Feed, then edit `backend/rec_fraud.db` directly with any SQLite tool (or
  a two-line Python script using `backend/database.py`'s `SessionLocal`) to
  change that REC's linked `generation_records.energy_generated_mwh` from
  100 to 150 -- deliberately bypassing the API, exactly like an attacker
  with raw database access would. Then run **Verify REC** on it: hash
  status flips to `MISMATCHED`, blockchain verification flips to `FAILED`
  (the on-chain hash no longer matches the edited local data), the result
  is `TAMPERED`, and a `CRITICAL` fraud alert appears on the Fraud Alerts
  page automatically.
- *Automatic, for repeated demos*: on the Simulation Control page, check
  **Enable Tampering Simulation** and pick a probability (5% by default).
  While running, the simulator will occasionally pick an already-issued,
  ACTIVE REC and apply the same 1.3x-1.8x multiplier to its energy/quantity
  directly in SQLite -- clearly logged in that REC's audit trail as a
  `REC_UPDATED` event from `SYSTEM_TAMPER_SIM`/`tamper_simulation`, and
  announced live as a `tamper_simulated` WebSocket toast -- but its
  anchored hash is deliberately left untouched, so it stays silently wrong
  until someone actually runs Verify REC on it. This is a **synthetic
  simulation for demonstration only**, clearly labeled as such everywhere
  it appears (the toggle's own label, the amber banner while it's on, the
  toast, and the audit log's `source` field) -- it is not a real intrusion
  and never touches the blockchain layer.

**Difference between ML fraud detection and cryptographic tamper
detection** -- these answer different questions and neither can substitute
for the other:

  | | ML / rule / graph fraud detection | Cryptographic tamper detection |
  |---|---|---|
  | Question | "Does this *behavior* look like fraud?" | "Does this *data* match what was originally recorded?" |
  | Runs | Once, at the moment a transaction happens (`pipeline.py`) | On demand, any time later, via Verify REC |
  | Basis | Statistics, thresholds, graph topology -- probabilistic | SHA-256 hash equality -- deterministic |
  | Can be "a bit suspicious" | Yes -- a risk score, a band, "mild anomaly" | No -- a hash either matches exactly or it doesn't |
  | Catches | Over-issuance, circular trading, rapid chains, dense clusters, statistical outliers | Direct data edits made after the fact, bypassing the app entirely |
  | Blind to | Someone editing history directly in the database after a transaction already looked fine | Behavioral patterns spread across many individually-valid transactions |

  Per `fraud_decision.py`'s and `verification_service.py`'s design, a
  confirmed cryptographic mismatch always wins: `_decide_result()` returns
  `TAMPERED` whenever the hash or on-chain check fails, regardless of how
  low the associated ML/graph risk score happens to be. ML informs *how
  suspicious a live transaction looked*; it is never allowed to override
  *proof that stored data no longer matches what was cryptographically
  anchored*.

**How to share verification details** -- after running Verify REC, use
**Share Verification Report (JSON)** to download the exact result as a
file (`POST /api/verification/report`, keyed only by `verification_id` --
the endpoint re-serves what was actually decided and stored at
verification time, never anything the client sends), or **Print / Save as
PDF** to open a formatted printable version through the browser's own
print dialog. Either way the report can be handed to another company or an
auditor without giving them any access to the database itself, and it
cannot be edited into showing a different result than what was actually
found.

**Verification History** (sidebar) lists every verification ever
performed, filterable by REC id, company, result and blockchain status --
the same append-only table the Dashboard's Verification Summary card
summarizes.

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

- **Verification**: real, cryptographic. `verification_service.py`'s
  canonical hash and its comparison against the on-chain hash are genuine
  SHA-256 checks against real data -- not a simulated "trust me" result.
  The only synthetic part is the optional tamper *scenario itself* (an
  ordinary demo/test tool for producing something to catch), never the
  detection logic that catches it.

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
- The stored-original-hash defense (`rec_records.generation_hash`) assumes
  an attacker can edit ordinary data columns but doesn't also rewrite that
  hash column and doesn't control the blockchain -- true for "someone with
  a SQLite browser," not for a fully compromised database server. The
  on-chain comparison is what makes this meaningfully harder to fake than a
  local checksum alone, since the chain can't be quietly rewritten the same
  way a file can.
- `POST /api/rec/{rec_id}/verify` has no rate limiting in this build (spec
  section 16 flags it as recommended) -- fine for a hackathon demo, not for
  a publicly reachable deployment.

## Project layout

```
backend/        FastAPI app, SQLAlchemy models, pipeline, ML/graph/blockchain/verification services
contracts/      Solidity contract + Hardhat project (compile/deploy/test)
ml_training/    Standalone scripts to train a better tx-level model (Colab-friendly)
frontend/       React + Vite dashboard
```
