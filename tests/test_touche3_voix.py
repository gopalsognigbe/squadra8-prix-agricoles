"""Touche 3 branchée : question à voix haute → prix ou offre (fakes, sans réseau)."""

from __future__ import annotations

import pytest

from app.dialogue import question_voix as QV
from app.dialogue.moteur import Evenement, Moteur
from app.ia.regles import extraire_offre, trouver_variete
from app.ia.transcription import AudioTropLong
from tests.fakes import services_fakes


def texte(tour) -> str:
    return " ".join(p.texte for p in tour.phrases)


def compris(intention="prix", famille="mais", variete=None, marche=None,
            montant=None, unite=None, erreur=None) -> dict:
    return {"erreur": erreur, "texte": "…", "intention": intention, "famille": famille,
            "variete": variete, "marche": marche, "montant": montant, "unite": unite}


def appel_voix(reponse, *, voix_active=True, produit_touche="1"):
    """Décroche, choisit le produit, tape 3. reponse : dict ou callable."""
    question = reponse if callable(reponse) else (lambda v: reponse)
    moteur = Moteur(services_fakes(question=question), voix_active=voix_active)
    sess = moteur.nouvelle_session("t3")

    def jouer(type_, valeur=None):
        return moteur.traiter(sess, Evenement(type=type_, valeur=valeur))

    jouer("DECROCHE")
    jouer("TOUCHE", produit_touche)
    tour = jouer("TOUCHE", "3")
    return jouer, tour, sess


def verifier_regles_annonce(t: str) -> None:
    assert "relevé le" in t
    assert "aujourd'hui" not in t.casefold() and "prix du jour" not in t.casefold()
    assert "transport" not in t.casefold()


# ---------- menu ----------
def test_menu_annonce_touche3_active() -> None:
    jouer, tour, _ = appel_voix(compris())
    assert tour.etat == "QUESTION_VOIX" and tour.attente == "voix"
    assert "après le bip" in texte(tour)
    assert tour.delai_s == 8  # = AUDIO_MAX_S par défaut


def test_delai_voix_suit_audio_max_s() -> None:
    moteur = Moteur(services_fakes(question=lambda v: compris()), voix_active=True, delai_voix=12)
    sess = moteur.nouvelle_session("d")
    moteur.traiter(sess, Evenement(type="DECROCHE"))
    moteur.traiter(sess, Evenement(type="TOUCHE", valeur="1"))
    assert moteur.traiter(sess, Evenement(type="TOUCHE", valeur="3")).delai_s == 12


def test_desactivee_reste_bientot_disponible() -> None:
    moteur = Moteur(services_fakes(), voix_active=False)
    sess = moteur.nouvelle_session("x")
    moteur.traiter(sess, Evenement(type="DECROCHE"))
    menu = moteur.traiter(sess, Evenement(type="TOUCHE", valeur="1"))
    assert "bientôt disponible" in texte(menu)
    tour = moteur.traiter(sess, Evenement(type="TOUCHE", valeur="3"))
    assert "arrive bientôt" in texte(tour) and tour.etat == "MENU_PRINCIPAL"


def test_sans_ia_branchee_bientot_disponible() -> None:
    from app.dialogue.moteur import Services

    services = services_fakes()
    moteur = Moteur(Services(prix=services.prix, offre=services.offre), voix_active=True)
    sess = moteur.nouvelle_session("x")
    moteur.traiter(sess, Evenement(type="DECROCHE"))
    assert "bientôt disponible" in texte(moteur.traiter(sess, Evenement(type="TOUCHE", valeur="1")))
    assert "arrive bientôt" in texte(moteur.traiter(sess, Evenement(type="TOUCHE", valeur="3")))


# ---------- prix ----------
def test_prix_mais_jaune_bohicon_un_seul_marche() -> None:
    jouer, _, _ = appel_voix(compris(variete="jaune", marche="Bohicon"))
    tour = jouer("VOIX", "q.wav")
    t = texte(tour)
    assert tour.etat == "MENU_PRINCIPAL"
    assert "Maïs jaune" in t and "Bohicon" in t
    assert "Houndjro" not in t and "Azogotchébou" not in t
    assert "cent trente-sept" in t and "vingt-cinq octobre" in t
    verifier_regles_annonce(t)


def test_prix_couleur_manquante_on_demande() -> None:
    jouer, _, sess = appel_voix(compris(variete=None))
    tour = jouer("VOIX", "q.wav")
    assert tour.etat == "CHOIX_VARIETE"
    assert "maïs blanc, tapez 1" in texte(tour) and "maïs jaune, tapez 2" in texte(tour)
    tour = jouer("TOUCHE", "2")
    t = texte(tour)
    assert "Maïs jaune" in t
    assert "Bohicon" in t and "Houndjro (Abomey)" in t and "Azogotchébou (Covè)" in t
    assert sess.produit == "mais jaune"
    verifier_regles_annonce(t)


def test_haricot_sans_couleur_trois_choix_et_touche_invalide() -> None:
    jouer, _, _ = appel_voix(compris(famille="haricot"), produit_touche="3")
    tour = jouer("VOIX", "q.wav")
    assert tour.etat == "CHOIX_VARIETE" and tour.touches_valides == ["1", "2", "3"]
    assert "pas valide" in texte(jouer("TOUCHE", "9"))
    assert "Haricot rouge" in texte(jouer("TOUCHE", "3"))


def test_produit_absent_on_reprend_le_produit_choisi() -> None:
    jouer, _, _ = appel_voix(compris(famille=None), produit_touche="2")  # soja
    t = texte(jouer("VOIX", "q.wav"))
    assert "Soja" in t and "quatre cent sept" in t


def test_marche_sans_prix_recent_on_le_dit() -> None:
    jouer, _, _ = appel_voix(compris(famille="soja", marche="Azogotchébou (Covè)"))
    t = texte(jouer("VOIX", "q.wav"))
    assert "pas de prix récent pour ce produit sur ce marché" in t
    assert "Bohicon" in t  # les marchés qui ont un prix
    verifier_regles_annonce(t)


def test_touche_4_rejoue_la_reponse_vocale() -> None:
    jouer, _, _ = appel_voix(compris(variete="blanc"))
    rep = jouer("VOIX", "q.wav")
    assert [p.texte for p in jouer("TOUCHE", "4").phrases] == [p.texte for p in rep.phrases]


# ---------- offre ----------
def test_offre_au_kilo_jugee_au_marche_dit() -> None:
    jouer, _, _ = appel_voix(compris("juger_offre", variete="blanc",
                                     marche="Azogotchébou (Covè)", montant=125, unite="kg"))
    t = texte(jouer("VOIX", "q.wav"))
    assert "cent vingt-cinq francs le kilo" in t
    assert "Azogotchébou (Covè)" in t and "cent quarante" in t
    assert "en dessous" in t
    verifier_regles_annonce(t)


def test_offre_sac_de_cent_kilos_directe() -> None:
    jouer, _, _ = appel_voix(compris("juger_offre", variete="blanc", montant=12000, unite="100kg"))
    t = texte(jouer("VOIX", "q.wav"))
    assert "cent vingt francs le kilo" in t and "Bohicon" in t and "en dessous" in t


def test_offre_sac_poids_non_dit_on_demande() -> None:
    jouer, _, _ = appel_voix(compris("juger_offre", variete="blanc", montant=15000, unite="sac"))
    tour = jouer("VOIX", "q.wav")
    assert tour.etat == "CONFIRMER_SAC"
    assert "quinze mille francs le sac" in texte(tour) and "100 kilos, tapez 1" in texte(tour)
    t = texte(jouer("TOUCHE", "1"))
    assert "cent cinquante francs le kilo" in t and "au-dessus" in t


def test_offre_sac_autre_poids_on_tape_le_prix_pour_100_kilos() -> None:
    jouer, _, _ = appel_voix(compris("juger_offre", variete="blanc", montant=6000, unite="sac",
                                     marche="Bohicon"))
    jouer("VOIX", "q.wav")
    tour = jouer("TOUCHE", "2")
    assert tour.etat == "OFFRE_MONTANT" and "sac de 100 kilos" in texte(tour)


def test_offre_sans_montant_on_tape_le_prix_et_garde_le_marche() -> None:
    jouer, _, _ = appel_voix(compris("juger_offre", variete="blanc", marche="Azogotchébou (Covè)"))
    tour = jouer("VOIX", "q.wav")
    assert tour.etat == "OFFRE_MONTANT" and tour.attente == "montant"
    assert "pas bien compris le montant" in texte(tour)
    for c in "12000":
        jouer("TOUCHE", c)
    t = texte(jouer("TOUCHE", "#"))
    assert "Azogotchébou (Covè)" in t and "en dessous" in t


def test_offre_sans_couleur_on_demande_puis_on_juge() -> None:
    jouer, _, _ = appel_voix(compris("juger_offre", montant=130, unite="kg"))
    assert jouer("VOIX", "q.wav").etat == "CHOIX_VARIETE"
    t = texte(jouer("TOUCHE", "1"))
    assert "cent trente francs le kilo" in t and "en dessous" in t


# ---------- hors sujet et pannes ----------
@pytest.mark.parametrize("intention", ["autre", "inconnu"])
def test_hors_sujet_retour_menu(intention) -> None:
    jouer, _, _ = appel_voix(compris(intention))
    tour = jouer("VOIX", "q.wav")
    assert tour.etat == "MENU_PRINCIPAL"
    assert "pas compris" in texte(tour) and "maïs, du soja ou du haricot" in texte(tour)


def test_audio_trop_long_on_redemande_puis_fin() -> None:
    jouer, _, _ = appel_voix(compris(erreur="trop_long"))
    tour = jouer("VOIX", "q.wav")
    assert tour.etat == "QUESTION_VOIX" and "trop longue" in texte(tour) and not tour.fin
    jouer("VOIX", "q.wav")
    assert jouer("VOIX", "q.wav").fin


@pytest.mark.parametrize("erreur", ["transcription", "ia"])
def test_panne_repli_bientot_disponible(erreur) -> None:
    jouer, _, _ = appel_voix(compris(erreur=erreur))
    tour = jouer("VOIX", "q.wav")
    assert tour.etat == "MENU_PRINCIPAL" and "arrive bientôt" in texte(tour)


def test_exception_du_service_repli_propre() -> None:
    def casse(_):
        raise RuntimeError("panne")

    jouer, _, _ = appel_voix(casse)
    tour = jouer("VOIX", "q.wav")
    assert tour.etat == "MENU_PRINCIPAL" and "arrive bientôt" in texte(tour)


def test_voix_hors_question_est_une_erreur() -> None:
    jouer, _, _ = appel_voix(compris())
    jouer("TOUCHE", "4")  # retour au menu
    assert "pas valide" in texte(jouer("VOIX", "q.wav"))


# ---------- règles de lecture de la phrase ----------
@pytest.mark.parametrize("phrase, attendu", [
    ("On me propose 12 000 francs le sac de Maïs à Bohicon. C'est bon ?",
     {"montant": 12000, "unite": "sac"}),
    ("Un acheteur me propose 125 francs le kilo de maïs, c'est bon.",
     {"montant": 125, "unite": "kg"}),
    ("15.000 francs le sac de 100 kilos de soja", {"montant": 15000, "unite": "100kg"}),
    ("On me donne 130 francs, c'est correct ?", {"montant": 130, "unite": None}),
    ("Le prix du maïs à Bohicon", {"montant": None, "unite": None}),
    ("12000 ou 13000 francs le kilo", {"montant": None, "unite": "kg"}),
])
def test_extraire_offre(phrase, attendu) -> None:
    assert extraire_offre(phrase) == attendu


@pytest.mark.parametrize("phrase, famille, attendu", [
    ("le maïs jaune à Covè", "mais", "jaune"),
    ("haricot rouge", "haricot", "rouge"),
    ("le prix du maïs", "mais", None),
    ("maïs blanc ou jaune", "mais", None),  # ambigu : on demande
    ("soja blanc", "soja", None),
])
def test_trouver_variete(phrase, famille, attendu) -> None:
    assert trouver_variete(phrase, famille) == attendu


# ---------- analyser_question (chaîne réelle, réseau remplacé) ----------
def test_analyser_trop_long(monkeypatch) -> None:
    def trop_long(_, **k):
        raise AudioTropLong("10.7 s")

    monkeypatch.setattr(QV, "transcrire", trop_long)
    assert QV.analyser_question("q.wav")["erreur"] == "trop_long"


def test_analyser_echec_transcription(monkeypatch) -> None:
    def panne(_, **k):
        raise RuntimeError("réseau")

    monkeypatch.setattr(QV, "transcrire", panne)
    assert QV.analyser_question("q.wav")["erreur"] == "transcription"


def test_analyser_vide(monkeypatch) -> None:
    monkeypatch.setattr(QV, "transcrire", lambda _, **k: "  ")
    assert QV.analyser_question("q.wav")["erreur"] == "vide"


def test_analyser_noms_fao_exacts(monkeypatch) -> None:
    monkeypatch.setattr(QV, "comprendre", lambda t, **k: {
        "intention": "juger_offre", "produit": "mais", "marche": "abomey", "confiance": 0.9})
    r = QV.analyser_question("texte:À Abomey on m'offre 11 000 francs le sac de maïs jaune")
    assert r["erreur"] is None and r["marche"] == "Houndjro (Abomey)"
    assert r["famille"] == "mais" and r["variete"] == "jaune"
    assert r["montant"] == 11000 and r["unite"] == "sac"


def test_analyser_produit_inconnu_et_ia_en_panne(monkeypatch) -> None:
    monkeypatch.setattr(QV, "comprendre", lambda t, **k: {
        "intention": "prix", "produit": "igname", "marche": "parakou"})
    r = QV.analyser_question("texte:prix de l'igname à Parakou")
    assert r["famille"] is None and r["marche"] is None

    def casse(_, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(QV, "comprendre", casse)
    assert QV.analyser_question("texte:bonjour")["erreur"] == "ia"


# ---------- précisions de Gopal : ville ↔ marché, couleur, montant en lettres ----------
from app.ia.intention import IntentionResult  # noqa: E402
from app.ia.regles import (  # noqa: E402
    VILLE_DU_MARCHE,
    comprendre_par_regles,
    montant_en_francs,
    resoudre_ville_marche,
)


@pytest.mark.parametrize("dit, fao", [
    ("Abomey", "Houndjro (Abomey)"), ("abomé", "Houndjro (Abomey)"),
    ("Houndjro", "Houndjro (Abomey)"), ("houndjoro", "Houndjro (Abomey)"),
    ("abomey", "Houndjro (Abomey)"), ("Houndjro (Abomey)", "Houndjro (Abomey)"),
    ("Covè", "Azogotchébou (Covè)"), ("cove", "Azogotchébou (Covè)"),
    ("kove", "Azogotchébou (Covè)"), ("A Covet, un acheteur", "Azogotchébou (Covè)"),
    ("Azogotchébou", "Azogotchébou (Covè)"), ("azogotchebou", "Azogotchébou (Covè)"),
    ("azogotcheboux", "Azogotchébou (Covè)"),
    ("Bohicon", "Bohicon"), ("bohikon", "Bohicon"),
])
def test_ville_vers_marche_fao(dit, fao) -> None:
    assert resoudre_ville_marche(dit) == fao


@pytest.mark.parametrize("dit", ["Parakou", "Cotonou", "", None, "Abomey ou Bohicon"])
def test_ville_inconnue_ou_ambigue(dit) -> None:
    assert resoudre_ville_marche(dit) is None


def test_marche_vers_ville_dans_les_deux_sens() -> None:
    for fao, ville in VILLE_DU_MARCHE.items():
        assert resoudre_ville_marche(ville) == fao
        assert resoudre_ville_marche(fao) == fao
        assert ville in fao  # l'annonce dit « Houndjro (Abomey) »


@pytest.mark.parametrize("phrase, montant", [
    ("quinze mille francs", 15000),
    ("15 000 francs", 15000),
    ("15000 F", 15000),
    ("15 mille francs", 15000),
    ("vingt-cinq mille cinq cents francs", 25500),
    ("onze mille francs le sac", 11000),
    ("cent vingt-cinq francs le kilo", 125),
    ("trois cent quatre-vingts francs", 380),
    ("quatre-vingt-dix mille francs", 90000),
    ("soixante-dix mille francs", 70000),
    ("vingt et un mille francs", 21000),
    ("un acheteur me propose douze mille", 12000),  # « un » n'est pas un montant
    ("le sac de 100 kilos à 15 000", 15000),  # le poids n'est pas un montant
    ("le prix du maïs", None),
    ("douze mille ou treize mille", None),  # deux montants : on demande
])
def test_montant_en_lettres_ou_chiffres(phrase, montant) -> None:
    assert montant_en_francs(phrase) == montant


@pytest.mark.parametrize("phrase, attendu", [
    ("quinze mille francs le sac", {"montant": 15000, "unite": "sac"}),
    ("douze mille francs le sac de cent kilos", {"montant": 12000, "unite": "100kg"}),
    ("douze mille le sac de 50 kilos", {"montant": 12000, "unite": "sac"}),
])
def test_extraire_offre_en_lettres(phrase, attendu) -> None:
    assert extraire_offre(phrase) == attendu


@pytest.mark.parametrize("phrase, famille, variete", [
    ("haricot noir", "haricot", "noir"),
    ("haricots blancs", "haricot", "blanc"),
    ("maïs blanc", "mais", "blanc"),
    ("le haricot", "haricot", None),
])
def test_couleurs(phrase, famille, variete) -> None:
    assert trouver_variete(phrase, famille) == variete


def test_regles_de_secours_completes() -> None:
    r = comprendre_par_regles(
        "à Houndjoro on me propose vingt-cinq mille cinq cents francs le sac de haricot rouge")
    assert r["intention"] == "juger_offre" and r["produit"] == "haricot"
    assert r["marche"] == "abomey" and r["variete"] == "rouge"
    assert r["montant_offre"] == 25500 and r["unite_offre"] == "sac"
    p = comprendre_par_regles("le prix du maïs jaune à Kove")
    assert p["marche"] == "cove" and p["variete"] == "jaune" and p["montant_offre"] is None


def test_schema_ia_tolerant() -> None:
    r = IntentionResult.model_validate({
        "intention": "juger_offre", "produit": "mais", "marche": "abomey",
        "variete": "Jaune", "montant_offre": "15 000", "unite_offre": "SAC"})
    assert (r.variete, r.montant_offre, r.unite_offre) == ("jaune", 15000, "sac")
    r = IntentionResult.model_validate({
        "intention": "prix", "variete": "vert", "montant_offre": "beaucoup", "unite_offre": "tonne"})
    assert (r.variete, r.montant_offre, r.unite_offre) == (None, None, None)


def _ia(monkeypatch, **reponse) -> None:
    base = {"intention": "juger_offre", "produit": "mais", "marche": None, "confiance": 0.9,
            "variete": None, "montant_offre": None, "unite_offre": None}
    base.update(reponse)
    monkeypatch.setattr(QV, "comprendre", lambda t, **k: base)


def test_ia_et_regle_d_accord(monkeypatch) -> None:
    _ia(monkeypatch, marche="Abomey", variete="jaune", montant_offre=15000, unite_offre="sac")
    r = QV.analyser_question("texte:à Abomé on me propose quinze mille francs le sac de maïs jaune")
    assert r["marche"] == "Houndjro (Abomey)" and r["variete"] == "jaune"
    assert r["montant"] == 15000 and r["unite"] == "sac"


def test_code_ia_cove_et_montant_en_chiffres(monkeypatch) -> None:
    _ia(monkeypatch, montant_offre=15000, unite_offre="sac", marche="cove")
    r = QV.analyser_question("texte:on me propose 15 000 balles pour le sac de maïs blanc")
    assert r["montant"] == 15000 and r["marche"] == "Azogotchébou (Covè)"


def test_montant_ia_sans_nombre_dans_la_phrase_refuse(monkeypatch) -> None:
    _ia(monkeypatch, montant_offre=15000)
    r = QV.analyser_question("texte:un acheteur veut mon maïs blanc, c'est bon ?")
    assert r["montant"] is None


def test_desaccord_ia_regle_on_ne_devine_pas(monkeypatch) -> None:
    _ia(monkeypatch, montant_offre=50000, variete="blanc", marche="bohicon")
    r = QV.analyser_question("texte:à Covè on me propose quinze mille le sac de maïs jaune")
    assert r["montant"] is None and r["variete"] is None and r["marche"] is None


def test_regle_seule_quand_ia_tombe(monkeypatch) -> None:
    monkeypatch.setattr(QV, "comprendre", lambda t, **k: comprendre_par_regles(t))
    r = QV.analyser_question(
        "texte:à Kove on m'offre vingt-cinq mille cinq cents francs le sac de haricot noir")
    assert r["intention"] == "juger_offre" and r["famille"] == "haricot"
    assert r["variete"] == "noir" and r["marche"] == "Azogotchébou (Covè)"
    assert r["montant"] == 25500 and r["unite"] == "sac"


def test_parcours_complet_abome_quinze_mille_le_sac(monkeypatch) -> None:
    monkeypatch.setattr(QV, "comprendre", lambda t, **k: comprendre_par_regles(t))
    jouer, _, _ = appel_voix(QV.analyser_question)
    tour = jouer("VOIX", "texte:à Abomé on me propose quinze mille francs le sac de maïs jaune")
    assert tour.etat == "CONFIRMER_SAC" and "quinze mille francs le sac" in texte(tour)
    t = texte(jouer("TOUCHE", "1"))
    assert "cent cinquante francs le kilo" in t and "Houndjro (Abomey)" in t
    verifier_regles_annonce(t)


def test_parcours_complet_couleur_absente_on_demande(monkeypatch) -> None:
    monkeypatch.setattr(QV, "comprendre", lambda t, **k: comprendre_par_regles(t))
    jouer, _, _ = appel_voix(QV.analyser_question, produit_touche="2")
    tour = jouer("VOIX", "texte:quel est le prix du haricot à Houndjro")
    assert tour.etat == "CHOIX_VARIETE" and "haricot noir, tapez 2" in texte(tour)
    t = texte(jouer("TOUCHE", "2"))
    assert "Haricot noir" in t
