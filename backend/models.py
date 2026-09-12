from __future__ import annotations

import time
import uuid

from sqlalchemy import (
    Boolean, Column, Float, ForeignKey, Integer, String, Text,
)

from database import Base


def _uuid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class Generator(Base):
    __tablename__ = "generators"

    id = Column(Integer, primary_key=True, autoincrement=True)
    generator_id = Column(String(40), unique=True, index=True, default=lambda: _uuid("GEN"))
    name = Column(String(120), nullable=False)
    plant_type = Column(String(20), nullable=False)  # Solar | Wind | Hydro
    state = Column(String(60), nullable=False)
    capacity_mw = Column(Float, nullable=False)
    registration_status = Column(String(20), default="ACTIVE")
    wallet_address = Column(String(64), nullable=True)
    created_at = Column(Float, default=time.time)


class GenerationRecord(Base):
    __tablename__ = "generation_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    generation_id = Column(String(40), unique=True, index=True, default=lambda: _uuid("GENEV"))
    generator_id = Column(String(40), ForeignKey("generators.generator_id"), index=True)
    generation_timestamp = Column(Float, default=time.time)
    energy_generated_mwh = Column(Float, nullable=False)
    weather_factor = Column(Float, default=1.0)
    meter_data_hash = Column(String(66), nullable=True)
    is_synthetic = Column(Boolean, default=True)
    created_at = Column(Float, default=time.time)


class RECRecord(Base):
    __tablename__ = "rec_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rec_id = Column(String(40), unique=True, index=True, default=lambda: _uuid("REC"))
    generation_id = Column(String(40), ForeignKey("generation_records.generation_id"), index=True)
    generator_id = Column(String(40), ForeignKey("generators.generator_id"), index=True)
    quantity = Column(Float, nullable=False)
    issue_timestamp = Column(Float, default=time.time)
    status = Column(String(20), default="ACTIVE")  # ACTIVE | RETIRED | REVOKED | HELD
    current_owner = Column(String(64), nullable=True)
    blockchain_tx_hash = Column(String(80), nullable=True)
    generation_hash = Column(String(66), nullable=True)
    created_at = Column(Float, default=time.time)


class RECTransaction(Base):
    __tablename__ = "rec_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(String(40), unique=True, index=True, default=lambda: _uuid("TXN"))
    rec_id = Column(String(40), ForeignKey("rec_records.rec_id"), index=True)
    sender = Column(String(64), nullable=True)
    receiver = Column(String(64), nullable=True)
    transaction_type = Column(String(20), nullable=False)  # ISSUE | TRANSFER | RETIRE | REVOKE
    quantity = Column(Float, nullable=False)
    transaction_timestamp = Column(Float, default=time.time)
    blockchain_tx_hash = Column(String(80), nullable=True)
    created_at = Column(Float, default=time.time)


class FraudAlert(Base):
    __tablename__ = "fraud_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(String(40), unique=True, index=True, default=lambda: _uuid("ALERT"))
    rec_id = Column(String(40), nullable=True, index=True)
    generation_id = Column(String(40), nullable=True, index=True)
    transaction_id = Column(String(40), nullable=True, index=True)
    rule_score = Column(Float, default=0)
    ml_score = Column(Float, default=0)
    graph_score = Column(Float, default=0)
    final_risk_score = Column(Float, default=0)
    risk_level = Column(String(20), default="LOW")  # LOW | MEDIUM | HIGH | CRITICAL
    fraud_type = Column(String(60), nullable=True)
    reasons = Column(Text, default="[]")  # JSON-encoded list[str]
    status = Column(String(20), default="OPEN")  # OPEN | REVIEWING | RESOLVED | DISMISSED
    created_at = Column(Float, default=time.time)


class GraphEntity(Base):
    __tablename__ = "graph_entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id = Column(String(64), unique=True, index=True)
    entity_type = Column(String(20), nullable=False)  # GENERATOR | BROKER | TRADER | COMPANY
    entity_name = Column(String(120), nullable=True)
    risk_score = Column(Float, default=0)
    degree = Column(Integer, default=0)
    betweenness = Column(Float, default=0)
    created_at = Column(Float, default=time.time)


class GraphEdge(Base):
    __tablename__ = "graph_edges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_entity = Column(String(64), index=True)
    target_entity = Column(String(64), index=True)
    relationship_type = Column(String(20), nullable=False)  # ISSUED | OWNED | TRANSFERRED | RETIRED
    rec_id = Column(String(40), nullable=True)
    quantity = Column(Float, default=0)
    transaction_timestamp = Column(Float, default=time.time)


class FraudCluster(Base):
    __tablename__ = "fraud_clusters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cluster_id = Column(String(40), unique=True, index=True, default=lambda: _uuid("FRAUD"))
    entity_count = Column(Integer, default=0)
    rec_count = Column(Integer, default=0)
    transfer_count = Column(Integer, default=0)
    graph_score = Column(Float, default=0)
    risk_score = Column(Float, default=0)
    fraud_pattern = Column(Text, default="[]")  # JSON-encoded list[str]
    status = Column(String(20), default="ACTIVE")
    created_at = Column(Float, default=time.time)
