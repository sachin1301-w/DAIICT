from __future__ import annotations

import json
import time

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
import pipeline
import schemas
import verification_service
import websocket_service
from blockchain_service import get_service as get_chain
from database import get_db
from graph_service import get_engine as get_graph_engine
from simulator import get_simulator

router = APIRouter(prefix="/api")

_MAX_REC_ID_LEN = 60


def _validate_rec_id(rec_id: str) -> str:
    if not rec_id or len(rec_id) > _MAX_REC_ID_LEN or not all(c.isalnum() or c in "-_" for c in rec_id):
        raise HTTPException(400, "invalid rec_id")
    return rec_id


def _alert_dict(a: models.FraudAlert) -> dict:
    d = {c.name: getattr(a, c.name) for c in a.__table__.columns}
    d["reasons"] = json.loads(a.reasons or "[]")
    return d


def _rec_dict(r: models.RECRecord) -> dict:
    return {c.name: getattr(r, c.name) for c in r.__table__.columns}


def _tx_dict(t: models.RECTransaction) -> dict:
    return {c.name: getattr(t, c.name) for c in t.__table__.columns}


# ---------------------------------------------------------------- health / dashboard

@router.get("/health")
def health():
    return {"status": "ok", "time": time.time(), "blockchain": get_chain().status()}


@router.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    total_generators = db.query(models.Generator).count()
    total_recs = db.query(models.RECRecord).count()
    active_recs = db.query(models.RECRecord).filter_by(status="ACTIVE").count()
    retired_recs = db.query(models.RECRecord).filter_by(status="RETIRED").count()
    total_transactions = db.query(models.RECTransaction).count()
    alerts = db.query(models.FraudAlert).all()
    suspicious_tx = len({a.transaction_id for a in alerts if a.transaction_id})
    avg_risk = round(sum(a.final_risk_score for a in alerts) / len(alerts), 2) if alerts else 0.0

    # Blockchain verification card: counted off rec_transactions so it reads
    # zero right after a reset, same as everything else on this page.
    status_rows = db.query(models.RECTransaction.blockchain_status, func.count(models.RECTransaction.id)) \
        .group_by(models.RECTransaction.blockchain_status).all()
    status_counts = {(status or "PENDING"): count for status, count in status_rows}
    blockchain_verification = {
        "passed": status_counts.get("PASSED", 0),
        "failed": status_counts.get("FAILED", 0),
        "pending": status_counts.get("PENDING", 0),
        "not_connected": status_counts.get("NOT_CONNECTED", 0),
    }

    # Verification Portal summary card (section 14). Deliberately NOT scoped
    # to rec_transactions/the current simulation run -- verification
    # requests survive Reset Transactions (see simulator._RESET_TABLES), so
    # this reflects the full compliance history, not just the live demo run.
    ver_result_rows = db.query(models.RECVerificationRequest.result, func.count(models.RECVerificationRequest.id)) \
        .group_by(models.RECVerificationRequest.result).all()
    ver_result_counts = {r: c for r, c in ver_result_rows}
    ver_bc_rows = db.query(models.RECVerificationRequest.blockchain_status, func.count(models.RECVerificationRequest.id)) \
        .group_by(models.RECVerificationRequest.blockchain_status).all()
    ver_bc_counts = {(s or "PENDING"): c for s, c in ver_bc_rows}
    verification_summary = {
        "total": sum(ver_result_counts.values()),
        "valid": ver_result_counts.get("VALID", 0),
        "suspicious": ver_result_counts.get("SUSPICIOUS", 0),
        "tampered": ver_result_counts.get("TAMPERED", 0),
        "not_found": ver_result_counts.get("NOT_FOUND", 0),
        "pending": ver_result_counts.get("PENDING", 0),
        "unconfirmed": ver_result_counts.get("UNCONFIRMED", 0),
        "invalid": ver_result_counts.get("INVALID", 0),
        "blockchain_passed": ver_bc_counts.get("PASSED", 0),
        "blockchain_failed": ver_bc_counts.get("FAILED", 0),
        "blockchain_pending": ver_bc_counts.get("PENDING", 0),
        "blockchain_not_connected": ver_bc_counts.get("NOT_CONNECTED", 0),
    }

    return {
        "total_generators": total_generators,
        "total_recs_issued": total_recs,
        "active_recs": active_recs,
        "retired_recs": retired_recs,
        "total_transactions": total_transactions,
        "suspicious_transactions": suspicious_tx,
        "fraud_alerts": len(alerts),
        "open_fraud_alerts": len([a for a in alerts if a.status == "OPEN"]),
        "average_risk_score": avg_risk,
        "blockchain_verification": blockchain_verification,
        "verification_summary": verification_summary,
        "simulation": get_simulator().status(),
        "blockchain": get_chain().status(),
    }


# ---------------------------------------------------------------- generators

@router.get("/generators")
def list_generators(db: Session = Depends(get_db)):
    rows = db.query(models.Generator).all()
    return [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in rows]


@router.post("/generators")
def create_generator(payload: schemas.GeneratorCreate, db: Session = Depends(get_db)):
    gen = models.Generator(**payload.model_dump())
    db.add(gen)
    db.commit()
    return {c.name: getattr(gen, c.name) for c in gen.__table__.columns}


# ---------------------------------------------------------------- transactions / certificates

@router.get("/transactions")
def list_transactions(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(models.RECTransaction).order_by(models.RECTransaction.transaction_timestamp.desc()).limit(limit).all()
    return [_tx_dict(r) for r in rows]


@router.get("/certificates")
def list_certificates(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(models.RECRecord)
    if status:
        q = q.filter_by(status=status.upper())
    rows = q.order_by(models.RECRecord.issue_timestamp.desc()).all()
    return [_rec_dict(r) for r in rows]


@router.post("/certificates/{rec_id}/retire")
def retire_certificate(rec_id: str, db: Session = Depends(get_db)):
    rec = db.query(models.RECRecord).filter_by(rec_id=rec_id).first()
    if not rec:
        raise HTTPException(404, "REC not found")
    result = pipeline.retire_rec(db, rec_id, rec.current_owner)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/certificates/{rec_id}/revoke")
def revoke_certificate(rec_id: str, payload: schemas.RevokeRequest, db: Session = Depends(get_db)):
    result = pipeline.revoke_rec(db, rec_id, payload.reason or "regulator action")
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ---------------------------------------------------------------- alerts

@router.get("/alerts")
def list_alerts(risk_level: str | None = None, db: Session = Depends(get_db)):
    q = db.query(models.FraudAlert)
    if risk_level:
        q = q.filter_by(risk_level=risk_level.upper())
    rows = q.order_by(models.FraudAlert.created_at.desc()).all()
    return [_alert_dict(a) for a in rows]


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: str, db: Session = Depends(get_db)):
    alert = db.query(models.FraudAlert).filter_by(alert_id=alert_id).first()
    if not alert:
        raise HTTPException(404, "alert not found")
    d = _alert_dict(alert)

    d["rec"] = None
    d["blockchain"] = None
    d["lifecycle"] = []
    d["related_entities"] = []
    if alert.rec_id:
        rec = db.query(models.RECRecord).filter_by(rec_id=alert.rec_id).first()
        d["rec"] = _rec_dict(rec) if rec else None
        d["blockchain"] = get_chain().verify_rec(alert.rec_id)
        lifecycle = db.query(models.RECTransaction).filter_by(rec_id=alert.rec_id) \
            .order_by(models.RECTransaction.transaction_timestamp).all()
        d["lifecycle"] = [_tx_dict(t) for t in lifecycle]
        entities = {t.sender for t in lifecycle if t.sender} | {t.receiver for t in lifecycle if t.receiver}
        if rec and rec.current_owner:
            entities.add(rec.current_owner)
        d["related_entities"] = sorted(entities)

    d["generation"] = None
    if alert.generation_id:
        gen = db.query(models.GenerationRecord).filter_by(generation_id=alert.generation_id).first()
        d["generation"] = {c.name: getattr(gen, c.name) for c in gen.__table__.columns} if gen else None

    d["transaction"] = None
    if alert.transaction_id:
        tx = db.query(models.RECTransaction).filter_by(transaction_id=alert.transaction_id).first()
        d["transaction"] = _tx_dict(tx) if tx else None

    return d


# ---------------------------------------------------------------- graph / fraud clusters

@router.get("/fraud-clusters")
def fraud_clusters(db: Session = Depends(get_db)):
    engine = get_graph_engine()
    engine.build(db)
    clusters = engine.suspicious_clusters()
    engine.sync_clusters_to_db(db, clusters)
    engine.sync_entities_to_db(db)
    return clusters


@router.get("/network-graph")
def network_graph(db: Session = Depends(get_db)):
    engine = get_graph_engine()
    engine.build(db)
    return engine.as_visjs()


# ---------------------------------------------------------------- blockchain

@router.get("/blockchain/status")
def blockchain_status():
    return get_chain().status()


@router.get("/verify/{rec_id}")
def verify_rec(rec_id: str, db: Session = Depends(get_db)):
    rec = db.query(models.RECRecord).filter_by(rec_id=rec_id).first()
    if not rec:
        raise HTTPException(404, "REC not found")
    onchain = get_chain().verify_rec(rec_id)
    hash_check = pipeline.verify_generation_hash(db, rec.generation_id) if rec.generation_id else None
    lifecycle = [_tx_dict(t) for t in db.query(models.RECTransaction).filter_by(rec_id=rec_id)
                 .order_by(models.RECTransaction.transaction_timestamp).all()]
    return {"rec": _rec_dict(rec), "onchain": onchain, "hash_verification": hash_check, "lifecycle": lifecycle}


# ---------------------------------------------------------------- REC Verification Portal
#
# Distinct from the QR-code deep-link `/verify/{rec_id}` route above (which
# just shows a basic hash/lifecycle check for the Blockchain Verify page):
# this is the full tamper-detection flow -- GET is a read-only lookup with
# no side effects, POST .../verify is the audited event that writes an
# append-only rec_verification_requests row (every attempt, including
# NOT_FOUND) and, when tampering is confirmed, a real FraudAlert + audit-log
# entry. See verification_service.py for the actual checks.

@router.get("/rec/{rec_id}")
def get_rec(rec_id: str, db: Session = Depends(get_db)):
    _validate_rec_id(rec_id)
    detail = verification_service.get_rec_detail(db, rec_id)
    if detail is None:
        raise HTTPException(404, "REC not found")
    return detail


@router.post("/rec/{rec_id}/verify")
def verify_rec_portal(rec_id: str, payload: schemas.VerifyRecRequest | None = Body(default=None),
                       db: Session = Depends(get_db)):
    _validate_rec_id(rec_id)
    company = payload.verifier_company if payload else None
    user = payload.verifier_user if payload else None
    result = verification_service.verify_rec(db, rec_id, verifier_company=company, verifier_user=user)

    websocket_service.broadcast_sync({
        "type": "rec_verified",
        "rec_id": rec_id,
        "verification_id": result["verification_id"],
        "result": result["result"],
        "blockchain_status": result["blockchain_status"],
        "hash_status": result["hash_status"],
    })
    if result["result"] == "TAMPERED":
        websocket_service.broadcast_sync({
            "type": "tamper_detected",
            "rec_id": rec_id,
            "verification_id": result["verification_id"],
            "result": "TAMPERED",
            "severity": "CRITICAL",
            "reason": result["reasons"][0] if result["reasons"] else "Data integrity check failed",
        })
    return result


@router.get("/rec/{rec_id}/history")
def rec_history(rec_id: str, db: Session = Depends(get_db)):
    _validate_rec_id(rec_id)
    rows = db.query(models.RECAuditLog).filter_by(rec_id=rec_id).order_by(models.RECAuditLog.changed_at).all()
    return [
        {
            "id": r.id, "rec_id": r.rec_id, "event_type": r.event_type,
            "old_value": json.loads(r.old_value) if r.old_value else None,
            "new_value": json.loads(r.new_value) if r.new_value else None,
            "changed_by": r.changed_by, "changed_at": r.changed_at, "source": r.source,
            "record_hash": r.record_hash, "previous_record_hash": r.previous_record_hash,
        }
        for r in rows
    ]


@router.get("/rec/{rec_id}/verification-history")
def rec_verification_history(rec_id: str, db: Session = Depends(get_db)):
    _validate_rec_id(rec_id)
    rows = db.query(models.RECVerificationRequest).filter_by(rec_id=rec_id) \
        .order_by(models.RECVerificationRequest.requested_at.desc()).all()
    return [_verification_dict(r) for r in rows]


@router.get("/verification/history")
def verification_history(
    rec_id: str | None = None, company: str | None = None, result: str | None = None,
    blockchain_status: str | None = None, since: float | None = None, until: float | None = None,
    limit: int = 200, db: Session = Depends(get_db),
):
    """Global listing (Verification History page) -- filterable, unlike the
    per-REC .../verification-history above."""
    q = db.query(models.RECVerificationRequest)
    if rec_id:
        q = q.filter(models.RECVerificationRequest.rec_id == rec_id)
    if company:
        q = q.filter(models.RECVerificationRequest.verifier_company.ilike(f"%{company}%"))
    if result:
        q = q.filter(models.RECVerificationRequest.result == result.upper())
    if blockchain_status:
        q = q.filter(models.RECVerificationRequest.blockchain_status == blockchain_status.upper())
    if since is not None:
        q = q.filter(models.RECVerificationRequest.requested_at >= since)
    if until is not None:
        q = q.filter(models.RECVerificationRequest.requested_at <= until)
    rows = q.order_by(models.RECVerificationRequest.requested_at.desc()).limit(min(limit, 1000)).all()
    return [_verification_dict(r) for r in rows]


@router.get("/verification/{verification_id}")
def get_verification(verification_id: str, db: Session = Depends(get_db)):
    row = db.query(models.RECVerificationRequest).filter_by(verification_id=verification_id).first()
    if not row:
        raise HTTPException(404, "verification not found")
    return _verification_dict(row, include_detail=True)


@router.post("/verification/report")
def verification_report(payload: schemas.VerificationReportRequest, db: Session = Depends(get_db)):
    """Generates the "Share Verification Report" download. Takes only a
    verification_id -- the result itself is never accepted from the client,
    only re-served from what was actually decided and stored at
    verification time (result_detail), so it can't be edited into showing
    something that didn't happen."""
    row = db.query(models.RECVerificationRequest).filter_by(verification_id=payload.verification_id).first()
    if not row:
        raise HTTPException(404, "verification not found")
    detail = json.loads(row.result_detail) if row.result_detail else {}
    return {
        "verification_id": row.verification_id,
        "rec_id": row.rec_id,
        "generated_at": time.time(),
        "verifier_company": row.verifier_company,
        "verifier_user": row.verifier_user,
        "verification_timestamp": row.requested_at,
        "result": row.result,
        "blockchain_status": row.blockchain_status,
        "hash_status": row.hash_status,
        "lifecycle_status": row.lifecycle_status,
        "risk_score": row.risk_score,
        "reasons": json.loads(row.reason or "[]"),
        "detail": detail,
    }


def _verification_dict(r: models.RECVerificationRequest, include_detail: bool = False) -> dict:
    d = {
        "verification_id": r.verification_id, "rec_id": r.rec_id,
        "verifier_company": r.verifier_company, "verifier_user": r.verifier_user,
        "requested_at": r.requested_at, "result": r.result, "reasons": json.loads(r.reason or "[]"),
        "blockchain_status": r.blockchain_status, "hash_status": r.hash_status, "lifecycle_status": r.lifecycle_status,
        "risk_score": r.risk_score,
    }
    if include_detail and r.result_detail:
        d["detail"] = json.loads(r.result_detail)
    return d


# ---------------------------------------------------------------- simulation control

@router.post("/simulation/start")
def simulation_start(payload: schemas.SimulationConfig | None = Body(default=None)):
    """Starting always applies whatever config is passed *first*, so the
    fraud-probability/interval currently selected in the UI takes effect
    immediately on this run -- no separate "apply" step required, and no
    backend/frontend restart needed."""
    sim = get_simulator()
    if payload is not None:
        sim.start(payload.interval_seconds, payload.fraud_probability, payload.tamper_enabled, payload.tamper_probability)
    else:
        sim.start()
    return sim.status()


@router.post("/simulation/stop")
def simulation_stop():
    get_simulator().stop()
    return get_simulator().status()


@router.post("/simulation/config")
def simulation_config(payload: schemas.SimulationConfig):
    """Updates the live config. Since `Simulator.tick()` reads
    `self.fraud_probability`/`self.interval` fresh on every tick, this takes
    effect on the very next tick of an already-running simulation, with no
    restart required."""
    get_simulator().configure(payload.interval_seconds, payload.fraud_probability,
                               payload.tamper_enabled, payload.tamper_probability)
    return get_simulator().status()


@router.get("/simulation/status")
def simulation_status():
    return get_simulator().status()


@router.post("/simulation/reset")
def simulation_reset(db: Session = Depends(get_db)):
    """Reset Transactions: stops the simulator, clears every
    simulator-generated table (RECs, generation records, transactions,
    fraud alerts, graph entities/edges, fraud clusters), resets the
    in-memory graph and simulator counters, and starts a new
    simulation_run_id -- see Simulator.reset_all's docstring for exactly
    what is and isn't touched. Broadcasts a `simulation_reset` WebSocket
    event so every connected dashboard clears its live view immediately,
    without a page refresh."""
    sim = get_simulator()
    counts = sim.reset_all(db)
    status = sim.status()

    payload = {
        "type": "simulation_reset",
        "message": "All simulation transactions cleared",
        "transaction_count": 0,
        "fraud_alert_count": 0,
        "graph_node_count": 0,
        "graph_edge_count": 0,
        "simulation_run_id": status["simulation_run_id"],
    }
    websocket_service.broadcast_sync(payload)

    return {
        "success": True,
        "message": "Simulation data reset successfully",
        "transaction_count": 0,
        "cleared": counts,
        "simulation_run_id": status["simulation_run_id"],
        "simulation": status,
    }


# ---------------------------------------------------------------- manual pipeline entry points

@router.post("/generation")
def submit_generation(payload: schemas.GenerationSubmit, db: Session = Depends(get_db)):
    result = pipeline.process_generation_event(
        db, payload.generator_id, payload.energy_generated_mwh, payload.weather_factor,
        rec_quantity=payload.rec_quantity, reuse_generation_id=payload.reuse_generation_id,
    )
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/transactions/transfer")
def submit_transfer(payload: schemas.TransferRequest, db: Session = Depends(get_db)):
    result = pipeline.process_transfer(db, payload.rec_id, payload.sender, payload.receiver, payload.quantity)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result
