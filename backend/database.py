from __future__ import annotations

import logging
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

import config

logger = logging.getLogger("database")

connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def _sync_missing_columns() -> None:
    """Lightweight auto-migration for SQLite dev databases: `create_all`
    only creates tables that don't exist yet, it never ALTERs an existing
    table to add newly-defined columns. Without this, a `rec_fraud.db` file
    created by an older build of this project would be missing columns like
    `blockchain_status` and every query against them would raise. There's no
    migration framework in this hackathon prototype, so this just diffs each
    model's declared columns against what SQLite actually has and adds
    whatever's missing -- safe to run every startup, a no-op once caught up."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # brand-new table -- create_all already built it with every column
            existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                col_type = column.type.compile(engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))
                logger.info("migrated: added column %s.%s", table.name, column.name)


def init_db() -> None:
    import models  # noqa: F401  ensures models are registered on Base before create_all
    Base.metadata.create_all(bind=engine)
    _sync_missing_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
