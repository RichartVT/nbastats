"""Motor y sesiones de SQLAlchemy.

El engine se crea de forma perezosa para que importar el paquete no exija tener
Postgres levantado (los tests unitarios de `analysis/` no tocan la base).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from nbastats.config import get_settings


@lru_cache
def get_engine(echo: bool = False) -> Engine:
    return create_engine(
        get_settings().database_url,
        echo=echo,
        pool_pre_ping=True,
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Sesión transaccional: commit al salir bien, rollback al fallar."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """Dependencia de FastAPI. Solo lectura: no hace commit."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
