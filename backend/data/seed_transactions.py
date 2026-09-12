"""Runs a handful of pipeline ticks at startup so the dashboard has data
immediately instead of a blank screen while the simulator warms up."""
from __future__ import annotations

import logging

import models
import simulator

logger = logging.getLogger("seed_transactions")


def seed(db) -> None:
    if db.query(models.RECTransaction).count() > 0:
        return
    sim = simulator.get_simulator()
    for _ in range(6):
        try:
            sim.tick()
        except Exception:
            logger.exception("seed tick failed")
    sim.ticks = 0  # don't count warm-up ticks toward the displayed simulation stats
