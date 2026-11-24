"""Cas simples pour le calcul de l'offre (touche 2)."""

import pytest

from app.services.calculs import arrondir_au_franc, arrondir_f, juger_offre, vers_100kg


def test_juger_offre_au_dessus() -> None:
    # 300 vs 200 = +50 % → au-dessus
    r = juger_offre(300.0, 200.0)
    assert r["ecart_f"] == 100.0
    assert r["ecart_pct"] == 50.0
    assert r["verdict"] == "au-dessus"


def test_juger_offre_proche() -> None:
    # 202 vs 200 = +1 % → proche
    r = juger_offre(202.0, 200.0)
    assert r["ecart_f"] == 2.0
    assert r["ecart_pct"] == 1.0
    assert r["verdict"] == "proche"


def test_juger_offre_en_dessous() -> None:
    # 180 vs 200 = −10 % → en dessous
    r = juger_offre(180.0, 200.0)
    assert r["ecart_f"] == -20.0
    assert r["ecart_pct"] == -10.0
    assert r["verdict"] == "en dessous"


def test_juger_offre_limite_plus_5() -> None:
    # Exactement +5 % → au-dessus (« 5 % ou plus »)
    r = juger_offre(210.0, 200.0)
    assert r["ecart_pct"] == 5.0
    assert r["verdict"] == "au-dessus"


def test_juger_offre_limite_moins_5() -> None:
    # Exactement −5 % → encore « proche » (borne basse incluse)
    r = juger_offre(190.0, 200.0)
    assert r["ecart_pct"] == -5.0
    assert r["verdict"] == "proche"


def test_juger_offre_juste_sous_moins_5() -> None:
    # Juste sous −5 % → en dessous
    r = juger_offre(189.0, 200.0)
    assert r["ecart_pct"] == pytest.approx(-5.5)
    assert r["verdict"] == "en dessous"


def test_juger_offre_prix_nul() -> None:
    with pytest.raises(ValueError):
        juger_offre(0.0, 200.0)
    with pytest.raises(ValueError):
        juger_offre(200.0, 0.0)
    with pytest.raises(ValueError):
        juger_offre(-10.0, 200.0)
    with pytest.raises(ValueError):
        juger_offre(200.0, -1.0)


def test_vers_100kg() -> None:
    assert vers_100kg(250.0) == 25_000
    assert vers_100kg(199.5) == 19_950


def test_arrondir_f() -> None:
    assert arrondir_f(252.0) == 250
    assert arrondir_f(253.0) == 255
    assert arrondir_f(250.0) == 250


def test_arrondir_au_franc() -> None:
    assert arrondir_au_franc(137.36) == 137
    assert arrondir_au_franc(253.0) == 253
    assert arrondir_au_franc(137.36) != arrondir_f(137.36)
    assert arrondir_f(137.36) == 135
    assert arrondir_f(253.0) == 255
