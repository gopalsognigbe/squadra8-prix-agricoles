"""Connexion et gestion des sessions SQLAlchemy."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Construit une seule fois le moteur à partir de DATABASE_URL."""
    url = get_settings().database_url
    options: dict[str, object] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **options)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Fabrique les sessions liées au moteur de l'application."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def nouvelle_session() -> Session:
    """Construit une session indépendante."""
    return get_session_factory()()


def get_session() -> Generator[Session, None, None]:
    """Dépendance FastAPI : ouvre une session et la ferme toujours."""
    session = nouvelle_session()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Session contextuelle pour scripts et services synchrones."""
    session = nouvelle_session()
    try:
        yield session
    finally:
        session.close()


def reinitialiser_moteur_pour_tests() -> None:
    """Vide les caches après changement de DATABASE_URL en tests."""
    get_engine.cache_clear()
    get_session_factory.cache_clear()
