"""Menu complet après chaque réponse, et réponse dans l'unité de l'offre (kilo ou sac)."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from app.dialogue import textes_fr as T
from app.dialogue.moteur import Evenement, Moteur
from app.dialogue.nombres import en_lettres
from app.dialogue.question_voix import _fusionner
from app.dialogue.services_prix import services_reels
from app.services.source_prix import get_source_prix
from tests.fakes import services_fakes

MENU = ["M01", "M02", "M03B", "M04"]
MENU_VOIX = ["M01", "M02", "M03", "M04"]


@pytest.fixture(autouse=True)
def csv_transport(tmp_path, monkeypatch):
    copie = tmp_path / "couts_transport.csv"
    shutil.copy(Path("data/transport/couts_transport.csv"), copie)
    monkeypatch.setenv("TRANSPORT_CSV", str(copie))
    get_source_prix.cache_clear()


def texte(tour) -> str:
    return " ".join(p.texte for p in tour.phrases)


def appel(services=None, voix=False):
    moteur = Moteur(services or services_reels(), voix_active=voix)
    sess = moteur.nouvelle_session("mu")

    def jouer(type_, valeur=None):
        return moteur.traiter(sess, Evenement(type=type_, valeur=valeur))

    jouer("DECROCHE")
    return jouer, sess


def offre_touche2(jouer, montant="13000", commune="7"):
    jouer("TOUCHE", "2")
    jouer("TOUCHE", "1")  # maïs
    for c in montant + "#":
        tour = jouer("TOUCHE", c)
    if tour.etat == "CHOIX_COMMUNE":
        tour = jouer("TOUCHE", commune)
    return tour


# ---------- menu de retour ----------
def test_r01_n_existe_plus():
    assert "R01" not in T.TEXTES
    with Path("app/voix/phrases.csv").open(encoding="utf-8-sig") as f:
        assert "R01" not in [ligne["identifiant"] for ligne in csv.DictReader(f, delimiter=";")]


def test_apres_une_reponse_le_menu_complet_est_annonce():
    jouer, _ = appel()
    tour = offre_touche2(jouer)
    assert [p.id for p in tour.phrases[-4:]] == MENU
    assert "Pour juger l'offre d'un acheteur, tapez 2." in texte(tour)
    assert tour.touches_valides == ["1", "2", "3", "4"]


def test_menu_apres_prix_avec_voix_prete():
    services = services_reels()
    services.question = lambda v: {"erreur": "ia"}
    jouer, _ = appel(services, voix=True)
    jouer("TOUCHE", "1")
    tour = jouer("TOUCHE", "1")
    assert [p.id for p in tour.phrases[-4:]] == MENU_VOIX


def test_silence_apres_reponse_repete_le_menu():
    jouer, _ = appel()
    offre_touche2(jouer)
    tour = jouer("SILENCE")
    assert [p.id for p in tour.phrases] == ["S01"] + MENU


def test_touches_1_et_2_redemandent_le_produit_et_4_reecoute():
    jouer, sess = appel()
    reponse = offre_touche2(jouer)
    rejoue = jouer("TOUCHE", "4")
    assert [p.texte for p in rejoue.phrases] == [p.texte for p in reponse.phrases]
    assert jouer("TOUCHE", "1").etat == "CHOIX_PRODUIT"
    tour = jouer("TOUCHE", "1")  # maïs → prix
    assert "Maïs blanc" in texte(tour) and [p.id for p in tour.phrases[-4:]] == MENU
    assert jouer("TOUCHE", "2").etat == "CHOIX_PRODUIT"
    assert jouer("TOUCHE", "1").etat == "OFFRE_MONTANT"  # maïs, puis le montant


# ---------- touche 2 : toujours en sac de 100 kg ----------
def test_touche2_en_sac_avec_transport():
    jouer, _ = appel()
    t = texte(offre_touche2(jouer))
    assert "L'acheteur propose treize mille francs le sac de cent kilos." in t
    assert ("À Bohicon, le sac de cent kilos est à treize mille sept cent trente-six francs, "
            "relevé le vingt-cinq octobre.") in t
    assert ("Le transport depuis Zagnanado coûte environ huit cents francs le sac, "
            "c'est une estimation.") in t
    assert "Il vous resterait douze mille neuf cent trente-six francs" in t
    assert "le kilo" not in t and "prix du jour" not in t


def test_touche2_en_sac_sans_transport():
    jouer, _ = appel()
    t = texte(offre_touche2(jouer, commune="0"))
    assert "L'acheteur propose treize mille francs le sac de cent kilos." in t
    assert "transport" not in t and "relevé le" in t and "le kilo" not in t


def test_touche2_en_sac_services_fakes():
    jouer, _ = appel(services_fakes())
    t = texte(offre_touche2(jouer, montant="12000"))
    assert "douze mille francs le sac de cent kilos" in t and "le kilo" not in t


# ---------- touche 3 : unité comprise ----------
def _voix(montant, unite, texte_q):
    services = services_reels()
    compris = {"intention": "juger_offre", "produit": "mais", "variete": "blanc",
               "marche": None, "montant_offre": montant, "unite_offre": unite}
    services.question = lambda v: _fusionner(texte_q, compris)
    jouer, sess = appel(services, voix=True)
    jouer("TOUCHE", "3")
    return jouer, sess


def test_touche3_au_kilo_repond_au_kilo():
    jouer, _ = _voix(150, "kg", "je suis à Zagnanado, on me propose 150 francs le kilo de maïs blanc")
    t = texte(jouer("VOIX", "x"))
    assert "L'acheteur propose cent cinquante francs le kilo." in t
    assert "le kilo est à cent trente-sept francs" in t
    assert "coûte environ huit francs le kilo, c'est une estimation" in t
    assert "Il vous resterait cent vingt-neuf francs" in t
    assert "sac" not in t


def test_touche3_sac_de_100_kilos_repond_en_sac():
    jouer, _ = _voix(13000, "100kg",
                     "je suis à Zagnanado, on me propose 13000 francs le sac de 100 kilos de maïs blanc")
    t = texte(jouer("VOIX", "x"))
    assert "treize mille francs le sac de cent kilos" in t
    assert "huit cents francs le sac" in t and "le kilo" not in t


def test_touche3_sac_confirme_100_kilos_repond_en_sac():
    jouer, _ = _voix(13000, "sac", "on me propose 13000 francs le sac de maïs blanc")
    assert jouer("VOIX", "x").etat == "CONFIRMER_SAC"
    tour = jouer("TOUCHE", "1")
    assert tour.etat == "CHOIX_COMMUNE"
    t = texte(jouer("TOUCHE", "0"))
    assert "treize mille francs le sac de cent kilos" in t and "le kilo" not in t


@pytest.mark.parametrize("touche,attendu,absent", [
    ("1", "L'acheteur propose cent cinquante francs le kilo.", "sac"),
    ("2", "L'acheteur propose cent cinquante francs le sac de cent kilos.", "le kilo"),
])
def test_choisir_unite(touche, attendu, absent):
    jouer, _ = _voix(150, None, "on me propose 150 francs pour le maïs blanc")
    assert jouer("VOIX", "x").etat == "CHOISIR_UNITE"
    assert jouer("TOUCHE", touche).etat == "CHOIX_COMMUNE"
    t = texte(jouer("TOUCHE", "0"))
    assert attendu in t and absent not in t.split("Pour les prix")[0]


def test_unite_remise_a_zero_apres_la_reponse():
    jouer, sess = _voix(150, "kg", "on me propose 150 francs le kilo de maïs blanc")
    jouer("VOIX", "x")
    jouer("TOUCHE", "0")
    assert sess.unite_offre is None
    t = texte(offre_touche2(jouer))  # nouvelle offre au clavier : en sac
    assert "le sac de cent kilos" in t


def test_verdict_identique_kilo_et_sac():
    o = services_reels().offre("mais", 13000, commune="Zagnanado")
    kg = T.phrases_offre(o, unite="kg")
    sac = T.phrases_offre(o, unite="sac")
    for a, b in zip(kg[1:], sac[1:]):
        assert a.split(" : ")[-1] == b.split(" : ")[-1]


# ---------- grands nombres ----------
@pytest.mark.parametrize("n,lettres", [
    (13736, "treize mille sept cent trente-six"),
    (12936, "douze mille neuf cent trente-six"),
    (40700, "quarante mille sept cents"),
    (100000, "cent mille"),
    (1250000, "un million deux cent cinquante mille"),
])
def test_grands_nombres_en_lettres(n, lettres):
    assert en_lettres(n) == lettres
