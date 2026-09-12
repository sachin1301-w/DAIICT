"""
Deterministic, explainable rule checks -- independent from ML. Each check_*
function returns (violated: bool, reason: str | None). validate_generation()
and validate_transaction() compose them into a single rule_score (0-100) and
a violations list, matching the shape the fraud decision engine expects.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

import models

# capacity factor: assume a single generation reading represents at most a
# few hours of output, so more than 6x nameplate capacity in one reading is
# physically implausible for that window.
MAX_CAPACITY_FACTOR_HOURS = 6
OVER_ISSUANCE_TOLERANCE = 1.2  # allow REC quantity up to 20% above reported generation

VIOLATION_WEIGHTS = {
    # A blatant single violation (impossible capacity, REC quantity far above
    # generation, reusing a retired certificate, transferring a REC you don't
    # own) must clear the fraud_decision.py FRAUD_SUSPECTED threshold (80) on
    # its own -- these are unambiguous fraud, not a "mild" issue that should
    # only matter when stacked with something else.
    "generator_not_registered": 100,
    "capacity_violation": 85,
    "duplicate_generation": 80,
    "over_issuance": 85,
    "invalid_timestamp": 30,
    "retired_rec_reuse": 90,
    "duplicate_ownership": 40,
    "invalid_transfer_sequence": 95,
}


def check_generator_registered(db: Session, generator_id: str) -> tuple[bool, str | None]:
    gen = db.query(models.Generator).filter_by(generator_id=generator_id).first()
    if gen is None:
        return True, f"generator '{generator_id}' is not registered"
    if gen.registration_status != "ACTIVE":
        return True, f"generator '{generator_id}' registration status is {gen.registration_status}"
    return False, None


def check_capacity_violation(capacity_mw: float, energy_generated_mwh: float) -> tuple[bool, str | None]:
    ceiling = capacity_mw * MAX_CAPACITY_FACTOR_HOURS
    if energy_generated_mwh > ceiling:
        return True, (
            f"reported generation {energy_generated_mwh:.1f} MWh exceeds plausible ceiling "
            f"{ceiling:.1f} MWh for a {capacity_mw:.0f} MW plant"
        )
    return False, None


def check_duplicate_generation(db: Session, generation_id: str) -> tuple[bool, str | None]:
    count = db.query(models.RECRecord).filter_by(generation_id=generation_id).count()
    if count >= 1:
        return True, f"generation record '{generation_id}' has already been used to issue an REC"
    return False, None


def check_over_issuance(energy_generated_mwh: float, rec_quantity: float) -> tuple[bool, str | None]:
    if energy_generated_mwh <= 0:
        return True, "non-positive reported generation"
    if rec_quantity > energy_generated_mwh * OVER_ISSUANCE_TOLERANCE:
        return True, (
            f"REC quantity {rec_quantity:.1f} exceeds generated energy {energy_generated_mwh:.1f} MWh "
            f"by more than {int((OVER_ISSUANCE_TOLERANCE - 1) * 100)}%"
        )
    return False, None


def check_invalid_timestamp(generation_timestamp: float, issue_timestamp: float) -> tuple[bool, str | None]:
    if issue_timestamp < generation_timestamp:
        return True, "REC issuance timestamp is before the generation event it is based on"
    return False, None


def check_retired_rec_reuse(db: Session, rec_id: str) -> tuple[bool, str | None]:
    rec = db.query(models.RECRecord).filter_by(rec_id=rec_id).first()
    if rec and rec.status in ("RETIRED", "REVOKED"):
        return True, f"REC '{rec_id}' is {rec.status} and cannot be transferred or reused"
    return False, None


def check_duplicate_ownership(sender: str, receiver: str) -> tuple[bool, str | None]:
    if sender and receiver and sender.lower() == receiver.lower():
        return True, "sender and receiver are the same entity (self-dealing transfer)"
    return False, None


def check_invalid_transfer_sequence(db: Session, rec_id: str, sender: str) -> tuple[bool, str | None]:
    rec = db.query(models.RECRecord).filter_by(rec_id=rec_id).first()
    if rec and rec.current_owner and sender and rec.current_owner.lower() != sender.lower():
        return True, f"sender '{sender}' is not the current owner of '{rec_id}' ('{rec.current_owner}' is)"
    return False, None


def _score(violations: list[tuple[str, str]]) -> float:
    return min(100, sum(VIOLATION_WEIGHTS.get(code, 20) for code, _ in violations))


def validate_generation(db: Session, generator_id: str, capacity_mw: float, energy_generated_mwh: float,
                         rec_quantity: float, generation_id: str, generation_timestamp: float,
                         issue_timestamp: float) -> dict:
    violations: list[tuple[str, str]] = []

    violated, reason = check_generator_registered(db, generator_id)
    if violated:
        violations.append(("generator_not_registered", reason))

    violated, reason = check_capacity_violation(capacity_mw, energy_generated_mwh)
    if violated:
        violations.append(("capacity_violation", reason))

    violated, reason = check_duplicate_generation(db, generation_id)
    if violated:
        violations.append(("duplicate_generation", reason))

    violated, reason = check_over_issuance(energy_generated_mwh, rec_quantity)
    if violated:
        violations.append(("over_issuance", reason))

    violated, reason = check_invalid_timestamp(generation_timestamp, issue_timestamp)
    if violated:
        violations.append(("invalid_timestamp", reason))

    return {"rule_score": _score(violations), "violations": [r for _, r in violations]}


def validate_transaction(db: Session, rec_id: str, sender: str, receiver: str) -> dict:
    violations: list[tuple[str, str]] = []

    violated, reason = check_retired_rec_reuse(db, rec_id)
    if violated:
        violations.append(("retired_rec_reuse", reason))

    violated, reason = check_duplicate_ownership(sender, receiver)
    if violated:
        violations.append(("duplicate_ownership", reason))

    violated, reason = check_invalid_transfer_sequence(db, rec_id, sender)
    if violated:
        violations.append(("invalid_transfer_sequence", reason))

    return {"rule_score": _score(violations), "violations": [r for _, r in violations]}
