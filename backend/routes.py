from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import pipeline
import schemas
from blockchain_service import get_service as get_chain
from database import get_db
from graph_service import get_engine as get_graph_engine
from simulator import get_simulator

router = APIRouter(prefix="/api")


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


# ---------------------------------------------------------------- simulation control

@router.post("/simulation/start")
def simulation_start():
    get_simulator().start()
    return get_simulator().status()


@router.post("/simulation/stop")
def simulation_stop():
    get_simulator().stop()
    return get_simulator().status()


@router.post("/simulation/config")
def simulation_config(payload: schemas.SimulationConfig):
    get_simulator().configure(payload.interval_seconds, payload.fraud_probability)
    return get_simulator().status()


@router.get("/simulation/status")
def simulation_status():
    return get_simulator().status()


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
