"""MySQL connection management.

One SQLAlchemy ``Engine`` is created per logical schema
(``dw_metadata``, ``dw_bronze``, ``dw_silver``, ``dw_gold``). Engines are
lazy-initialized so importing this module is cheap and safe in
environments where MySQL is not yet reachable (CI, unit tests, etc.).

The metadata schema also exposes an ORM ``Base`` and a session factory.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings
from .logging import get_logger

_log = get_logger(__name__)


class Base(DeclarativeBase):
    """Declarative base for all ORM models in ``dw_metadata``."""


# ---- Engine cache (lazy) ----------------------------------------------------
_engines: dict[str, Engine] = {}


def _build_engine(database: str) -> Engine:
    url = settings.mysql_url(database)
    _log.debug("Creating SQLAlchemy engine for database=%s driver=%s", database, settings.mysql_driver)
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
        connect_args=settings.mysql_connect_args(),
    )


def get_engine(database: str) -> Engine:
    """Return (and cache) the engine for the given logical database name."""
    if database not in _engines:
        _engines[database] = _build_engine(database)
    return _engines[database]


# ---- Convenience accessors --------------------------------------------------
def metadata_engine() -> Engine:
    return get_engine(settings.db_metadata)


def bronze_engine() -> Engine:
    return get_engine(settings.db_bronze)


def silver_engine() -> Engine:
    return get_engine(settings.db_silver)


def gold_engine() -> Engine:
    return get_engine(settings.db_gold)


# ---- Session factory for the metadata DB -----------------------------------
_SessionLocal: sessionmaker[Session] | None = None


def _session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=metadata_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager that yields a transactional metadata-DB session."""
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_metadata_session() -> Iterator[Session]:
    """FastAPI dependency: yield a metadata-DB session per request."""
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()


# ---- Bootstrap helpers ------------------------------------------------------
def init_metadata_tables() -> None:
    """Create all ORM tables in the metadata schema.

    Importing :mod:`app.models` triggers SQLAlchemy registration, so all
    tables are present on ``Base.metadata`` by the time we call
    ``create_all``.
    """
    # Side-effect import: registers every model on ``Base``.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=metadata_engine())
    _log.info("Metadata tables ensured in schema %s", settings.db_metadata)
