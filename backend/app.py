"""
FastAPI entrypoint. Run with:  python app.py   (or: uvicorn app:app --reload)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

import config
import websocket_service
from data import seed_generators, seed_transactions
from database import SessionLocal, init_db
from routes import router
from simulator import get_simulator

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_generators.seed(db)
        seed_transactions.seed(db)
    finally:
        db.close()

    websocket_service.set_event_loop(asyncio.get_running_loop())

    if config.SIMULATION_AUTOSTART:
        get_simulator().start()

    logger.info("REC Fraud Detection backend ready on port %d", config.API_PORT)
    yield
    get_simulator().stop()


app = FastAPI(title="REC Fraud Detection API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_origin_regex=config.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await websocket_service.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep the connection open; client doesn't need to send anything
    except WebSocketDisconnect:
        websocket_service.disconnect(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=config.API_HOST, port=config.API_PORT, reload=False)
