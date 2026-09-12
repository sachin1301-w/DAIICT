"""Seeds the generators table, linking two of them to real Hardhat GENERATOR_ROLE
wallets (so their issuances/transfers can actually settle on-chain) and a few
more as off-chain-only for variety."""
from __future__ import annotations

import json
import random
import time

import config
import models


def _wallet_address(label: str) -> str | None:
    path = config.CHAIN_DIR / "wallets.json"
    if not path.exists():
        return None
    wallets = {w["label"]: w for w in json.load(open(path))}
    entry = wallets.get(label)
    return entry["address"] if entry else None


GENERATORS = [
    dict(name="Plant A Solar Park", plant_type="Solar", state="Gujarat", capacity_mw=50,
         wallet_label="Generator: Plant A (Solar)"),
    dict(name="Sunrise Wind Farm", plant_type="Wind", state="Tamil Nadu", capacity_mw=80,
         wallet_label="Generator: Sunrise Wind Farm"),
    dict(name="Deccan Hydro Plant", plant_type="Hydro", state="Karnataka", capacity_mw=35, wallet_label=None),
    dict(name="Rann Solar Farm", plant_type="Solar", state="Rajasthan", capacity_mw=65, wallet_label=None),
    dict(name="Western Ghats Wind", plant_type="Wind", state="Maharashtra", capacity_mw=45, wallet_label=None),
]


def seed(db) -> None:
    if db.query(models.Generator).count() > 0:
        return
    for spec in GENERATORS:
        wallet_address = _wallet_address(spec["wallet_label"]) if spec["wallet_label"] else None
        # Backdated on purpose: these represent already-accredited plants, not
        # accounts created this second -- account_age_days is an ML feature,
        # and a value near 0 for every seeded generator would make every one
        # of their very first readings look anomalous by comparison to normal
        # training data.
        backdated_created_at = time.time() - random.uniform(90, 900) * 86400
        db.add(models.Generator(
            name=spec["name"], plant_type=spec["plant_type"], state=spec["state"],
            capacity_mw=spec["capacity_mw"], registration_status="ACTIVE", wallet_address=wallet_address,
            created_at=backdated_created_at,
        ))
    db.commit()
