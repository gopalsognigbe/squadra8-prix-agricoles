"""Offre comparée au prix de détail des 3 marchés (touche 2 et touche 3)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.dialogue.moteur import Evenement, Moteur
from app.dialogue.services_prix import services_reels
from app.services.calculs import comparer_offre_marches, marche_prix_le_plus_eleve
from app.services.source_prix import ORDRE_MARCHES, get_source_prix
from tests.fakes import PRIX, services_fakes

BOHICON, HOUNDJRO, COVE = ORDRE_MARCHES


def texte(tour) -> str:
    return " ".join(p.texte for p in tour.phrases)


def touche2(produit_touche: str, montant: str):
    moteur = Moteur(services_fakes())
    sess = moteur.nouvelle_session("o3")
    moteur.traiter(sess, Evenement(type="DECROCHE"))
    moteur.traiter(sess, Evenement(type="TOUCHE", valeur=produit_touche))
    moteur.traiter(sess, Evenement(type="TOUCHE", valeur="2"))
    for c in montant:
        moteur.traiter(sess, Evenement(type="TOUCHE", valeur=c))
    return moteur.traiter(sess, Evenement(type="TOUCHE", valeur="#"))


def touche3(reponse: dict, produit_touche: str = "1"):
    moteur = Moteur(services_fakes(question=lambda v: reponse), voix_active=True)
    sess = moteur.nouvelle_session("o3v")
    moteur.traiter(sess, Evenement(type="DECROCHE"))
    moteur.traiter(sess, Evenement(type="TOUCHE", valeur=produit_touche))
    moteur.traiter(sess, Evenement(type="TOUCHE", valeur="3"))
    return moteur.traiter(sess, Evenement(type="VOIX", valeur="q.wav"))


def offre_voix(famille="mais", variete="blanc", marche=None, montant=15000, unite="100kg"):
    return {"erreur": None, "texte": "…", "intention": "juger_offre", "famille": famille,
            "variete": variete, "marche": marche, "montant": montant, "unite": unite}


def sans_mots_interdits(t: str) -> None:
    bas = t.casefold()
    assert "prix du jour" not in bas and "aujourd'hui" not in bas and "transport" not in bas


# ---------- calcul ----------
def test_comparer_trois_marches_ordre_et_verdicts() -> None:
    res = comparer_offre_marches(135.0, PRIX["mais"], ORDRE_MARCHES)
    assert [c["marche"] for c in res] == [BOHICON, HOUNDJRO, COVE]
    # 135 vs 137,36 → proche ; vs 128,57 → +5,0 % au-dessus ; vs 140 → proche
    assert [c["verdict"] for c in res] == ["proche", "au-dessus", "proche"]


def test_comparer_marche_manquant_jamais_invente() -> None:
    res = comparer_offre_marches(400.0, PRIX["soja"], ORDRE_MARCHES)
    assert [c["marche"] for c in res] == [BOHICON, HOUNDJRO, COVE]
    assert res[0]["reference_kg"] == 407.0
    assert res[1]["reference_kg"] is None and res[2]["reference_kg"] is None
    assert res[1]["verdict"] is None


def test_comparer_marche_dit_en_premier() -> None:
    res = comparer_offre_marches(135.0, PRIX["mais"], ORDRE_MARCHES, marche_dit=COVE)
    assert [c["marche"] for c in res] == [COVE, BOHICON, HOUNDJRO]


def test_prix_le_plus_eleve() -> None:
    res = comparer_offre_marches(135.0, PRIX["mais"], ORDRE_MARCHES)
    assert marche_prix_le_plus_eleve(res) == COVE
    # Un seul marché avec prix : pas de synthèse.
    assert marche_prix_le_plus_eleve(comparer_offre_marches(400.0, PRIX["soja"], ORDRE_MARCHES)) is None
    # Égalité au franc : pas de synthèse.
    egal = [{"marche": "A", "reference_kg": 140.2}, {"marche": "B", "reference_kg": 139.9}]
    assert marche_prix_le_plus_eleve(egal) is None


# ---------- touche 2 ----------
def test_touche2_trois_marches_annonces() -> None:
    tour = touche2("1", "13500")  # maïs, 13 500 F les 100 kg
    phrases = [p.texte for p in tour.phrases]
    assert phrases[0] == "L'acheteur propose cent trente-cinq francs le kilo."
    assert phrases[1] == ("À Bohicon, le kilo est à cent trente-sept francs, "
                          "relevé le vingt-cinq octobre : l'offre est proche de ce prix.")
    assert phrases[2] == ("À Houndjro (Abomey), le kilo est à cent vingt-neuf francs, "
                          "relevé le dix-neuf octobre : l'offre est au-dessus de ce prix.")
    assert phrases[3] == ("À Azogotchébou (Covè), le kilo est à cent quarante francs, "
                          "relevé le vingt-huit octobre : l'offre est proche de ce prix.")
    assert phrases[4] == "Le prix de détail le plus élevé est à Azogotchébou (Covè)."
    assert tour.phrases[-1].id == "R01" and tour.etat == "MENU_PRINCIPAL"
    sans_mots_interdits(texte(tour))


def test_touche2_marches_sans_prix_signales() -> None:
    tour = touche2("2", "35000")  # soja : seul Bohicon a un prix
    t = texte(tour)
    assert "À Bohicon, le kilo est à quatre cent sept francs" in t
    assert "l'offre est en dessous de ce prix" in t
    assert "À Houndjro (Abomey), il n'y a pas de prix récent pour ce produit." in t
    assert "À Azogotchébou (Covè), il n'y a pas de prix récent pour ce produit." in t
    assert "plus élevé" not in t
    sans_mots_interdits(t)


def test_touche2_aucun_prix_d01() -> None:
    moteur = Moteur(services_fakes(sans_prix=True))
    sess = moteur.nouvelle_session("vide")
    moteur.traiter(sess, Evenement(type="DECROCHE"))
    moteur.traiter(sess, Evenement(type="TOUCHE", valeur="1"))
    moteur.traiter(sess, Evenement(type="TOUCHE", valeur="2"))
    for c in "12000#":
        tour = moteur.traiter(sess, Evenement(type="TOUCHE", valeur=c))
    assert [p.id for p in tour.phrases] == ["D01", "R01"]


# ---------- touche 3 ----------
def test_touche3_offre_trois_marches_sans_marche_dit() -> None:
    tour = touche3(offre_voix(montant=15000, unite="100kg"))
    marches = [p.texte.split(",")[0] for p in tour.phrases[1:4]]
    assert marches == ["À Bohicon", "À Houndjro (Abomey)", "À Azogotchébou (Covè)"]
    assert texte(tour).count("l'offre est au-dessus de ce prix") == 3


def test_touche3_marche_dit_en_premier() -> None:
    tour = touche3(offre_voix(marche=COVE, montant=125, unite="kg"))
    phrases = [p.texte for p in tour.phrases]
    assert phrases[0] == "L'acheteur propose cent vingt-cinq francs le kilo."
    assert phrases[1].startswith("À Azogotchébou (Covè), le kilo est à cent quarante francs")
    assert phrases[2].startswith("À Bohicon,") and phrases[3].startswith("À Houndjro (Abomey),")
    sans_mots_interdits(texte(tour))


def test_touche3_marche_dit_sans_prix_annonce_puis_autres() -> None:
    tour = touche3(offre_voix(famille="soja", variete=None, marche=COVE,
                              montant=400, unite="kg"), produit_touche="2")
    phrases = [p.texte for p in tour.phrases]
    assert phrases[1] == "À Azogotchébou (Covè), il n'y a pas de prix récent pour ce produit."
    assert phrases[2].startswith("À Bohicon, le kilo est à quatre cent sept francs")


# ---------- source réelle (CSV d'exemple) et API ----------
def test_services_reels_offre_trois_marches() -> None:
    get_source_prix.cache_clear()
    o = services_reels().offre("mais", 15000)
    assert [c["marche"] for c in o["marches"]] == [BOHICON, HOUNDJRO, COVE]
    assert o["marche"] == BOHICON  # champs historiques inchangés
    assert all(c["reference_kg"] is None or c["date_releve"] for c in o["marches"])


def test_post_api_offre_renvoie_les_marches() -> None:
    from app.main import app

    with TestClient(app) as client:
        r = client.post("/api/offre", json={"produit": "Maïs Blanc", "montant_sac": 15000})
    data = r.json()
    assert data["disponible"] is True and data["marche"] == BOHICON
    assert [c["marche"] for c in data["marches"]][0] == BOHICON
    assert {c["marche"] for c in data["marches"]} == set(ORDRE_MARCHES)
