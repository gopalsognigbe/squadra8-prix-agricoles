"""Tests de SourceBase : prix validés, frais, arrondi au franc."""

from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Base, Marche, Prix, Produit, Source
from app.db.seed import charger_donnees, charger_sources_et_admin
from app.db.session import get_engine, nouvelle_session, reinitialiser_moteur_pour_tests
from app.services.calculs import arrondir_f
from app.services.source_prix import SourceBase, get_source_prix


def _activer_source_base(database_url: str) -> SourceBase:
    os.environ["SOURCE_PRIX"] = "base"
    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()
    get_source_prix.cache_clear()
    reinitialiser_moteur_pour_tests()
    source = get_source_prix()
    assert isinstance(source, SourceBase)
    return source


def _preparer_base(tmp_path: Path) -> tuple[str, object]:
    db_path = tmp_path / "source_base.sqlite"
    url = f"sqlite+pysqlite:///{db_path}"
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    reinitialiser_moteur_pour_tests()
    engine = get_engine()
    Base.metadata.create_all(engine)
    session = nouvelle_session()
    charger_donnees(session)
    charger_sources_et_admin(session)
    session.flush()
    return url, session


def test_source_base_vide_renvoie_liste_vide(tmp_path: Path) -> None:
    url, session = _preparer_base(tmp_path)
    session.commit()
    session.close()
    source = _activer_source_base(url)
    assert source.prix_du_jour("Maïs Blanc") == []
    assert source.dernier_prix("Maïs Blanc", "Bohicon") is None


def test_source_base_filtre_statut_et_fraicheur(tmp_path: Path) -> None:
    url, session = _preparer_base(tmp_path)
    produit = session.scalar(select(Produit).where(Produit.code == "mais_blanc"))
    marche = session.scalar(select(Marche).where(Marche.code == "bohicon"))
    source_row = session.scalar(select(Source).where(Source.code == "saisie"))
    assert produit and marche and source_row
    aujourd_hui = date.today()

    session.add(
        Prix(
            produit_id=produit.id,
            marche_id=marche.id,
            prix_fcfa=Decimal("200.00"),
            unite="kg",
            type_prix="detail",
            date_releve=aujourd_hui,
            source_id=source_row.id,
            statut="en_attente",
        )
    )
    session.add(
        Prix(
            produit_id=produit.id,
            marche_id=marche.id,
            prix_fcfa=Decimal("210.00"),
            unite="kg",
            type_prix="detail",
            date_releve=aujourd_hui - timedelta(days=61),
            source_id=source_row.id,
            statut="valide",
        )
    )
    session.add(
        Prix(
            produit_id=produit.id,
            marche_id=marche.id,
            prix_fcfa=Decimal("137.36"),
            unite="kg",
            type_prix="detail",
            date_releve=aujourd_hui - timedelta(days=5),
            source_id=source_row.id,
            statut="valide",
        )
    )
    session.commit()
    session.close()

    source = _activer_source_base(url)
    lignes = source.prix_du_jour("Maïs Blanc")
    assert len(lignes) == 1
    ligne = lignes[0]
    assert ligne["marche"] == "Bohicon"
    assert ligne["prix_kg"] == 137
    assert ligne["prix_fcfa"] == 137
    assert ligne["prix_kg_annonce"] == 137
    assert ligne["date_releve"] == (aujourd_hui - timedelta(days=5)).isoformat()
    assert "prix du jour" not in str(ligne).casefold()


def test_source_base_arrondi_franc_pas_cinq(tmp_path: Path) -> None:
    """137,36 → 137 ; 253 reste 253 (arrondir_f donnerait 255)."""
    url, session = _preparer_base(tmp_path)
    produit = session.scalar(select(Produit).where(Produit.code == "soja"))
    marche = session.scalar(select(Marche).where(Marche.code == "houndjro"))
    source_row = session.scalar(select(Source).where(Source.code == "saisie"))
    assert produit and marche and source_row
    session.add(
        Prix(
            produit_id=produit.id,
            marche_id=marche.id,
            prix_fcfa=Decimal("253.00"),
            unite="kg",
            type_prix="detail",
            date_releve=date.today(),
            source_id=source_row.id,
            statut="valide",
        )
    )
    session.commit()
    session.close()

    source = _activer_source_base(url)
    ligne = source.dernier_prix("Soja", "Houndjro (Abomey)")
    assert ligne is not None
    assert ligne["prix_kg_annonce"] == 253
    assert arrondir_f(253) == 255
