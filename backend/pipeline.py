"""
The complete transaction pipeline (see project spec section 20):

  1. Generate/receive transaction data
  2. Save raw data to SQLite
  3. Generate a SHA-256 hash of the generation data
  4. Rule-based validation
  5. Extract ML features
  6. Run Isolation Forest (transaction-level model)
  7. Update the NetworkX graph
  8. Run graph fraud detection
  9. Check blockchain integrity
 10. Calculate final risk score (fraud_decision.combine)
 11. If legitimate: issue/transfer on the blockchain
 12. If suspicious: hold + create a fraud_alerts row
 13. If critical: freeze (never auto-revoke -- see fraud_decision.py docstring)
 14. Save results to SQLite
 15. Return the result (websocket_service broadcasts it)
"""
from __future__ import annotations

import hashlib
import json
import logging
import time

from sqlalchemy.orm import Session

import config
import fraud_decision
import graph_service
import models
import ml_service
import rules_engine
from blockchain_service import get_service as get_chain

logger = logging.getLogger("pipeline")


def _hash_payload(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def _counterparties_last_24h(db: Session, entity: str) -> int:
    cutoff = time.time() - 86400
    rows = db.query(models.RECTransaction).filter(
        models.RECTransaction.transaction_timestamp >= cutoff,
        (models.RECTransaction.sender == entity) | (models.RECTransaction.receiver == entity),
    ).all()
    parties = {r.sender for r in rows if r.sender and r.sender != entity}
    parties |= {r.receiver for r in rows if r.receiver and r.receiver != entity}
    return len(parties)


def _frequency_last_24h(db: Session, tx_type: str, entity: str | None = None) -> int:
    cutoff = time.time() - 86400
    q = db.query(models.RECTransaction).filter(
        models.RECTransaction.transaction_timestamp >= cutoff,
        models.RECTransaction.transaction_type == tx_type,
    )
    if entity:
        q = q.filter((models.RECTransaction.sender == entity) | (models.RECTransaction.receiver == entity))
    return q.count()


def _velocity_last_10min(db: Session, entity: str) -> int:
    cutoff = time.time() - 600
    return db.query(models.RECTransaction).filter(
        models.RECTransaction.transaction_timestamp >= cutoff,
        (models.RECTransaction.sender == entity) | (models.RECTransaction.receiver == entity),
    ).count()


def _create_alert(db: Session, decision: dict, rec_id: str | None, generation_id: str | None,
                   transaction_id: str | None, fraud_type: str) -> models.FraudAlert:
    alert = models.FraudAlert(
        rec_id=rec_id, generation_id=generation_id, transaction_id=transaction_id,
        rule_score=decision["rule_score"], ml_score=decision["ml_score"], graph_score=decision["graph_score"],
        final_risk_score=decision["final_risk_score"], risk_level=decision["risk_level"],
        fraud_type=fraud_type, reasons=json.dumps(decision["reasons"]), status="OPEN",
    )
    db.add(alert)
    db.flush()
    return alert


def _infer_fraud_type(decision: dict, rule_violations: list[str]) -> str | None:
    if decision["decision"] == "LEGITIMATE":
        return None
    joined = " ".join(rule_violations).lower()
    if "capacity" in joined:
        return "CAPACITY_VIOLATION"
    if "already been used" in joined:
        return "DUPLICATE_GENERATION"
    if "exceeds generated energy" in joined:
        return "OVER_ISSUANCE"
    if "retired" in joined or "revoked" in joined:
        return "RETIRED_REC_REUSE"
    if "circular" in " ".join(decision["reasons"]).lower():
        return "CIRCULAR_TRADING"
    if "rapid transfer" in " ".join(decision["reasons"]).lower():
        return "RAPID_TRANSFER_CHAIN"
    if "dense" in " ".join(decision["reasons"]).lower():
        return "SUSPICIOUS_DENSE_CLUSTER"
    return "ANOMALY"


# ==================================================================== generation -> REC issuance

def process_generation_event(db: Session, generator_id: str, energy_generated_mwh: float,
                              weather_factor: float, rec_quantity: float | None = None,
                              reuse_generation_id: str | None = None,
                              force_duplicate_flag: bool = False) -> dict:
    generator = db.query(models.Generator).filter_by(generator_id=generator_id).first()
    if generator is None:
        return {"error": f"unknown generator_id '{generator_id}'"}

    rec_quantity = rec_quantity if rec_quantity is not None else energy_generated_mwh
    now = time.time()

    # step 2: raw generation data -> SQLite
    generation = models.GenerationRecord(
        generator_id=generator_id, generation_timestamp=now,
        energy_generated_mwh=energy_generated_mwh, weather_factor=weather_factor, is_synthetic=True,
    )
    db.add(generation)
    db.flush()

    # step 3: hash anchor
    data_hash = _hash_payload({
        "generation_id": generation.generation_id, "generator_id": generator_id,
        "energy_generated_mwh": energy_generated_mwh, "timestamp": now,
    })
    generation.meter_data_hash = data_hash
    db.flush()

    effective_generation_id = reuse_generation_id or generation.generation_id  # simulate duplicate-generation fraud

    # step 4: rules
    rules_result = rules_engine.validate_generation(
        db, generator_id=generator_id, capacity_mw=generator.capacity_mw,
        energy_generated_mwh=energy_generated_mwh, rec_quantity=rec_quantity,
        generation_id=effective_generation_id, generation_timestamp=now, issue_timestamp=now,
    )

    # step 5-6: ML (transaction-level features for this issuance)
    issuance_freq = _frequency_last_24h(db, "ISSUE", generator_id)
    tx_features = {
        "plant_capacity_mw": generator.capacity_mw,
        "energy_generated_mwh": energy_generated_mwh,
        "rec_quantity": rec_quantity,
        "generation_rec_ratio": (rec_quantity / energy_generated_mwh) if energy_generated_mwh else 0,
        "capacity_utilization": min(energy_generated_mwh / (generator.capacity_mw * 6), 2) if generator.capacity_mw else 0,
        "weather_factor": weather_factor,
        "time_gap_generation_to_issuance": 0.01,
        "issuance_frequency_last_24h": issuance_freq,
        "transfer_frequency_last_24h": 0,
        "transaction_velocity_last_10min": _velocity_last_10min(db, generator_id),
        "number_of_counterparties": 0,
        "account_age_days": max((now - generator.created_at) / 86400, 0),
        "previous_alert_count": db.query(models.FraudAlert).filter_by(generation_id=effective_generation_id).count(),
        "retirement_reuse_flag": 0,
        "duplicate_generation_flag": int(force_duplicate_flag or bool(reuse_generation_id)),
    }
    graph_engine = graph_service.get_engine()
    graph_engine.build(db)
    tx_features.update(graph_engine.transaction_graph_features(generator_id, generator_id))
    ml_result = ml_service.get_service().score_transaction(tx_features)

    # also run the two original REC-issuance models supplied for this project
    # (different, plant/vintage-level schema -- see ml_service.py) and fold
    # their signal in, so both the new transaction-level model and the
    # original pair of models genuinely participate in every issuance decision.
    legacy_rec_view = {
        "plant_capacity_mw": generator.capacity_mw,
        "fuel_type": generator.plant_type,
        "state": generator.state,
        "accreditation_year": time.localtime(generator.created_at).tm_year,
        "vintage_month": time.localtime(now).tm_mon,
        "generation_expected_mwh": generator.capacity_mw * 6,  # same plausible-ceiling proxy rules_engine uses
        "generation_claimed_mwh": energy_generated_mwh,
        "num_transfers": 0,
        "days_to_retirement": None,
        "self_retention_flag": False,
        "duplicate_flag": force_duplicate_flag or bool(reuse_generation_id),
        "status": "issued",
    }
    legacy_result = ml_service.get_service().score_generation_event(legacy_rec_view)
    if legacy_result.get("available"):
        ml_result["ml_score"] = max(ml_result["ml_score"], legacy_result["combined_score"])
        if legacy_result["is_outlier"]:
            ml_result["reasons"].append(
                f"legacy REC-issuance model flagged this as a statistical outlier "
                f"(anomaly {legacy_result['anomaly_score']}, risk {legacy_result['risk_score']}%)"
            )
    ml_result["legacy"] = legacy_result

    # step 7-8: graph (issuance has no transfer edge yet; graph score comes from
    # the generator's existing cluster membership, if any)
    graph_clusters = graph_engine.suspicious_clusters()
    generator_cluster = next((c for c in graph_clusters if generator_id in c["entity_ids"]), None)
    graph_score = generator_cluster["graph_score"] if generator_cluster else 0
    graph_patterns = generator_cluster["patterns"] if generator_cluster else []

    # step 9: blockchain integrity gate (nothing on-chain yet for a brand new
    # generation event, so integrity trivially holds)
    blockchain_integrity_ok = True

    # step 10: decision
    decision = fraud_decision.combine(
        rule_score=rules_result["rule_score"], ml_score=ml_result["ml_score"], graph_score=graph_score,
        blockchain_integrity_ok=blockchain_integrity_ok, rule_violations=rules_result["violations"],
        ml_reasons=ml_result["reasons"], graph_patterns=graph_patterns,
    )

    rec = models.RECRecord(
        generation_id=generation.generation_id, generator_id=generator_id, quantity=rec_quantity,
        issue_timestamp=now, current_owner=generator.wallet_address or generator_id,
        generation_hash=data_hash,
    )

    chain = get_chain()
    if decision["decision"] == "LEGITIMATE":
        rec.status = "ACTIVE"
        db.add(rec)
        db.flush()
        db.add(models.RECTransaction(
            rec_id=rec.rec_id, sender=None, receiver=rec.current_owner,
            transaction_type="ISSUE", quantity=rec_quantity, transaction_timestamp=now,
        ))
        db.add(models.GraphEdge(
            source_entity="ISSUANCE", target_entity=rec.current_owner, relationship_type="ISSUED",
            rec_id=rec.rec_id, quantity=rec_quantity, transaction_timestamp=now,
        ))
        chain_result = chain.issue_rec(rec.rec_id, generator_id, rec_quantity, _resolve_address(rec.current_owner), data_hash)
        rec.blockchain_tx_hash = chain_result.tx_hash
        if not chain_result.ok:
            logger.warning("blockchain issue_rec failed/pending for %s: %s", rec.rec_id, chain_result.error)
    else:
        # step 12/13: hold, never auto-revoke
        rec.status = "HELD"
        db.add(rec)
        db.flush()
        fraud_type = _infer_fraud_type(decision, rules_result["violations"])
        _create_alert(db, decision, rec.rec_id, generation.generation_id, None, fraud_type)

    db.commit()

    logger.info(
        "[%s] generation=%s rule=%.0f ml=%.0f graph=%.0f final=%.0f decision=%s",
        time.strftime("%H:%M:%S"), generation.generation_id,
        rules_result["rule_score"], ml_result["ml_score"], graph_score,
        decision["final_risk_score"], decision["decision"],
    )

    return {
        "generation": _serialize(generation), "rec": _serialize(rec),
        "rules": rules_result, "ml": ml_result, "graph": {"graph_score": graph_score, "patterns": graph_patterns},
        "decision": decision,
    }


# ==================================================================== transfer / retire

def process_transfer(db: Session, rec_id: str, sender: str, receiver: str, quantity: float) -> dict:
    rec = db.query(models.RECRecord).filter_by(rec_id=rec_id).first()
    if rec is None:
        return {"error": f"unknown rec_id '{rec_id}'"}

    now = time.time()
    rules_result = rules_engine.validate_transaction(db, rec_id=rec_id, sender=sender, receiver=receiver)

    graph_engine = graph_service.get_engine()
    graph_engine.build(db)
    tx_features = {
        "plant_capacity_mw": 0, "energy_generated_mwh": 0, "rec_quantity": quantity,
        "generation_rec_ratio": 1, "capacity_utilization": 0, "weather_factor": 1,
        "time_gap_generation_to_issuance": (now - rec.issue_timestamp) / 3600,
        "issuance_frequency_last_24h": 0,
        "transfer_frequency_last_24h": _frequency_last_24h(db, "TRANSFER", sender),
        "transaction_velocity_last_10min": _velocity_last_10min(db, sender),
        "number_of_counterparties": _counterparties_last_24h(db, sender),
        "account_age_days": 365, "previous_alert_count": db.query(models.FraudAlert).filter_by(rec_id=rec_id).count(),
        "retirement_reuse_flag": int(rec.status in ("RETIRED", "REVOKED")),
        "duplicate_generation_flag": 0,
    }
    tx_features.update(graph_engine.transaction_graph_features(sender, receiver))
    ml_result = ml_service.get_service().score_transaction(tx_features)

    clusters = graph_engine.suspicious_clusters()
    involved = next((c for c in clusters if sender in c["entity_ids"] or receiver in c["entity_ids"]), None)
    graph_score = involved["graph_score"] if involved else 0
    graph_patterns = involved["patterns"] if involved else []

    chain = get_chain()
    onchain = chain.verify_rec(rec_id)
    blockchain_integrity_ok = True
    if onchain is not None and rec.generation_hash:
        blockchain_integrity_ok = onchain["generation_data_hash"].lstrip("0") == rec.generation_hash.lstrip("0") \
            or onchain["generation_data_hash"] == rec.generation_hash

    decision = fraud_decision.combine(
        rule_score=rules_result["rule_score"], ml_score=ml_result["ml_score"], graph_score=graph_score,
        blockchain_integrity_ok=blockchain_integrity_ok, rule_violations=rules_result["violations"],
        ml_reasons=ml_result["reasons"], graph_patterns=graph_patterns,
    )

    transaction = models.RECTransaction(
        rec_id=rec_id, sender=sender, receiver=receiver, transaction_type="TRANSFER",
        quantity=quantity, transaction_timestamp=now,
    )

    if decision["decision"] == "LEGITIMATE":
        rec.current_owner = receiver
        db.add(transaction)
        db.add(models.GraphEdge(
            source_entity=sender, target_entity=receiver, relationship_type="TRANSFERRED",
            rec_id=rec_id, quantity=quantity, transaction_timestamp=now,
        ))
        chain_result = chain.transfer_rec(rec_id, _label_for(sender), _resolve_address(receiver))
        transaction.blockchain_tx_hash = chain_result.tx_hash
        db.flush()
    else:
        fraud_type = _infer_fraud_type(decision, rules_result["violations"])
        db.add(transaction)
        db.flush()
        _create_alert(db, decision, rec_id, rec.generation_id, transaction.transaction_id, fraud_type)
        if decision["decision"] == "CRITICAL":
            chain.freeze_rec(rec_id)
            rec.status = "HELD"

    db.commit()

    logger.info(
        "[%s] transfer=%s rec=%s rule=%.0f ml=%.0f graph=%.0f final=%.0f decision=%s",
        time.strftime("%H:%M:%S"), transaction.transaction_id, rec_id,
        rules_result["rule_score"], ml_result["ml_score"], graph_score,
        decision["final_risk_score"], decision["decision"],
    )

    return {"transaction": _serialize(transaction), "rules": rules_result, "ml": ml_result,
            "graph": {"graph_score": graph_score, "patterns": graph_patterns}, "decision": decision}


def retire_rec(db: Session, rec_id: str, owner: str) -> dict:
    rec = db.query(models.RECRecord).filter_by(rec_id=rec_id).first()
    if rec is None:
        return {"error": f"unknown rec_id '{rec_id}'"}
    if rec.status != "ACTIVE":
        return {"error": f"REC '{rec_id}' is not ACTIVE (status={rec.status})"}

    now = time.time()
    rec.status = "RETIRED"
    transaction = models.RECTransaction(
        rec_id=rec_id, sender=owner, receiver=None, transaction_type="RETIRE",
        quantity=rec.quantity, transaction_timestamp=now,
    )
    chain_result = get_chain().retire_rec(rec_id, _label_for(owner))
    transaction.blockchain_tx_hash = chain_result.tx_hash
    db.add(transaction)
    db.commit()

    logger.info("[%s] retire=%s rec=%s owner=%s", time.strftime("%H:%M:%S"), transaction.transaction_id, rec_id, owner)
    return {"transaction": _serialize(transaction), "rec": _serialize(rec)}


def revoke_rec(db: Session, rec_id: str, reason: str) -> dict:
    """Only ever called by an explicit regulator action -- see fraud_decision.py."""
    rec = db.query(models.RECRecord).filter_by(rec_id=rec_id).first()
    if rec is None:
        return {"error": f"unknown rec_id '{rec_id}'"}

    now = time.time()
    rec.status = "REVOKED"
    transaction = models.RECTransaction(
        rec_id=rec_id, sender="REGULATOR", receiver=None, transaction_type="REVOKE",
        quantity=rec.quantity, transaction_timestamp=now,
    )
    chain_result = get_chain().revoke_rec(rec_id, reason)
    transaction.blockchain_tx_hash = chain_result.tx_hash
    db.add(transaction)

    alert = db.query(models.FraudAlert).filter_by(rec_id=rec_id, status="OPEN").first()
    if alert:
        alert.status = "RESOLVED"

    db.commit()

    logger.info(
        "[%s] revoke=%s rec=%s reason=%r", time.strftime("%H:%M:%S"), transaction.transaction_id, rec_id, reason,
    )
    return {"transaction": _serialize(transaction), "rec": _serialize(rec)}


def verify_generation_hash(db: Session, generation_id: str) -> dict:
    generation = db.query(models.GenerationRecord).filter_by(generation_id=generation_id).first()
    if generation is None:
        return {"error": "generation record not found"}

    recomputed = _hash_payload({
        "generation_id": generation.generation_id, "generator_id": generation.generator_id,
        "energy_generated_mwh": generation.energy_generated_mwh, "timestamp": generation.generation_timestamp,
    })
    valid = recomputed == generation.meter_data_hash
    return {"valid": valid, "tampered": not valid, "stored_hash": generation.meter_data_hash, "recomputed_hash": recomputed}


# ==================================================================== helpers

def _resolve_address(owner: str) -> str:
    """owner may already be a 0x address, or an entity/generator id -- fall
    back to a deterministic placeholder checksum address derived from the id
    so blockchain calls never crash on an unmapped owner during simulation."""
    if owner and owner.startswith("0x") and len(owner) == 42:
        return owner
    chain = get_chain()
    wallet = chain.wallets.get(owner)
    if wallet:
        return wallet["address"]
    digest = hashlib.sha256((owner or "unknown").encode()).hexdigest()[:40]
    return "0x" + digest


def _label_for(entity: str) -> str:
    chain = get_chain()
    if entity in chain.wallets:
        return entity
    for label, w in chain.wallets.items():
        if w["address"].lower() == (entity or "").lower():
            return label
    return entity


def _serialize(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
