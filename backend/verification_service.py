"""
REC Verification Portal: independent, cryptographic + on-chain tamper
detection for a single REC, on top of the existing rule/ML/graph fraud
pipeline (pipeline.py / fraud_decision.py) -- that pipeline scores a
transaction *as it happens*; this module answers a different question
asked *after the fact*, by anyone (an internal operator, another company, an
auditor): "is this specific REC's data still exactly what was anchored at
issuance, right now?"

Core idea (spec section 6):

    SQLite current values --SHA-256--> current hash
    current hash  vs  rec.generation_hash (the immutable hash stored once,
                       at issuance, in the LEGITIMATE branch of
                       pipeline.process_generation_event -- never
                       overwritten afterwards)
    rec.generation_hash  vs  the hash actually anchored on-chain

Three-way agreement is what "VALID" means. A blockchain that's merely
offline is never treated as agreement -- see verify_rec()'s NOT_CONNECTED
handling and the module docstring in blockchain_service.py.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time

from sqlalchemy.orm import Session

import models
from blockchain_service import get_service as get_chain

logger = logging.getLogger("verification_service")

# Same heuristic ceiling rules_engine.check_capacity_violation uses, reused
# here for the standalone physical-plausibility check (spec Rule 7).
MAX_CAPACITY_FACTOR_HOURS = 6
OVER_ISSUANCE_TOLERANCE = 1.2

RESULT_VALUES = {"VALID", "SUSPICIOUS", "INVALID", "TAMPERED", "NOT_FOUND", "PENDING", "UNCONFIRMED"}


# ==================================================================== canonical hash

def canonical_rec_payload(rec: models.RECRecord, generation: models.GenerationRecord | None,
                           generator: models.Generator | None) -> dict:
    """The exact 7-field canonical payload from the spec. Computed the same
    way at issuance (pipeline.py) and at every later verification -- a
    single shared definition so the two can never silently drift apart."""
    return {
        "rec_id": rec.rec_id,
        "generator_id": rec.generator_id,
        "plant_capacity_mw": generator.capacity_mw if generator else None,
        "energy_generated_mwh": generation.energy_generated_mwh if generation else None,
        "rec_quantity": rec.quantity,
        "generation_timestamp": generation.generation_timestamp if generation else None,
        "issuance_timestamp": rec.issue_timestamp,
    }


def canonical_rec_hash(rec: models.RECRecord, generation: models.GenerationRecord | None,
                        generator: models.Generator | None) -> str:
    blob = json.dumps(canonical_rec_payload(rec, generation, generator), sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


# ==================================================================== audit log

def audit_log(db: Session, rec_id: str, event_type: str, old_value=None, new_value=None,
              changed_by: str = "system", source: str = "pipeline") -> models.RECAuditLog:
    """Appends one hash-chained row. Each row's record_hash covers its own
    content plus the immediately preceding row's hash for this rec_id, so
    the chain (not just any single row) has to be internally consistent --
    a cheap tamper-evidence property without a real blockchain write per
    event. Caller commits; this only adds+flushes."""
    last = (
        db.query(models.RECAuditLog)
        .filter_by(rec_id=rec_id)
        .order_by(models.RECAuditLog.id.desc())
        .first()
    )
    previous_hash = last.record_hash if last else None
    changed_at = time.time()
    payload = {
        "rec_id": rec_id, "event_type": event_type,
        "old_value": old_value, "new_value": new_value,
        "changed_by": changed_by, "changed_at": changed_at,
        "previous_record_hash": previous_hash,
    }
    record_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    row = models.RECAuditLog(
        rec_id=rec_id, event_type=event_type,
        old_value=json.dumps(old_value, default=str) if old_value is not None else None,
        new_value=json.dumps(new_value, default=str) if new_value is not None else None,
        changed_by=changed_by, changed_at=changed_at, source=source,
        record_hash=record_hash, previous_record_hash=previous_hash,
    )
    db.add(row)
    db.flush()
    return row


# ==================================================================== checks

def _resolve_address(chain, owner: str) -> str:
    if owner and owner.startswith("0x") and len(owner) == 42:
        return owner
    wallet = chain.wallets.get(owner)
    if wallet:
        return wallet["address"]
    digest = hashlib.sha256((owner or "unknown").encode()).hexdigest()[:40]
    return "0x" + digest


def _check_blockchain(chain, rec: models.RECRecord, compare_hash: str | None) -> tuple[str, str, dict | None]:
    """Returns (blockchain_status, message, onchain_dict_or_None).

    NOT_CONNECTED is decided purely from chain connectivity, checked BEFORE
    calling verify_rec -- never inferred after the fact from "verify_rec
    returned None", since that also happens for a REC that's legitimately
    never been minted (held for review). Conflating those two would let an
    offline node accidentally read as "this REC doesn't exist" (FAILED)
    instead of the honest "we can't tell" (NOT_CONNECTED).

    `compare_hash` is the CURRENT recomputed hash, not the stored original --
    deliberately, so that "someone edited SQLite directly" (spec Test 2)
    reads as a blockchain verification FAILURE too, exactly like the spec's
    section 6 diagram (current local hash -> original -> blockchain hash,
    all three must agree), not just a data-integrity mismatch that happens
    to leave the on-chain comparison looking fine."""
    if not chain.is_online:
        return "NOT_CONNECTED", "Local blockchain node unavailable", None

    onchain = chain.verify_rec(rec.rec_id)
    if onchain is None:
        if rec.status == "HELD":
            return "PENDING", "REC is held for fraud review and was never anchored on-chain", None
        return "FAILED", "REC not found on-chain despite being marked issued locally -- possible tamper or lost chain state", None

    if not compare_hash:
        return "PENDING", "No hash available locally to compare against on-chain data", onchain

    onchain_hash = onchain["generation_data_hash"]
    match = onchain_hash == compare_hash or onchain_hash.lstrip("0") == compare_hash.lstrip("0")
    if match:
        return "PASSED", "On-chain hash matches the current local data", onchain
    return "FAILED", "On-chain hash does not match the current local data", onchain


def _check_data_integrity(rec: models.RECRecord, generation: models.GenerationRecord | None,
                           generator: models.Generator | None) -> tuple[str, str, str | None]:
    """Returns (hash_status, message, recomputed_hash)."""
    if not rec.generation_hash:
        return "UNKNOWN", "No original hash on file for this REC", None
    recomputed = canonical_rec_hash(rec, generation, generator)
    if recomputed == rec.generation_hash:
        return "MATCHED", "Recalculated hash matches the hash stored at issuance", recomputed
    return "MISMATCHED", "Recalculated hash differs from the hash stored at issuance -- one or more fields were edited after issuance", recomputed


def _field_level_reasons(rec: models.RECRecord, generation: models.GenerationRecord | None,
                          generator: models.Generator | None, onchain: dict | None,
                          hash_status: str) -> list[dict]:
    """Attributes WHICH field looks tampered, where possible. Cross-checks
    against on-chain data (quantity/owner/generator_id/status are all
    stored on-chain -- see RECRegistry.sol's REC struct) for rules 2/3/5/6;
    falls back to "the hash says something changed, but the only canonical
    fields the chain doesn't also store are energy/capacity/timestamps" for
    rule 1, since energy_generated_mwh is deliberately NOT part of the
    on-chain struct (only quantity is)."""
    reasons: list[dict] = []

    if onchain:
        onchain_qty = onchain["quantity"]
        if abs(onchain_qty - rec.quantity) > 1e-6:
            reasons.append({
                "type": "REC_QUANTITY_TAMPERED",
                "message": f"Database REC quantity ({rec.quantity}) does not match the on-chain quantity ({onchain_qty}).",
            })
        chain = get_chain()
        expected_owner = _resolve_address(chain, rec.current_owner).lower()
        if onchain["current_owner"].lower() != expected_owner:
            reasons.append({
                "type": "OWNERSHIP_TAMPERED",
                "message": "Current owner in the database does not match the on-chain owner.",
            })
        if onchain["generator_id"] != rec.generator_id:
            reasons.append({
                "type": "GENERATOR_DATA_TAMPERED",
                "message": "Generator ID in the database does not match the on-chain record.",
            })
        onchain_status = onchain["status"]
        db_active_like = rec.status in ("ACTIVE", "HELD")
        onchain_active_like = onchain_status == "ACTIVE"
        if db_active_like != onchain_active_like and not (rec.status == "HELD" and onchain_status == "ACTIVE"):
            reasons.append({
                "type": "LIFECYCLE_TAMPERED",
                "message": f"Database status ({rec.status}) is inconsistent with the on-chain status ({onchain_status}).",
            })

    if hash_status == "MISMATCHED" and not any(r["type"] in ("REC_QUANTITY_TAMPERED", "GENERATOR_DATA_TAMPERED") for r in reasons):
        reasons.insert(0, {
            "type": "DATA_TAMPERED",
            "message": "Energy generated, plant capacity or timestamp values differ from what was anchored at issuance (hash mismatch).",
        })

    if generation is not None and generator is not None:
        if generation.energy_generated_mwh < 0 or rec.quantity < 0:
            reasons.append({"type": "PHYSICAL_VALIDATION_FAILED", "message": "Negative energy generated or REC quantity."})
        if rec.quantity > generation.energy_generated_mwh * OVER_ISSUANCE_TOLERANCE:
            reasons.append({
                "type": "PHYSICAL_VALIDATION_FAILED",
                "message": f"REC quantity ({rec.quantity}) exceeds generated energy ({generation.energy_generated_mwh} MWh) by more than {int((OVER_ISSUANCE_TOLERANCE - 1) * 100)}%.",
            })
        ceiling = generator.capacity_mw * MAX_CAPACITY_FACTOR_HOURS
        if generation.energy_generated_mwh > ceiling:
            reasons.append({
                "type": "PHYSICAL_VALIDATION_FAILED",
                "message": f"Energy generated ({generation.energy_generated_mwh} MWh) exceeds physically plausible output ({ceiling:.1f} MWh) for a {generator.capacity_mw:.0f} MW plant.",
            })
        if rec.issue_timestamp < generation.generation_timestamp - 1:
            reasons.append({"type": "TIMESTAMP_TAMPERED", "message": "REC issuance timestamp predates its generation event."})

    return reasons


def _decide_result(rec_found: bool, generation_ok: bool, hash_status: str, blockchain_status: str,
                    reasons: list[dict]) -> str:
    if not rec_found:
        return "NOT_FOUND"
    if not generation_ok:
        return "INVALID"

    reason_types = {r["type"] for r in reasons}
    critical = (
        hash_status == "MISMATCHED"
        or blockchain_status == "FAILED"
        or "LIFECYCLE_TAMPERED" in reason_types
        or "OWNERSHIP_TAMPERED" in reason_types
    )
    if critical:
        return "TAMPERED"
    if blockchain_status == "NOT_CONNECTED":
        # Never VALID just because SQLite agrees with itself -- spec section 6 / Test 8.
        return "UNCONFIRMED"
    if reason_types:
        return "SUSPICIOUS"
    if blockchain_status == "PENDING":
        return "PENDING"
    return "VALID"


def _verification_risk_level(result: str, reason_types: set[str]) -> str | None:
    if result == "TAMPERED":
        return "CRITICAL"
    if result == "SUSPICIOUS" and reason_types:
        return "HIGH"
    return None


_ALERT_RISK_SCORE = {"CRITICAL": 95, "HIGH": 75}


# ==================================================================== main entry point

def verify_rec(db: Session, rec_id: str, verifier_company: str | None = None,
                verifier_user: str | None = None, source_ip: str | None = None) -> dict:
    """The full checked-and-logged verification flow (spec sections 4, 6, 8,
    9's POST /api/rec/{id}/verify, 10). Always writes one
    rec_verification_requests row, even for NOT_FOUND -- append-only, per
    spec section 16. When tampering is confirmed, also raises a real
    FraudAlert (fraud_type one of the new tamper types) so it shows up
    in the existing Fraud Alerts page/dashboard counts, and an audit-log
    HASH_MISMATCH/TAMPER_DETECTED entry -- genuinely wired into the
    existing fraud pipeline rather than a parallel system."""
    rec = db.query(models.RECRecord).filter_by(rec_id=rec_id).first()
    generation = None
    generator = None
    lifecycle: list[models.RECTransaction] = []
    latest_alert = None

    if rec is not None:
        generation = db.query(models.GenerationRecord).filter_by(generation_id=rec.generation_id).first()
        generator = db.query(models.Generator).filter_by(generator_id=rec.generator_id).first()
        lifecycle = (
            db.query(models.RECTransaction).filter_by(rec_id=rec_id)
            .order_by(models.RECTransaction.transaction_timestamp).all()
        )
        latest_alert = (
            db.query(models.FraudAlert).filter_by(rec_id=rec_id)
            .order_by(models.FraudAlert.created_at.desc()).first()
        )

    now = time.time()

    if rec is None:
        result = "NOT_FOUND"
        hash_status, blockchain_status, lifecycle_status = "UNKNOWN", "UNKNOWN", "UNKNOWN"
        reasons: list[dict] = [{"type": "NOT_FOUND", "message": f"No REC exists with id '{rec_id}'."}]
        recomputed_hash = None
        onchain = None
    else:
        chain = get_chain()
        hash_status, hash_message, recomputed_hash = _check_data_integrity(rec, generation, generator)
        compare_hash = recomputed_hash or rec.generation_hash
        blockchain_status, bc_message, onchain = _check_blockchain(chain, rec, compare_hash)
        reasons = _field_level_reasons(rec, generation, generator, onchain, hash_status)
        result = _decide_result(True, generation is not None and generator is not None, hash_status, blockchain_status, reasons)
        lifecycle_status = "INVALID" if any(r["type"] == "LIFECYCLE_TAMPERED" for r in reasons) else "VALID"
        if blockchain_status in ("FAILED", "NOT_CONNECTED"):
            reasons = [{"type": "BLOCKCHAIN", "message": bc_message}] + reasons

    reason_types = {r["type"] for r in reasons if r["type"] not in ("BLOCKCHAIN",)}
    risk_level = _verification_risk_level(result, reason_types)

    ml_risk = latest_alert.ml_score if latest_alert else 0.0
    graph_risk = latest_alert.graph_score if latest_alert else 0.0
    final_risk = latest_alert.final_risk_score if latest_alert else (
        _ALERT_RISK_SCORE.get(risk_level, 0) if risk_level else 0.0
    )

    response = {
        "rec_id": rec_id,
        "result": result,
        "blockchain_status": blockchain_status,
        "hash_status": hash_status,
        "lifecycle_status": lifecycle_status,
        "ml_risk_score": ml_risk,
        "graph_risk_score": graph_risk,
        "final_risk_score": final_risk,
        "reasons": [r["message"] for r in reasons],
        "reason_types": sorted(reason_types),
        "verified_at": now,
        "original_hash": rec.generation_hash if rec else None,
        "recomputed_hash": recomputed_hash,
        "onchain_hash": onchain["generation_data_hash"] if onchain else None,
        "rec": _rec_detail(rec, generation, generator, lifecycle) if rec else None,
    }

    # -------- persist the verification request (append-only, always) --------
    verification = models.RECVerificationRequest(
        rec_id=rec_id, verifier_company=verifier_company, verifier_user=verifier_user,
        requested_at=now, result=result, reason=json.dumps(response["reasons"]),
        blockchain_status=blockchain_status, hash_status=hash_status, lifecycle_status=lifecycle_status,
        verified_blockchain=blockchain_status in ("PASSED", "FAILED"),
        verified_hash=hash_status in ("MATCHED", "MISMATCHED"),
        verified_lifecycle=lifecycle_status == "VALID",
        risk_score=final_risk, source_ip=source_ip,
    )
    db.add(verification)
    db.flush()
    response["verification_id"] = verification.verification_id
    response["verifier_company"] = verifier_company
    response["verifier_user"] = verifier_user
    # Captured verbatim so /api/verification/report always re-serves exactly
    # what was decided here -- never recomputed from (possibly by-then-
    # different) live data, never accepting a client-supplied result.
    verification.result_detail = json.dumps(response, default=str)

    if rec is not None:
        audit_log(
            db, rec_id, "REC_VERIFIED",
            new_value={"result": result, "verifier_company": verifier_company, "verifier_user": verifier_user},
            changed_by=verifier_user or verifier_company or "anonymous verifier", source="verification_portal",
        )
        if result == "TAMPERED":
            event_type = "HASH_MISMATCH" if hash_status == "MISMATCHED" else "TAMPER_DETECTED"
            audit_log(
                db, rec_id, event_type,
                old_value={"expected_hash": rec.generation_hash},
                new_value={"recomputed_hash": recomputed_hash, "reasons": response["reasons"]},
                changed_by="verification_service", source="verification_portal",
            )
            fraud_type = (sorted(reason_types)[0].lower() if reason_types else "blockchain_hash_mismatch")
            alert = models.FraudAlert(
                rec_id=rec_id, final_risk_score=_ALERT_RISK_SCORE["CRITICAL"], risk_level="CRITICAL",
                fraud_type=fraud_type, reasons=json.dumps(response["reasons"]), status="OPEN",
            )
            db.add(alert)
        elif risk_level == "HIGH":
            fraud_type = sorted(reason_types)[0].lower() if reason_types else "data_tampering"
            alert = models.FraudAlert(
                rec_id=rec_id, final_risk_score=_ALERT_RISK_SCORE["HIGH"], risk_level="HIGH",
                fraud_type=fraud_type, reasons=json.dumps(response["reasons"]), status="OPEN",
            )
            db.add(alert)

    db.commit()
    return response


def _rec_detail(rec: models.RECRecord, generation: models.GenerationRecord | None,
                 generator: models.Generator | None, lifecycle: list[models.RECTransaction]) -> dict:
    original_owner = lifecycle[0].receiver if lifecycle and lifecycle[0].transaction_type == "ISSUE" else rec.current_owner
    return {
        "rec_id": rec.rec_id,
        "generator_id": rec.generator_id,
        "plant_name": generator.name if generator else None,
        "plant_location": generator.state if generator else None,
        "energy_source": generator.plant_type if generator else None,
        "plant_capacity_mw": generator.capacity_mw if generator else None,
        "energy_generated_mwh": generation.energy_generated_mwh if generation else None,
        "rec_quantity": rec.quantity,
        "generation_timestamp": generation.generation_timestamp if generation else None,
        "issuance_timestamp": rec.issue_timestamp,
        "original_owner": original_owner,
        "current_owner": rec.current_owner,
        "status": rec.status,
        "retired": rec.status == "RETIRED",
        "blockchain_tx_hash": rec.blockchain_tx_hash,
        "generation_data_hash": rec.generation_hash,
        "lifecycle": [
            {
                "transaction_id": t.transaction_id, "transaction_type": t.transaction_type,
                "sender": t.sender, "receiver": t.receiver, "quantity": t.quantity,
                "transaction_timestamp": t.transaction_timestamp, "blockchain_tx_hash": t.blockchain_tx_hash,
                "blockchain_status": t.blockchain_status,
            }
            for t in lifecycle
        ],
    }


def get_rec_detail(db: Session, rec_id: str) -> dict | None:
    """Read-only lookup (GET /api/rec/{rec_id}) -- no side effects, no
    verification_requests row. Used to populate the Verify REC page before
    the user actually clicks Verify."""
    rec = db.query(models.RECRecord).filter_by(rec_id=rec_id).first()
    if rec is None:
        return None
    generation = db.query(models.GenerationRecord).filter_by(generation_id=rec.generation_id).first()
    generator = db.query(models.Generator).filter_by(generator_id=rec.generator_id).first()
    lifecycle = (
        db.query(models.RECTransaction).filter_by(rec_id=rec_id)
        .order_by(models.RECTransaction.transaction_timestamp).all()
    )
    return _rec_detail(rec, generation, generator, lifecycle)
