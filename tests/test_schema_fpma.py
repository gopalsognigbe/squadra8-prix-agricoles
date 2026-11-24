"""Tests de contrat minimaux du schéma et de l'import FPMA."""

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.db.models import Appel, Base, Interaction, Produit
from data.scripts.maj_fao import filtrer_series_mvp, mapper_type_prix


def test_schema_creates_on_sqlite() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    names = set(inspect(engine).get_table_names())
    assert {
        "produit",
        "marche",
        "source",
        "prix",
        "utilisateur",
        "appel",
        "interaction",
        "demande_rappel",
        "liste_noire",
        "journal",
    } <= names


def test_sqlite_bigint_ids_and_uuid_are_portable() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        p = Produit(
            code="mais_blanc",
            nom="Maïs Blanc",
            nom_fpma="Maïs Blanc",
            touche=1,
            actif=True,
        )
        db.add(p)
        db.flush()
        appel = Appel(numero_hash="a" * 64, canal="sim")
        db.add(appel)
        db.flush()
        interaction = Interaction(appel_id=appel.id, etape="menu", entree="1")
        db.add(interaction)
        db.flush()
        assert interaction.id is not None


def test_fpma_price_type_mapping_is_explicit() -> None:
    assert mapper_type_prix("Retail") == "detail"
    assert mapper_type_prix("Wholesale") == "gros"
    assert mapper_type_prix("unknown") == "unknown"


def test_fpma_filter_keeps_only_mvp_pairs() -> None:
    series = [
        {"commodity_name": "Maïs Blanc", "market_name": "Bohicon"},
        {"commodity_name": "Igname", "market_name": "Bohicon"},
        {"commodity_name": "Soja", "market_name": "Marché inconnu"},
    ]
    assert filtrer_series_mvp(series) == [series[0]]
