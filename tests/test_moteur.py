"""Tests du moteur de dialogue et de l'adaptateur source FAO."""

from __future__ import annotations

from pathlib import Path

from app.dialogue.moteur import Evenement, Moteur
from app.dialogue.services_prix import services_reels
from app.services.source_prix import get_source_prix
from tests.fakes import FakeJournal, services_fakes


def texte(tour) -> str:
    return " ".join(p.texte for p in tour.phrases)


def nouvel_appel(**kw):
    fakes_kw = kw.pop("fakes", {})
    moteur = Moteur(services_fakes(**fakes_kw), **kw)
    sess = moteur.nouvelle_session("test")

    def jouer(type_: str, valeur: str | None = None):
        return moteur.traiter(sess, Evenement(type=type_, valeur=valeur))

    return jouer


def au_menu(**kw):
    """Décroche au menu principal, produit = maïs (sans annoncer les prix)."""
    fakes_kw = kw.pop("fakes", {})
    moteur = Moteur(services_fakes(**fakes_kw), **kw)
    sess = moteur.nouvelle_session("test")

    def jouer(type_: str, valeur: str | None = None):
        return moteur.traiter(sess, Evenement(type=type_, valeur=valeur))

    jouer("DECROCHE")
    sess.produit = "mais"
    return jouer


def test_accueil() -> None:
    jouer = nouvel_appel()
    tour = jouer("DECROCHE")
    assert tour.etat == "MENU_PRINCIPAL"
    assert "service des prix agricoles" in texte(tour)
    assert "prix sur 3 marchés" in texte(tour)
    assert "juger l'offre" in texte(tour)
    assert tour.attente == "touche"
    assert tour.touches_valides == ["1", "2", "3", "4"]


def test_menu_trois_marches_pas_aujourdhui() -> None:
    jouer = nouvel_appel()
    menu = jouer("DECROCHE")
    t = texte(menu)
    assert "3 marchés" in t
    assert "aujourd'hui" not in t.casefold()
    assert "bientôt disponible" in t  # voix désactivée par défaut


def test_prix_demande_le_produit_puis_annonce() -> None:
    jouer = nouvel_appel()
    jouer("DECROCHE")
    choix = jouer("TOUCHE", "1")
    assert choix.etat == "CHOIX_PRODUIT" and "maïs" in texte(choix).casefold()
    tour = jouer("TOUCHE", "1")  # maïs
    assert "Bohicon" in texte(tour) and tour.etat == "MENU_PRINCIPAL"


def test_parcours_nominal() -> None:
    jouer = au_menu()
    tour = jouer("TOUCHE", "1")
    t = texte(tour)
    assert tour.etat == "MENU_PRINCIPAL"
    assert "Bohicon" in t
    assert "Houndjro (Abomey)" in t
    assert "Azogotchébou (Covè)" in t
    assert "Zogbodomey" not in t and "Hlanxi" not in t
    # 137,36 F → round → 137 F → « cent trente-sept »
    assert "cent trente-sept" in t
    assert "vingt-cinq octobre" in t
    assert "relevé le" in t
    assert "aujourd'hui" not in t.casefold()
    assert "repère" in t and "Source" in t
    # 100 kg : vers_100kg(137.36) = 13736
    assert "treize mille sept cent trente-six" in t


def test_avertissement_dit_une_seule_fois() -> None:
    jouer = au_menu()
    assert "repère" in texte(jouer("TOUCHE", "1"))
    assert "repère" not in texte(jouer("TOUCHE", "1"))


def test_touche_invalide_puis_fin() -> None:
    jouer = nouvel_appel()
    jouer("DECROCHE")
    tour = jouer("TOUCHE", "9")
    assert tour.etat == "MENU_PRINCIPAL" and "pas valide" in texte(tour) and not tour.fin
    jouer("TOUCHE", "9")
    assert jouer("TOUCHE", "9").fin


def test_silence_repete_puis_fin() -> None:
    jouer = nouvel_appel()
    jouer("DECROCHE")
    tour = jouer("SILENCE")
    assert "rien entendu" in texte(tour) and not tour.fin
    assert jouer("SILENCE").fin


def test_touche_4_rejoue_mot_pour_mot() -> None:
    jouer = au_menu()
    prix = jouer("TOUCHE", "1")
    rejoue = jouer("TOUCHE", "4")
    assert [p.texte for p in rejoue.phrases] == [p.texte for p in prix.phrases]


def test_offre_douze_mille_en_dessous() -> None:
    jouer = au_menu()
    tour = jouer("TOUCHE", "2")
    assert tour.attente == "montant"
    for c in "12000":
        jouer("TOUCHE", c)
    tour = jouer("TOUCHE", "#")
    t = texte(tour)
    assert tour.etat == "MENU_PRINCIPAL"
    assert "cent vingt" in t and "cent trente-sept" in t
    assert "en dessous" in t
    assert "vingt-cinq octobre" in t
    assert "aujourd'hui" not in t.casefold()


def test_montant_vide_refuse() -> None:
    jouer = au_menu()
    jouer("TOUCHE", "2")
    tour = jouer("TOUCHE", "#")
    assert "pas valide" in texte(tour) and tour.attente == "montant"


def test_montant_trop_long_refuse() -> None:
    jouer = au_menu()
    jouer("TOUCHE", "2")
    for c in "12345678":
        tour = jouer("TOUCHE", c)
    assert "pas valide" in texte(tour)


def test_prix_absent() -> None:
    jouer = au_menu(fakes={"sans_prix": True})
    tour = jouer("TOUCHE", "1")
    assert "pas de prix récent" in texte(tour)
    assert "4" in tour.touches_valides


def test_voix_desactivee_par_defaut() -> None:
    jouer = nouvel_appel()  # voix_active=False par défaut
    menu = jouer("DECROCHE")
    assert "bientôt disponible" in texte(menu)
    tour = jouer("TOUCHE", "3")
    assert "arrive bientôt" in texte(tour) and tour.etat == "MENU_PRINCIPAL"


def test_voix_active() -> None:
    jouer = au_menu(voix_active=True)
    tour = jouer("TOUCHE", "3")
    assert tour.etat == "QUESTION_VOIX" and tour.attente == "voix"


def test_raccroche_termine() -> None:
    jouer = au_menu()
    assert jouer("RACCROCHE").fin


def test_journal_enregistre_les_evenements() -> None:
    journal = FakeJournal()
    jouer = nouvel_appel(fakes={"journal": journal})
    jouer("DECROCHE")
    jouer("TOUCHE", "1")
    assert ("test", "ACCUEIL", "DECROCHE:") in journal.lignes
    assert len(journal.lignes) == 2


def test_moteur_independant_du_canal() -> None:
    code = Path("app/dialogue/moteur.py").read_text(encoding="utf-8")
    imports = [
        ligne.lower()
        for ligne in code.splitlines()
        if ligne.startswith(("import ", "from "))
    ]
    for interdit in ("twilio", "fastapi", "app.api"):
        assert not any(interdit in ligne for ligne in imports)


def test_console_n_importe_pas_tests_fakes() -> None:
    code = Path("app/dialogue/console.py").read_text(encoding="utf-8")
    assert "tests.fakes" not in code
    assert "services_reels" in code


def test_adaptateur_prix_mais_trois_marches_officiels() -> None:
    get_source_prix.cache_clear()
    liste = services_reels().prix("mais")
    marches = [p["marche"] for p in liste]
    assert marches == [
        "Bohicon",
        "Houndjro (Abomey)",
        "Azogotchébou (Covè)",
    ]
    assert "Zogbodomey" not in marches and "Hlanxi" not in marches
    assert "Abomey" not in marches  # pas le marché INStaD


def test_moteur_avec_source_reelle_date_releve() -> None:
    get_source_prix.cache_clear()
    moteur = Moteur(services_reels(), voix_active=False)
    sess = moteur.nouvelle_session("csv")
    moteur.traiter(sess, Evenement(type="DECROCHE"))
    moteur.traiter(sess, Evenement(type="TOUCHE", valeur="1"))  # prix → produit
    tour = moteur.traiter(sess, Evenement(type="TOUCHE", valeur="1"))  # maïs → prix
    t = texte(tour)
    assert "relevé le vingt-cinq octobre" in t  # Bohicon
    assert "aujourd'hui" not in t.casefold()
    assert "Bohicon" in t
    assert "Houndjro (Abomey)" in t
    # Anomalie Houndjro 173,63 écartée → 128,57 relevé le 19 octobre
    assert "dix-neuf octobre" in t
