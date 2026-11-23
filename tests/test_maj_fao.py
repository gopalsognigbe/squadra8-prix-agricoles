"""Tests de la maj FAO incrémentale (API simulée, aucun réseau)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from data.scripts.maj_fao import (
    COLONNES,
    filtrer_series_mvp,
    lancer_maj_fao,
    lire_csv,
)


def _serie(
    uuid: str,
    *,
    commodity: str,
    market: str,
    admin_unit: str = "Zou",
    admin_unit2: str = "",
    price_type: str = "Retail",
) -> dict[str, Any]:
    return {
        "uuid": uuid,
        "market_name": market,
        "admin_unit": admin_unit,
        "admin_unit2": admin_unit2,
        "commodity_name": commodity,
        "price_type": price_type,
        "measure_unit_label": "KG",
        "currency": "XOF",
        "source_name": "SIM-Bénin",
        "market_type": "retail",
        "periodicity": [{"period": "daily", "calculated": False}],
    }


def _prix(uuid: str, points: list[tuple[str, float]]) -> dict[str, Any]:
    return {
        "uuid": uuid,
        "datapoints": [
            {"price_value": prix, "date": date, "periodicity": "daily"} for date, prix in points
        ],
    }


class _FakeHTTPResponse:
    def __init__(self, payload: Any) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _fake_urlopen_factory(routes: dict[str, Any]):
    """Mappe une URL (préfixe ou exacte) vers un payload JSON."""

    def fake_urlopen(requete: Any, timeout: float = 60) -> _FakeHTTPResponse:
        url = requete.full_url if hasattr(requete, "full_url") else str(requete)
        for cle, payload in routes.items():
            if cle in url:
                return _FakeHTTPResponse(payload)
        raise AssertionError(f"URL non mockée : {url}")

    return fake_urlopen


@pytest.fixture
def csv_tmp(tmp_path: Path) -> Path:
    return tmp_path / "prix_fao.csv"


def test_filtre_mvp_exclut_zinvi_et_abomey_instad() -> None:
    series = [
        _serie("1", commodity="Maïs Blanc", market="Bohicon"),
        _serie("2", commodity="Maïs Blanc", market="Houndjro (Abomey)"),
        _serie("3", commodity="Maïs Blanc", market="Azogotchébou (Covè)"),
        _serie("4", commodity="Maïs Blanc", market="Zinvié", admin_unit="Atlantique"),
        _serie("5", commodity="Maize", market="Abomey", admin_unit="Zou department (1)"),
    ]
    retenues = filtrer_series_mvp(series)
    marches = {s["market_name"] for s in retenues}
    assert marches == {"Bohicon", "Houndjro (Abomey)", "Azogotchébou (Covè)"}
    assert all(s["commodity_name"] == "Maïs Blanc" for s in retenues)


def test_premier_lancement_ecrit_points(csv_tmp: Path) -> None:
    series = [_serie("u1", commodity="Maïs Blanc", market="Bohicon")]
    prix = [_prix("u1", [("2026-11-01", 250.0), ("2026-11-02", 255.0)])]

    routes = {
        "FpmaSerieDomestic/": series,
        "FpmaSeriePrice/": prix,
    }

    with (
        patch("data.scripts.maj_fao.urllib.request.urlopen", side_effect=_fake_urlopen_factory(routes)),
        patch("data.scripts.maj_fao.time.sleep"),
    ):
        resume = lancer_maj_fao(chemin_csv=csv_tmp, tout_benin=False)

    assert resume["succes"] is True
    assert resume["nouveaux"] == 2
    assert resume["derniere_date"] == "2026-11-02"
    lignes = lire_csv(csv_tmp)
    assert len(lignes) == 2
    assert lignes[0]["produit"] == "Maïs Blanc"
    assert lignes[0]["marche"] == "Bohicon"
    assert set(lignes[0]) >= set(COLONNES)


def test_second_lancement_memes_points_zero_nouveau(csv_tmp: Path) -> None:
    series = [_serie("u1", commodity="Soja", market="Bohicon")]
    prix = [_prix("u1", [("2026-11-01", 400.0)])]
    routes = {
        "FpmaSerieDomestic/": series,
        "FpmaSeriePrice/": prix,
    }

    with (
        patch("data.scripts.maj_fao.urllib.request.urlopen", side_effect=_fake_urlopen_factory(routes)),
        patch("data.scripts.maj_fao.time.sleep"),
    ):
        r1 = lancer_maj_fao(chemin_csv=csv_tmp)
        r2 = lancer_maj_fao(chemin_csv=csv_tmp)

    assert r1["nouveaux"] == 1
    assert r2["succes"] is True
    assert r2["nouveaux"] == 0
    assert len(lire_csv(csv_tmp)) == 1


def test_second_lancement_point_plus_recent(csv_tmp: Path) -> None:
    series = [_serie("u1", commodity="Haricot blanc", market="Bohicon")]
    prix_v1 = [_prix("u1", [("2026-11-01", 500.0)])]
    prix_v2 = [_prix("u1", [("2026-11-01", 500.0), ("2026-11-05", 510.0)])]

    with (
        patch(
            "data.scripts.maj_fao.urllib.request.urlopen",
            side_effect=_fake_urlopen_factory(
                {"FpmaSerieDomestic/": series, "FpmaSeriePrice/": prix_v1}
            ),
        ),
        patch("data.scripts.maj_fao.time.sleep"),
    ):
        lancer_maj_fao(chemin_csv=csv_tmp)

    with (
        patch(
            "data.scripts.maj_fao.urllib.request.urlopen",
            side_effect=_fake_urlopen_factory(
                {"FpmaSerieDomestic/": series, "FpmaSeriePrice/": prix_v2}
            ),
        ),
        patch("data.scripts.maj_fao.time.sleep"),
    ):
        resume = lancer_maj_fao(chemin_csv=csv_tmp)

    assert resume["nouveaux"] == 1
    lignes = lire_csv(csv_tmp)
    assert len(lignes) == 2
    dates = sorted(ligne["date"] for ligne in lignes)
    assert dates == ["2026-11-01", "2026-11-05"]


def test_echec_reseau_conserve_csv(csv_tmp: Path) -> None:
    series = [_serie("u1", commodity="Maïs Jaune", market="Bohicon")]
    prix = [_prix("u1", [("2026-10-01", 200.0)])]
    routes = {
        "FpmaSerieDomestic/": series,
        "FpmaSeriePrice/": prix,
    }

    with (
        patch("data.scripts.maj_fao.urllib.request.urlopen", side_effect=_fake_urlopen_factory(routes)),
        patch("data.scripts.maj_fao.time.sleep"),
    ):
        lancer_maj_fao(chemin_csv=csv_tmp)

    avant = lire_csv(csv_tmp)
    assert len(avant) == 1

    with (
        patch(
            "data.scripts.maj_fao.urllib.request.urlopen",
            side_effect=OSError("réseau coupé"),
        ),
        patch("data.scripts.maj_fao.time.sleep"),
    ):
        resume = lancer_maj_fao(chemin_csv=csv_tmp)

    assert resume["succes"] is False
    assert resume["erreur"]
    assert lire_csv(csv_tmp) == avant


def test_maj_fao_au_demarrage_false_n_appelle_pas() -> None:
    os.environ["MAJ_FAO_AU_DEMARRAGE"] = "false"
    get_settings.cache_clear()

    with patch("app.main.lancer_maj_fao") as mock_maj:
        from app.main import app

        with TestClient(app) as client:
            reponse = client.get("/sante")
            assert reponse.status_code == 200
            assert reponse.json() == {"statut": "ok"}
        mock_maj.assert_not_called()

    # Remettre la consigne globale des tests.
    os.environ["MAJ_FAO_AU_DEMARRAGE"] = "false"
    get_settings.cache_clear()


def test_maj_fao_au_demarrage_true_appelle_en_fond() -> None:
    os.environ["MAJ_FAO_AU_DEMARRAGE"] = "true"
    get_settings.cache_clear()

    with patch("app.main.lancer_maj_fao", return_value={"succes": True}) as mock_maj:
        from app.main import app

        with TestClient(app) as client:
            assert client.get("/sante").json() == {"statut": "ok"}
            for _ in range(100):
                if mock_maj.called:
                    break
                time.sleep(0.01)
        assert mock_maj.called

    os.environ["MAJ_FAO_AU_DEMARRAGE"] = "false"
    get_settings.cache_clear()


def test_ignorer_point_sans_prix(csv_tmp: Path) -> None:
    series = [_serie("u1", commodity="Maïs Blanc", market="Bohicon")]
    prix = [
        {
            "uuid": "u1",
            "datapoints": [
                {"price_value": None, "date": "2026-11-01", "periodicity": "daily"},
                {"price_value": 100.0, "date": "", "periodicity": "daily"},
                {"price_value": 110.0, "date": "2026-11-03", "periodicity": "daily"},
            ],
        }
    ]
    routes = {"FpmaSerieDomestic/": series, "FpmaSeriePrice/": prix}

    with (
        patch("data.scripts.maj_fao.urllib.request.urlopen", side_effect=_fake_urlopen_factory(routes)),
        patch("data.scripts.maj_fao.time.sleep"),
    ):
        resume = lancer_maj_fao(chemin_csv=csv_tmp)

    assert resume["nouveaux"] == 1
    assert lire_csv(csv_tmp)[0]["date"] == "2026-11-03"
