"""
Broadcasts pipeline results to connected dashboard clients.

The simulator runs on a plain background thread (not asyncio), so
broadcast_sync() schedules the actual async send onto FastAPI's event loop
via asyncio.run_coroutine_threadsafe. set_event_loop() is called once from
app.py's startup handler.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger("websocket_service")

_connections: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


async def connect(ws: WebSocket) -> None:
    await ws.accept()
    _connections.add(ws)
    logger.info("client connected (%d total)", len(_connections))


def disconnect(ws: WebSocket) -> None:
    _connections.discard(ws)
    logger.info("client disconnected (%d total)", len(_connections))


async def _broadcast(message: dict) -> None:
    payload = json.dumps(message, default=str)
    dead = []
    for ws in list(_connections):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections.discard(ws)


def broadcast_sync(message: dict) -> None:
    """Callable safely from the simulator's background thread."""
    if _loop is None or not _connections:
        return
    try:
        asyncio.run_coroutine_threadsafe(_broadcast(message), _loop)
    except Exception:
        logger.exception("failed to schedule broadcast")
