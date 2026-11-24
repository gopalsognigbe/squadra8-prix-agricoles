"""Source de prix FAO (plan B) : CSV d'exemple, aucun réseau."""

from __future__ import annotations

import csv
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.services.calculs import vers_100kg
from app.services.source_prix import (
    SourceFaoCsv,
    get_source_prix,
    resoudre_produit,
)

CSV_EXEMPLE = Path(__file__).resolve().parent / "donnees" / "prix_fao_exemple.csv"
COLONNES = [
    "pays",
    "marche",
    "departement",
    "commune",
    "produit",
    "type",
    "unite",
    "devise",
    "date",
    "prix",
    "source_serie_id",
    "periodicite",
    "source",
    "type_marche",
]


@pytest.fixture(autouse=True)
def _caches() -> None:
    os.environ["SOURCE_PRIX"] = "fao"
    os.environ["PRIX_FAO_CSV"] = str(CSV_EXEMPLE)
    get_settings.cache_clear()
    get_source_prix.cache_clear()
    yield
    get_settings.cache_clear()
    get_source_prix.cache_clear()


def test_vers_100kg_137_36() -> None:
    assert vers_100kg(137.36) == 13736


def test_prix_du_jour_mais_blanc_trois_marches() -> None:
    source = SourceFaoCsv(CSV_EXEMPLE)
    liste = source.prix_du_jour("Maïs Blanc")
    assert [p["marche"] for p in liste] == [
        "Bohicon",
        "Houndjro (Abomey)",
        "Azogotchébou (Covè)",
    ]
    bohicon = liste[0]
    assert bohicon["prix_kg"] == pytest.approx(137.36)
    assert bohicon["prix_fcfa"] == pytest.approx(137.36)
    assert bohicon["prix_100kg"] == 13736
    assert bohicon["date_releve"] == "2026-10-25"
    assert bohicon["source"] == "SIM-Bénin - CT-SAGSA"
    assert bohicon["unite"] == "Kilogramme"
    assert bohicon["type_prix"] == "detail"
    assert bohicon["devise"] == "XOF"


def test_alias_mais_identique() -> None:
    source = SourceFaoCsv(CSV_EXEMPLE)
    a = source.prix_du_jour("mais")
    b = source.prix_du_jour("Maïs Blanc")
    assert resoudre_produit("mais") == "Maïs Blanc"
    assert [p["produit"] for p in a] == [p["produit"] for p in b]
    assert [p["marche"] for p in a] == [p["marche"] for p in b]
    assert [p["prix_kg"] for p in a] == [p["prix_kg"] for p in b]


def test_haricot_noir_bohicon_absent() -> None:
    source = SourceFaoCsv(CSV_EXEMPLE)
    assert source.dernier_prix("Haricot noir", "Bohicon") is None


def test_marches_hors_mvp_ignores() -> None:
    source = SourceFaoCsv(CSV_EXEMPLE)
    liste = source.prix_du_jour("Maïs Blanc")
    marches = {p["marche"] for p in liste}
    assert "Abomey" not in marches
    assert "Hlanxi (Zogbodomey)" not in marches
    # Pas d'alias silencieux
    assert source.dernier_prix("Maïs Blanc", "Abomey") is None


def test_dernier_anormal_ignore_precedent_ok() -> None:
    source = SourceFaoCsv(CSV_EXEMPLE)
    prix = source.dernier_prix("Maïs Blanc", "Houndjro (Abomey)")
    assert prix is not None
    # 173.63 du 2026-10-27 est anormal ; on garde 128.57 du 2026-10-19
    assert prix["prix_kg"] == pytest.approx(128.57)
    assert prix["date_releve"] == "2026-10-19"


def test_fichier_absent_sans_exception(tmp_path: Path) -> None:
    source = SourceFaoCsv(tmp_path / "inexistant.csv")
    assert source.prix_du_jour("Maïs Blanc") == []
    assert source.dernier_prix("Maïs Blanc", "Bohicon") is None


def test_fichier_vide_sans_exception(tmp_path: Path) -> None:
    vide = tmp_path / "vide.csv"
    vide.write_text("", encoding="utf-8-sig")
    source = SourceFaoCsv(vide)
    assert source.prix_du_jour("mais") == []


def test_cache_recharge_si_fichier_change(tmp_path: Path) -> None:
    chemin = tmp_path / "prix.csv"

    def ecrire(prix: str, date: str) -> None:
        with chemin.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(COLONNES)
            w.writerow(
                [
                    "Bénin",
                    "Bohicon",
                    "Zou",
                    "Bohicon",
                    "Maïs Blanc",
                    "detail",
                    "Kilogramme",
                    "XOF",
                    date,
                    prix,
                    "s1",
                    "daily",
                    "SIM-Bénin - CT-SAGSA",
                    "Secondaire",
                ]
            )

    ecrire("100.00", "2026-10-01")
    source = SourceFaoCsv(chemin)
    assert source.dernier_prix("Maïs Blanc", "Bohicon")["prix_kg"] == pytest.approx(100.0)

    time.sleep(0.05)  # mtime distinct
    ecrire("150.00", "2026-10-02")
    lu = source.dernier_prix("Maïs Blanc", "Bohicon")
    assert lu is not None
    assert lu["prix_kg"] == pytest.approx(150.0)
    assert lu["date_releve"] == "2026-10-02"


def test_get_api_prix_bohicon() -> None:
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/api/prix", params={"produit": "mais", "marche": "Bohicon"})
    assert r.status_code == 200
    data = r.json()
    assert data["disponible"] is True
    assert data["produit"] == "Maïs Blanc"
    assert data["prix"][0]["date_releve"] == "2026-10-25"
    assert data["prix"][0]["prix_kg"] == pytest.approx(137.36)
    assert data["prix"][0]["prix_100kg"] == 13736


def test_get_api_prix_haricot_noir_bohicon_indisponible() -> None:
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/api/prix/Haricot%20noir", params={"marche": "Bohicon"})
    assert r.status_code == 200
    data = r.json()
    assert data["disponible"] is False
    assert data["prix"] == []
    assert "Pas de prix disponible" in data["message"]
    for token in ("137", "450", "F/kg", "173"):
        assert token not in data["message"]


def test_post_api_offre_proche() -> None:
    from app.main import app

    with TestClient(app) as client:
        # Réf Bohicon 137.36 → offre 138 ≈ proche
        r = client.post(
            "/api/offre",
            json={"produit": "Maïs Blanc", "marche": "Bohicon", "offre_kg": 138.0},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["disponible"] is True
    assert data["verdict"] == "proche"
    assert data["date_releve"] == "2026-10-25"
    assert "ecart_f" in data and "ecart_pct" in data


def test_post_api_offre_sans_reference() -> None:
    from app.main import app

    with TestClient(app) as client:
        r = client.post(
            "/api/offre",
            json={"produit": "Haricot noir", "marche": "Bohicon", "offre_kg": 400.0},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["disponible"] is False
    assert "verdict" not in data


def test_source_base_non_prete(tmp_path, monkeypatch) -> None:
    """Base SQLite vide : SourceBase, pas d'erreur ; prix_du_jour → []."""
    from app.db.models import Base
    from app.db.session import get_engine, reinitialiser_moteur_pour_tests
    from app.services.source_prix import SourceBase

    db_path = tmp_path / "vide.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    monkeypatch.setenv("SOURCE_PRIX", "base")
    get_settings.cache_clear()
    get_source_prix.cache_clear()
    reinitialiser_moteur_pour_tests()
    Base.metadata.create_all(get_engine())

    source = get_source_prix()
    assert isinstance(source, SourceBase)
    assert source.prix_du_jour("Maïs Blanc") == []
