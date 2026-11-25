"""Règles de secours : une offre proposée n'est pas une demande de cours."""

from app.ia.regles import comprendre_par_regles


def test_demande_de_cours_reste_prix() -> None:
    r = comprendre_par_regles("quel est le prix du maïs à Bohicon")
    assert r["intention"] == "prix"
    assert r["produit"] == "mais"
    assert r["marche"] == "bohicon"


def test_propose_c_est_bon_est_une_offre() -> None:
    r = comprendre_par_regles(
        "on me propose 12 000 francs le sac de maïs à Bohicon, c'est bon"
    )
    assert r["intention"] == "juger_offre"
    assert r["produit"] == "mais"
    assert r["marche"] == "bohicon"


def test_accepter_est_une_offre() -> None:
    r = comprendre_par_regles(
        "l'acheteur dit 15 000 francs le sac, est-ce que je dois accepter"
    )
    assert r["intention"] == "juger_offre"


def test_me_payer_c_est_correct_est_une_offre() -> None:
    r = comprendre_par_regles(
        "le client veut me payer 130 francs le kilo, c'est correct"
    )
    assert r["intention"] == "juger_offre"
