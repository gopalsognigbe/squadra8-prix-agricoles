"""Transport commune → marché : commune demandée, net après transport, dashboard."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dialogue import textes_fr as T
from app.dialogue.moteur import Evenement, Moteur
from app.dialogue.question_voix import _fusionner
from app.dialogue.services_prix import services_reels
from app.services import transport as TR
from app.services.calculs import comparer_offre_marches
from app.services.source_prix import ORDRE_MARCHES, get_source_prix
from tests.fakes import services_fakes

BOHICON, HOUNDJRO, COVE = ORDRE_MARCHES
CSV_REPO = Path("data/transport/couts_transport.csv")


@pytest.fixture(autouse=True)
def csv_temporaire(tmp_path, monkeypatch):
    """Chaque test travaille sur une copie : le CSV du dépôt n'est jamais réécrit."""
    copie = tmp_path / "couts_transport.csv"
    shutil.copy(CSV_REPO, copie)
    monkeypatch.setenv("TRANSPORT_CSV", str(copie))
    get_source_prix.cache_clear()
    return copie


def texte(tour) -> str:
    return " ".join(p.texte for p in tour.phrases)


def _offre_touche2(moteur, montant="15000", commune=None):
    sess = moteur.nouvelle_session("t")
    tours = [moteur.traiter(sess, Evenement(type="DECROCHE"))]

    def t(v):
        tours.append(moteur.traiter(sess, Evenement(type="TOUCHE", valeur=v)))
        return tours[-1]

    t("2")
    t("1")  # maïs
    for c in montant + "#":
        t(c)
    if commune is not None:
        t(commune)
    return sess, tours


# ---------- tableau ----------
def test_tableau_9_communes_x_3_marches_tous_estimes():
    lignes = TR.lire_couts(CSV_REPO)
    assert len(lignes) == 27
    assert {ligne["commune"] for ligne in lignes} == set(TR.COMMUNES)
    assert {ligne["marche"] for ligne in lignes} == set(ORDRE_MARCHES)
    # Rien n'est présenté comme vérifié : c'est à l'équipe de le faire.
    assert {ligne["statut"] for ligne in lignes} == {"estime"}
    for ligne in lignes:
        assert ligne["cout_min"] <= ligne["cout_sac_100kg"] <= ligne["cout_max"]
        assert ligne["source"]


def test_touches_communes_1_a_9():
    assert len(TR.COMMUNES) == 9
    assert TR.TOUCHE_COMMUNE["7"] == "Zagnanado"
    assert "0" not in TR.TOUCHE_COMMUNE


def test_cout_transport_et_cout_manquant(csv_temporaire):
    c = TR.cout_transport("Zagnanado", BOHICON)
    assert c["cout_sac_100kg"] == 800 and c["cout_kg"] == 8.0 and c["statut"] == "estime"
    assert TR.cout_transport(None, BOHICON) is None
    assert TR.cout_transport("Paris", BOHICON) is None


# ---------- calcul ----------
def test_verdict_sur_le_net():
    liste = [{"marche": BOHICON, "prix_kg": 150.0, "date_releve": "2026-10-25"}]
    # 150 − 10 de transport = 140 : une offre à 140 est « proche » du net
    # alors qu'elle serait « en dessous » du prix brut.
    cmp = comparer_offre_marches(140.0, liste, [BOHICON],
                                 transport=lambda m: {"cout_kg": 10.0, "statut": "estime"})
    c = cmp[0]
    assert c["net_kg"] == 140.0 and c["verdict"] == "proche" and c["verdict_brut"] == "en dessous"


def test_sans_cout_rien_ne_change():
    liste = [{"marche": BOHICON, "prix_kg": 150.0, "date_releve": "2026-10-25"}]
    c = comparer_offre_marches(140.0, liste, [BOHICON], transport=lambda m: None)[0]
    assert "net_kg" not in c and c["verdict"] == "en dessous"


# ---------- touche 2 ----------
def test_touche2_commune_demandee_puis_net_annonce():
    moteur = Moteur(services_reels(), voix_active=False)
    sess, tours = _offre_touche2(moteur, commune="7")  # Zagnanado
    demande = tours[-2]
    assert demande.etat == "CHOIX_COMMUNE" and demande.phrases[0].id == "C01"
    assert set(demande.touches_valides) == set("0123456789")
    rep = texte(tours[-1])
    assert sess.commune == "Zagnanado"
    assert "Le transport depuis Zagnanado coûte environ huit cents francs le sac, c'est une estimation." in rep
    assert "Il vous resterait" in rep and "relevé le" in rep
    assert "prix du jour" not in rep


def test_touche2_autre_commune_garde_la_phrase_sans_transport():
    moteur = Moteur(services_reels(), voix_active=False)
    sess, tours = _offre_touche2(moteur, commune="0")
    rep = texte(tours[-1])
    assert sess.commune == "autre"
    assert "transport" not in rep and "relevé le" in rep


def test_commune_demandee_une_seule_fois_par_appel():
    moteur = Moteur(services_reels(), voix_active=False)
    sess, _ = _offre_touche2(moteur, commune="3")  # Bohicon
    t = lambda v: moteur.traiter(sess, Evenement(type="TOUCHE", valeur=v))  # noqa: E731
    t("2")
    for c in "15000#":
        tour = t(c)
    assert tour.etat == "MENU_PRINCIPAL" and "Le transport depuis Bohicon" in texte(tour)


def test_touche_commune_invalide_compte_une_erreur():
    moteur = Moteur(services_reels(), voix_active=False)
    sess, tours = _offre_touche2(moteur)
    assert tours[-1].etat == "CHOIX_COMMUNE"
    tour = moteur.traiter(sess, Evenement(type="TOUCHE", valeur="#"))
    assert sess.nb_erreurs == 1 and tour.etat == "CHOIX_COMMUNE"


def test_statut_verifie_ne_dit_plus_estimation(csv_temporaire):
    for ligne in TR.lire_couts():
        if ligne["commune"] == "Zagnanado":
            TR.modifier_cout(ligne["id"], {"statut": "verifie"}, "test", "now")
    moteur = Moteur(services_reels(), voix_active=False)
    _, tours = _offre_touche2(moteur, commune="7")
    rep = texte(tours[-1])
    assert "Le transport depuis Zagnanado coûte environ huit cents francs le sac." in rep
    assert "estimation" not in rep


def test_cout_manquant_pour_un_marche(csv_temporaire):
    lignes = [ligne for ligne in TR.lire_couts()
              if not (ligne["commune"] == "Zagnanado" and ligne["marche"] == HOUNDJRO)]
    TR.ecrire_couts(lignes)
    moteur = Moteur(services_reels(), voix_active=False)
    _, tours = _offre_touche2(moteur, commune="7")
    phrases = [p.texte for p in tours[-1].phrases]
    houndjro = next(p for p in phrases if p.startswith(f"À {HOUNDJRO}"))
    assert "transport" not in houndjro and "l'offre est" in houndjro
    assert any("Le transport depuis Zagnanado" in p for p in phrases if p.startswith(f"À {BOHICON}"))


def test_sans_tableau_pas_de_question_commune(csv_temporaire):
    csv_temporaire.unlink()
    moteur = Moteur(services_reels(), voix_active=False)
    _, tours = _offre_touche2(moteur)
    assert tours[-1].etat == "MENU_PRINCIPAL"  # verdict direct, comme avant


def test_services_fakes_inchanges():
    moteur = Moteur(services_fakes(), voix_active=False)
    _, tours = _offre_touche2(moteur)
    assert tours[-1].etat != "CHOIX_COMMUNE"


def test_touche1_prix_inchangee():
    moteur = Moteur(services_reels(), voix_active=False)
    sess = moteur.nouvelle_session("p")
    moteur.traiter(sess, Evenement(type="DECROCHE"))
    moteur.traiter(sess, Evenement(type="TOUCHE", valeur="1"))
    tour = moteur.traiter(sess, Evenement(type="TOUCHE", valeur="1"))
    assert "transport" not in texte(tour) and sess.commune is None


# ---------- touche 3 ----------
@pytest.mark.parametrize("phrase,attendu", [
    ("je suis à Zagnanado, on me propose 15000 le sac de 100 kilos de maïs blanc", "Zagnanado"),
    ("j'habite à Djidja, quel est le prix du soja", "Djidja"),
    ("depuis Za-Kpota on m'offre 150 francs le kilo de maïs blanc", "Za-Kpota"),
    ("le prix du maïs blanc à Bohicon", None),  # Bohicon ici est le MARCHÉ
    ("à Covè on m'offre 25500 le sac de haricot rouge", None),
])
def test_commune_extraite_seulement_apres_une_tournure_de_depart(phrase, attendu):
    assert TR.trouver_commune(phrase) == attendu


def test_touche3_commune_dite_pas_redemandee():
    services = services_reels()
    texte_q = "je suis à Zagnanado, on me propose 15000 francs le sac de 100 kilos de maïs blanc"
    compris = {"intention": "juger_offre", "produit": "mais", "variete": "blanc",
               "marche": None, "montant_offre": 15000, "unite_offre": "100kg"}
    services.question = lambda v: _fusionner(texte_q, compris)
    moteur = Moteur(services, voix_active=True)
    sess = moteur.nouvelle_session("v")
    moteur.traiter(sess, Evenement(type="DECROCHE"))
    moteur.traiter(sess, Evenement(type="TOUCHE", valeur="3"))
    tour = moteur.traiter(sess, Evenement(type="VOIX", valeur="x"))
    assert tour.etat == "MENU_PRINCIPAL"
    assert "Le transport depuis Zagnanado" in texte(tour)


def test_touche3_commune_non_dite_demandee():
    services = services_reels()
    texte_q = "on me propose 150 francs le kilo de maïs blanc"
    compris = {"intention": "juger_offre", "produit": "mais", "variete": "blanc",
               "marche": None, "montant_offre": 150, "unite_offre": "kg"}
    services.question = lambda v: _fusionner(texte_q, compris)
    moteur = Moteur(services, voix_active=True)
    sess = moteur.nouvelle_session("v")
    moteur.traiter(sess, Evenement(type="DECROCHE"))
    moteur.traiter(sess, Evenement(type="TOUCHE", valeur="3"))
    tour = moteur.traiter(sess, Evenement(type="VOIX", valeur="x"))
    assert tour.etat == "CHOIX_COMMUNE"
    tour = moteur.traiter(sess, Evenement(type="TOUCHE", valeur="4"))  # Covè
    assert "Le transport depuis Covè" in texte(tour)


def test_texte_c01_cite_les_9_communes():
    for nom in TR.COMMUNES:
        assert nom in T.TEXTES["C01"]


# ---------- dashboard / API ----------
class _FausseSession:
    def __init__(self):
        self.ajouts = []

    def add(self, obj):
        self.ajouts.append(obj)

    def commit(self):
        pass


def _client(role="validateur"):
    from app.api import admin
    from app.db.models import Utilisateur
    from app.db.session import get_session
    from app.main import app

    user = Utilisateur(id=1, email="membre@squadra8.test", nom_affiche="Membre",
                       role=role, actif=True, mot_de_passe_hash="x")
    fausse = _FausseSession()
    app.dependency_overrides[admin.current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: fausse
    return app, fausse


def test_api_transport_lister_modifier_verifier(csv_temporaire):
    app, fausse = _client()
    try:
        with TestClient(app) as client:
            lignes = client.get("/api/admin/transport").json()
            assert len(lignes) == 27
            cible = next(x for x in lignes if x["commune"] == "Zagnanado" and x["marche"] == BOHICON)
            r = client.put(f"/api/admin/transport/{cible['id']}",
                           json={"cout_sac_100kg": 1000, "statut": "verifie"})
            assert r.status_code == 200
            assert r.json()["statut"] == "verifie" and r.json()["modifie_par"] == "membre@squadra8.test"
            assert client.put("/api/admin/transport/999", json={"statut": "verifie"}).status_code == 404
            assert client.put(f"/api/admin/transport/{cible['id']}",
                              json={"statut": "faux"}).status_code == 422
    finally:
        app.dependency_overrides.clear()
    assert TR.cout_transport("Zagnanado", BOHICON) == {
        "cout_sac_100kg": 1000, "cout_kg": 10.0, "statut": "verifie",
        "mode": cible["mode"]}
    assert fausse.ajouts and fausse.ajouts[0].action == "transport_modification"


def test_api_transport_saisie_ne_peut_pas_modifier(csv_temporaire):
    app, _ = _client(role="saisie")
    try:
        with TestClient(app) as client:
            assert client.get("/api/admin/transport").status_code == 200
            assert client.put("/api/admin/transport/1", json={"statut": "verifie"}).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_api_transport_exige_connexion():
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/api/admin/transport").status_code in (401, 503)
