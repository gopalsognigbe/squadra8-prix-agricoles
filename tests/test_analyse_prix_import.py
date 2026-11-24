"""Intégration du moteur d'anomalies dans le flux d'import FPMA."""
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import Base, Marche, Prix, Produit, Source
from data.scripts.import_fpma import importer_lignes


def _setup():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    produit = Produit(code="mais", nom="Maïs", nom_fpma="Maïs Blanc", touche=1)
    marche = Marche(code="bohicon", nom="Bohicon", commune="Bohicon", nom_fpma="Bohicon")
    source = Source(code="historique", nom="Historique")
    session.add_all([produit, marche, source])
    session.flush()
    session.add(Prix(
        produit_id=produit.id, marche_id=marche.id, prix_fcfa=Decimal("200"),
        unite="kg", type_prix="detail", date_releve=date(2026, 10, 10),
        source_id=source.id, statut="valide",
    ))
    session.commit()
    return engine, session


def _line(price: str, day: str = "2026-10-15"):
    return {
        "produit": "Maïs Blanc", "marche": "Bohicon", "date": day,
        "prix": price, "type": "Retail", "unite": "KG", "devise": "XOF",
    }


def test_import_marque_variation_anormale_sans_valider():
    engine, session = _setup()
    try:
        result = importer_lignes(session, [_line("280")])
        row = session.scalars(select(Prix).where(Prix.statut == "en_attente")).one()
        assert result["importees"] == 1
        assert row.statut == "en_attente"
        assert row.score_anomalie is None
        assert "A_variation_dernier_prix" in row.motif_anomalie
    finally:
        session.close()
        engine.dispose()


def test_import_prix_normal_sans_alerte():
    engine, session = _setup()
    try:
        importer_lignes(session, [_line("220")])
        row = session.scalars(select(Prix).where(Prix.statut == "en_attente")).one()
        assert row.statut == "en_attente"
        assert row.motif_anomalie is None
        assert row.score_anomalie is None
    finally:
        session.close()
        engine.dispose()


def test_historique_autre_unite_non_utilise():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        produit = Produit(code="mais", nom="Maïs", nom_fpma="Maïs Blanc", touche=1)
        marche = Marche(code="bohicon", nom="Bohicon", commune="Bohicon", nom_fpma="Bohicon")
        source = Source(code="historique", nom="Historique")
        session.add_all([produit, marche, source])
        session.flush()
        session.add(Prix(
            produit_id=produit.id, marche_id=marche.id, prix_fcfa=Decimal("20000"),
            unite="sac_100kg", type_prix="detail", date_releve=date(2026, 10, 10),
            source_id=source.id, statut="valide",
        ))
        session.commit()
        importer_lignes(session, [_line("200")])
        row = session.scalars(select(Prix).where(Prix.statut == "en_attente")).one()
        assert row.motif_anomalie is None
    engine.dispose()
