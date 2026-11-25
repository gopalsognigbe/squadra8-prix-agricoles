"""Touche 3 : le marché dit dans la question est gardé après le choix de variété.

Signalé : « le prix du haricot à Covè » → choix de la variété → le service
doit donner seulement Azogotchébou (Covè), pas les 3 marchés.
Sans clé : comprendre() est remplacé par une réponse factice (ou par les règles).
"""
import pytest

from app.dialogue import question_voix
from app.dialogue.moteur import Evenement, Moteur, Services
from app.dialogue.question_voix import PREFIXE_TEXTE, analyser_question
from app.ia.intention import comprendre_par_regles
from app.services.calculs import juger_offre

MARCHES = ["Bohicon", "Houndjro (Abomey)", "Azogotchébou (Covè)"]
PRIX_KG = {"Bohicon": 600.0, "Houndjro (Abomey)": 620.0, "Azogotchébou (Covè)": 650.0}


def _liste(produit):
    return [{"marche": m, "prix_fcfa": PRIX_KG[m], "prix_kg": PRIX_KG[m],
             "prix_100kg": PRIX_KG[m] * 100, "unite": "Kilogramme", "type_prix": "detail",
             "date_releve": "2026-10-28", "source": "test"} for m in MARCHES]


def _services(offres_vues):
    def offre(produit, montant_sac, marche=None):
        offres_vues.append((produit, montant_sac, marche))
        liste = _liste(produit)
        ref = next((p for p in liste if p["marche"] == marche), liste[0])
        offre_kg = float(montant_sac) / 100.0
        return {"offre_kg": offre_kg, "reference_kg": ref["prix_kg"], "marche": ref["marche"],
                "date_releve": ref["date_releve"], **juger_offre(offre_kg, ref["prix_kg"])}

    return Services(prix=_liste, offre=offre, question=analyser_question)


@pytest.fixture
def ia(monkeypatch):
    """Réponse factice de l'IA (sans clé Groq) ; panne=True → règles de secours seules."""
    reponse = {}

    def faux_comprendre(texte, echeance=None):
        if reponse.get("panne"):  # Groq et Gemini indisponibles : repli sur les règles
            return comprendre_par_regles(texte)
        return {"intention": "prix", "produit": None, "variete": None, "marche": None,
                "montant_offre": None, "unite_offre": None, **reponse}

    monkeypatch.setattr(question_voix, "comprendre", faux_comprendre)
    return reponse


def _appel(phrase, touches_apres):
    offres = []
    moteur = Moteur(_services(offres), voix_active=True)
    sess = moteur.nouvelle_session("test")
    moteur.traiter(sess, Evenement(type="DECROCHE"))
    moteur.traiter(sess, Evenement(type="TOUCHE", valeur="2"))  # soja (n'importe)
    moteur.traiter(sess, Evenement(type="TOUCHE", valeur="3"))  # question à voix haute
    tours = [moteur.traiter(sess, Evenement(type="VOIX", valeur=PREFIXE_TEXTE + phrase))]
    for t in touches_apres:
        tours.append(moteur.traiter(sess, Evenement(type="TOUCHE", valeur=t)))
    return tours, offres


def _marches_annonces(tour):
    textes = " ".join(p.texte for p in tour.phrases)
    return [m for m in MARCHES if f"{m} :" in textes]


@pytest.mark.parametrize("variete_touche", ["1", "2", "3"])
def test_haricot_cove_seulement_azogotchebou(ia, variete_touche):
    ia.update(produit="haricot", marche="cove")
    tours, _ = _appel("le prix du haricot à Covè", [variete_touche])
    assert tours[0].etat == "CHOIX_VARIETE"
    assert _marches_annonces(tours[-1]) == ["Azogotchébou (Covè)"]


def test_mais_abomey_seulement_houndjro(ia):
    ia.update(produit="mais", marche="abomey")
    tours, _ = _appel("le prix du maïs à Abomey", ["2"])
    assert tours[0].etat == "CHOIX_VARIETE"
    assert _marches_annonces(tours[-1]) == ["Houndjro (Abomey)"]


def test_marche_par_les_regles_si_ia_ne_le_donne_pas(ia):
    ia.update(produit="haricot", marche=None)
    tours, _ = _appel("le prix du haricot à Covè", ["1"])
    assert _marches_annonces(tours[-1]) == ["Azogotchébou (Covè)"]


def test_marche_garde_si_ia_en_panne(ia):
    ia.update(panne=True)
    tours, _ = _appel("le prix du haricot à Covè", ["3"])
    assert tours[0].etat == "CHOIX_VARIETE"
    assert _marches_annonces(tours[-1]) == ["Azogotchébou (Covè)"]


def test_sans_marche_les_trois_marches(ia):
    ia.update(produit="haricot")
    tours, _ = _appel("le prix du haricot", ["1"])
    assert _marches_annonces(tours[-1]) == MARCHES


def test_offre_sac_avec_marche_apres_variete(ia):
    ia.update(intention="juger_offre", produit="haricot", marche="cove",
              montant_offre=60000, unite_offre="sac")
    tours, offres = _appel("on me propose soixante mille le sac de haricot à Covè", ["1", "1"])
    assert [t.etat for t in tours[:2]] == ["CHOIX_VARIETE", "CONFIRMER_SAC"]
    assert offres == [("haricot blanc", 60000, "Azogotchébou (Covè)")]
    assert "Azogotchébou (Covè)" in " ".join(p.texte for p in tours[-1].phrases)


def test_offre_sac_avec_marche_montant_retape(ia):
    ia.update(intention="juger_offre", produit="haricot", marche="abomey",
              montant_offre=60000, unite_offre="sac")
    # CONFIRMER_SAC → 2 (autre sac) → montant au clavier → #
    tours, offres = _appel("soixante mille le sac de haricot à Abomey",
                           ["3", "2", "5", "0", "0", "0", "0", "#"])
    assert offres and offres[-1][2] == "Houndjro (Abomey)"
