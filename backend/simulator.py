"""
Background simulation engine (spec sections 5-7). Runs in its own daemon
thread so it never blocks the API server. Every SIMULATION_INTERVAL_SECONDS
it either:
  - reports a normal (or occasionally fraudulent) generation reading, or
  - moves an existing REC between entities (normal trade, or a forced fraud
    pattern: circular trading, rapid chain, dense cluster, retired reuse),
and pushes the full pipeline result out over the WebSocket.
"""
from __future__ import annotations

import logging
import random
import threading
import time

import config
import graph_service
import models
import pipeline
import websocket_service
from database import SessionLocal

logger = logging.getLogger("simulator")

# entities with real seeded Hardhat wallets -- transfers among these actually
# hit the chain. "Clean" pool entities are off-chain-only strings; the
# pipeline gracefully marks their blockchain sync as pending (see
# pipeline._resolve_address / blockchain_service.TxResult.pending_sync).
FRAUD_RING = ["Trader: Broker X", "Trader: Broker Y", "Trader: Company B", "Trader: Company C"]
CLEAN_TRADERS = ["GreenBuy Industries", "EcoRetail Ltd", "Fairtrade Broker Co", "SunTrust Energy Buyers"]

FRAUD_SCENARIOS = [
    "OVER_ISSUANCE", "DUPLICATE_GENERATION", "CAPACITY_VIOLATION", "RETIRED_REC_REUSE",
    "CIRCULAR_TRADING", "RAPID_TRANSFER_CHAIN", "SUSPICIOUS_DENSE_CLUSTER",
]


def _capacity_factor(plant_type: str) -> float:
    hour = time.localtime().tm_hour
    if plant_type == "Solar":
        return random.uniform(0.55, 0.9) if 7 <= hour <= 18 else random.uniform(0.0, 0.05)
    if plant_type == "Wind":
        return random.uniform(0.1, 0.85)
    return random.uniform(0.45, 0.8)  # Hydro: more stable


def _normal_generation(db) -> dict:
    generators = db.query(models.Generator).filter_by(registration_status="ACTIVE").all()
    if not generators:
        return {"skipped": "no registered generators"}
    gen = random.choice(generators)
    factor = _capacity_factor(gen.plant_type)
    energy = round(gen.capacity_mw * factor, 2)
    weather = round(random.uniform(0.6, 1.0), 2)
    return pipeline.process_generation_event(db, gen.generator_id, energy, weather)


def _normal_transfer(db) -> dict:
    active = db.query(models.RECRecord).filter_by(status="ACTIVE").all()
    if not active:
        return {"skipped": "no active RECs to transfer"}
    rec = random.choice(active)
    receiver = random.choice(CLEAN_TRADERS + FRAUD_RING)
    return pipeline.process_transfer(db, rec.rec_id, rec.current_owner, receiver, rec.quantity)


def _fraud_over_issuance(db) -> dict:
    generators = db.query(models.Generator).filter_by(registration_status="ACTIVE").all()
    if not generators:
        return {"skipped": "no registered generators"}
    gen = random.choice(generators)
    energy = round(gen.capacity_mw * random.uniform(0.3, 0.6), 2)
    inflated_quantity = round(energy * random.uniform(3, 6), 2)
    return pipeline.process_generation_event(db, gen.generator_id, energy, 0.8, rec_quantity=inflated_quantity)


def _fraud_duplicate_generation(db) -> dict:
    prior = db.query(models.RECRecord).order_by(models.RECRecord.id.desc()).first()
    if prior is None:
        return _normal_generation(db)
    gen = db.query(models.Generator).filter_by(generator_id=prior.generator_id).first()
    energy = round(gen.capacity_mw * random.uniform(0.3, 0.6), 2) if gen else 50
    return pipeline.process_generation_event(
        db, prior.generator_id, energy, 0.8, reuse_generation_id=prior.generation_id, force_duplicate_flag=True,
    )


def _fraud_capacity_violation(db) -> dict:
    generators = db.query(models.Generator).filter_by(registration_status="ACTIVE").all()
    if not generators:
        return {"skipped": "no registered generators"}
    gen = random.choice(generators)
    impossible_energy = round(gen.capacity_mw * random.uniform(12, 20), 2)
    return pipeline.process_generation_event(db, gen.generator_id, impossible_energy, 1.0)


def _fraud_retired_reuse(db) -> dict:
    retired = db.query(models.RECRecord).filter_by(status="RETIRED").all()
    if not retired:
        # nothing retired yet -- retire one now so the next tick can reuse it
        active = db.query(models.RECRecord).filter_by(status="ACTIVE").first()
        if active:
            pipeline.retire_rec(db, active.rec_id, active.current_owner)
        return {"skipped": "retired a REC this tick; reuse attempt will trigger next fraud tick"}
    rec = random.choice(retired)
    return pipeline.process_transfer(db, rec.rec_id, rec.current_owner, random.choice(CLEAN_TRADERS), rec.quantity)


def _fraud_circular_trading(db) -> dict:
    """Push a REC one hop further around the fraud ring; over several ticks
    this naturally closes a cycle (Broker X -> Company B -> Broker Y -> Company C -> Broker X)."""
    active = db.query(models.RECRecord).filter(
        models.RECRecord.status == "ACTIVE", models.RECRecord.current_owner.isnot(None)
    ).all()
    ring_owned = [r for r in active if pipeline._label_for(r.current_owner) in FRAUD_RING]
    if not ring_owned:
        # seed the ring: push a fresh REC from its generator into the ring
        result = _normal_generation(db)
        rec = result.get("rec")
        if not rec or rec.get("status") != "ACTIVE":
            return result
        return pipeline.process_transfer(db, rec["rec_id"], rec["current_owner"], FRAUD_RING[0], rec["quantity"])

    rec = random.choice(ring_owned)
    current_label = pipeline._label_for(rec.current_owner)
    idx = FRAUD_RING.index(current_label) if current_label in FRAUD_RING else -1
    next_hop = FRAUD_RING[(idx + 1) % len(FRAUD_RING)]
    return pipeline.process_transfer(db, rec.rec_id, rec.current_owner, next_hop, rec.quantity)


def _fraud_rapid_transfer_chain(db) -> dict:
    active = db.query(models.RECRecord).filter_by(status="ACTIVE").all()
    if not active:
        return {"skipped": "no active RECs"}
    rec = random.choice(active)
    chain_entities = random.sample(FRAUD_RING, k=min(3, len(FRAUD_RING)))
    last_result = None
    owner = rec.current_owner
    for hop in chain_entities:
        last_result = pipeline.process_transfer(db, rec.rec_id, owner, hop, rec.quantity)
        if "error" in last_result or last_result["decision"]["decision"] != "LEGITIMATE":
            break
        owner = hop
    return last_result or {"skipped": "no hops executed"}


def _fraud_dense_cluster(db) -> dict:
    active = db.query(models.RECRecord).filter_by(status="ACTIVE").all()
    if not active:
        return {"skipped": "no active RECs"}
    rec = random.choice(active)
    a, b = random.sample(FRAUD_RING, 2)
    return pipeline.process_transfer(db, rec.rec_id, rec.current_owner, random.choice([a, b]), rec.quantity)


FRAUD_HANDLERS = {
    "OVER_ISSUANCE": _fraud_over_issuance,
    "DUPLICATE_GENERATION": _fraud_duplicate_generation,
    "CAPACITY_VIOLATION": _fraud_capacity_violation,
    "RETIRED_REC_REUSE": _fraud_retired_reuse,
    "CIRCULAR_TRADING": _fraud_circular_trading,
    "RAPID_TRANSFER_CHAIN": _fraud_rapid_transfer_chain,
    "SUSPICIOUS_DENSE_CLUSTER": _fraud_dense_cluster,
}


class Simulator:
    def __init__(self):
        self.interval = config.SIMULATION_INTERVAL_SECONDS
        self.fraud_probability = config.FRAUD_PROBABILITY
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.running = False
        self.ticks = 0
        self.last_result: dict | None = None

    def configure(self, interval_seconds: float | None = None, fraud_probability: float | None = None) -> None:
        if interval_seconds is not None:
            self.interval = max(1.0, interval_seconds)
        if fraud_probability is not None:
            self.fraud_probability = min(max(fraud_probability, 0.0), 1.0)

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.running = True
        self._thread.start()
        logger.info("Simulator started (interval=%.1fs, fraud_probability=%.2f)", self.interval, self.fraud_probability)

    def stop(self) -> None:
        self.running = False
        self._stop_event.set()
        logger.info("Simulator stopped")

    def status(self) -> dict:
        return {
            "running": self.running, "interval_seconds": self.interval,
            "fraud_probability": self.fraud_probability, "ticks": self.ticks,
        }

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("simulator tick failed")
            self._stop_event.wait(self.interval)

    def tick(self) -> dict:
        db = SessionLocal()
        try:
            self.ticks += 1
            is_fraud = random.random() < self.fraud_probability
            if is_fraud:
                scenario = random.choice(FRAUD_SCENARIOS)
                result = FRAUD_HANDLERS[scenario](db)
                result = result or {}
                result["injected_scenario"] = scenario
            else:
                result = _normal_generation(db) if random.random() < 0.65 else _normal_transfer(db)

            result["tick"] = self.ticks
            result["is_fraud_injected"] = is_fraud
            self.last_result = result

            graph_engine = graph_service.get_engine()
            graph_engine.build(db)
            graph_engine.sync_clusters_to_db(db)
            graph_engine.sync_entities_to_db(db)

            websocket_service.broadcast_sync({"type": "pipeline_result", "data": result})
            return result
        finally:
            db.close()


_simulator = Simulator()


def get_simulator() -> Simulator:
    return _simulator
