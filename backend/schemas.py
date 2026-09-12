from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class GeneratorCreate(BaseModel):
    name: str
    plant_type: str = Field(pattern="^(Solar|Wind|Hydro)$")
    state: str
    capacity_mw: float
    wallet_address: Optional[str] = None


class GenerationSubmit(BaseModel):
    generator_id: str
    energy_generated_mwh: float
    weather_factor: float = 1.0
    rec_quantity: Optional[float] = None  # defaults to energy_generated_mwh if omitted
    reuse_generation_id: Optional[str] = None  # for duplicate-generation simulation/testing


class TransferRequest(BaseModel):
    rec_id: str
    sender: str
    receiver: str
    quantity: float


class SimulationConfig(BaseModel):
    interval_seconds: Optional[float] = None
    fraud_probability: Optional[float] = None


class RevokeRequest(BaseModel):
    actor: str = "REGULATOR_MAIN"
    reason: Optional[str] = None
