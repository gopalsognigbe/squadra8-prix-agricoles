"""Configuration pytest : pas d'appel FAO réel pendant les tests."""

from __future__ import annotations

import os

# Avant tout import de l'app : désactiver la maj FAO au démarrage.
os.environ["MAJ_FAO_AU_DEMARRAGE"] = "false"


def pytest_configure() -> None:
    """Vide le cache settings si l'environnement a changé."""
    try:
        from app.config import get_settings

        get_settings.cache_clear()
    except Exception:  # noqa: BLE001 — import optionnel au tout début
        pass
