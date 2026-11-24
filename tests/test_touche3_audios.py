"""Tests du mapping G8 (sans audio, sans openpyxl, sans réseau)."""

from data.scripts.test_touche3_audios import (
    est_correct_g8,
    evaluer_ligne,
    formater_intention,
    intentions_acceptees,
    normaliser_marche,
    normaliser_produit,
)


def test_intentions_prix_et_offre():
    assert intentions_acceptees("prix") == frozenset({"prix"})
    assert intentions_acceptees("offre") == frozenset({"juger_offre"})
    assert est_correct_g8("prix", "prix")
    assert not est_correct_g8("prix", "juger_offre")
    assert est_correct_g8("offre", "juger_offre")
    assert not est_correct_g8("offre", "prix")


def test_hors_sujet_accepte_autre_et_inconnu():
    assert intentions_acceptees("hors_sujet") == frozenset({"autre", "inconnu"})
    assert intentions_acceptees("hors-sujet") == frozenset({"autre", "inconnu"})
    assert est_correct_g8("hors_sujet", "autre")
    assert est_correct_g8("hors_sujet", "inconnu")
    assert not est_correct_g8("hors_sujet", "prix")


def test_intention_vide_ou_inconnue_n_est_pas_juste_pour_un_prix():
    assert not est_correct_g8("prix", None)
    assert not est_correct_g8("prix", "")
    assert not est_correct_g8("prix", "inconnu")


def test_normaliser_produit_varietes_vers_codes():
    assert normaliser_produit("maïs") == "mais"
    assert normaliser_produit("Maïs Jaune") == "mais"
    assert normaliser_produit("maïs blanc") == "mais"
    assert normaliser_produit("haricot noir") == "haricot"
    assert normaliser_produit("Haricot rouge") == "haricot"
    assert normaliser_produit("soja") == "soja"
    assert normaliser_produit("mais") == "mais"
    assert normaliser_produit(None) is None
    assert normaliser_produit("  ") is None


def test_normaliser_marche_noms_fao_vers_codes():
    assert normaliser_marche("Bohicon") == "bohicon"
    assert normaliser_marche("Houndjro (Abomey)") == "abomey"
    assert normaliser_marche("Abomey") == "abomey"
    assert normaliser_marche("Azogotchébou (Covè)") == "cove"
    assert normaliser_marche("Covè") == "cove"
    assert normaliser_marche("cove") == "cove"
    assert normaliser_marche(None) is None
    assert normaliser_marche("") is None


def test_evaluer_ligne_g8_ignore_produit_et_marche():
    detail = {"intention": "prix", "produit": "mais", "marche": "bohicon"}
    # Variété et nom FAO plus précis que le schéma : G8 reste juste.
    v = evaluer_ligne("prix", "maïs jaune", "Houndjro (Abomey)", detail)
    assert v["correct"] is True
    assert v["produit_ok"] is True
    assert v["marche_ok"] is False  # attendu abomey, trouvé bohicon
    assert v["strict"] is False


def test_evaluer_ligne_slots_vides_non_penalises():
    detail = {"intention": "juger_offre", "produit": "soja", "marche": None}
    v = evaluer_ligne("offre", None, None, detail)
    assert v["correct"] is True
    assert v["produit_ok"] is None
    assert v["marche_ok"] is None
    assert v["strict"] is True


def test_evaluer_ligne_hors_sujet_inconnu():
    v = evaluer_ligne("hors_sujet", None, None, {"intention": "inconnu"})
    assert v["correct"] is True
    assert v["strict"] is True


def test_formater_intention():
    assert formater_intention(
        {"intention": "prix", "produit": "mais", "marche": "cove", "source": "regles"}
    ) == ("prix | mais | cove | regles")
    assert formater_intention({"intention": "inconnu"}) == "inconnu | - | - | -"
    assert formater_intention(None) == ""
