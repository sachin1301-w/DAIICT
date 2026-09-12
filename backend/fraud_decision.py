"""
Fraud Decision Engine: combines rule_score, ml_score, graph_score and a
blockchain-integrity gate into one decision + explainable reasons.

Blockchain integrity is a gate/check (did the on-chain hash match what's in
SQLite right now), never proof of legitimacy on its own -- a transaction can
pass integrity and still be fraud (over-issuance, circular trading, etc).

IMPORTANT (see section 20 of the spec): this function only ever produces a
decision + alert. It never calls revokeREC()/freezeREC() itself -- only an
explicit regulator action does that. ML/graph/rule signals create alerts or
hold transactions; they do not unilaterally revoke anything.
"""
from __future__ import annotations

import config


def combine(rule_score: float, ml_score: float, graph_score: float,
            blockchain_integrity_ok: bool, rule_violations: list[str],
            ml_reasons: list[str], graph_patterns: list[str]) -> dict:
    combined_score = (
        config.RULE_SCORE_WEIGHT * rule_score
        + config.ML_SCORE_WEIGHT * ml_score
        + config.GRAPH_SCORE_WEIGHT * graph_score
    )
    combined_score = round(min(combined_score, 100), 2)

    if not blockchain_integrity_ok:
        decision = "CRITICAL"
    elif rule_score >= config.DECISION_RULE_SCORE_FRAUD_THRESHOLD:
        decision = "FRAUD_SUSPECTED"
    elif graph_score >= config.DECISION_GRAPH_SCORE_FRAUD_THRESHOLD:
        decision = "FRAUD_SUSPECTED"
    elif ml_score >= config.DECISION_ML_SCORE_SUSPICIOUS_THRESHOLD:
        decision = "SUSPICIOUS"
    else:
        decision = "LEGITIMATE"

    risk_level = "LOW"
    for level, (lo, hi) in config.RISK_LEVEL_THRESHOLDS.items():
        if lo <= combined_score <= hi:
            risk_level = level
            break

    reasons = []
    if not blockchain_integrity_ok:
        reasons.append("blockchain integrity check FAILED -- on-chain hash does not match current off-chain data")
    reasons += [f"rule violation: {v}" for v in rule_violations]
    reasons += ml_reasons
    reasons += [f"graph pattern: {p}" for p in graph_patterns]
    if not reasons:
        reasons.append("no rule, ML or graph signals triggered")

    return {
        "final_risk_score": combined_score,
        "risk_level": risk_level,
        "decision": decision,
        "rule_score": rule_score,
        "ml_score": ml_score,
        "graph_score": graph_score,
        "reasons": reasons,
    }
