"""Touche 3, incrément 2 : montant sans unité, règles d'offre, 429 Groq, budget < 6 s."""

from __future__ import annotations

import time

import httpx
import openai
import pytest

from app.config import get_settings
from app.dialogue import question_voix as QV
from app.dialogue.moteur import Evenement, Moteur
from app.ia import delais
from app.ia import intention as I
from app.ia import transcription as TR
from app.ia.regles import comprendre_par_regles
from tests.fakes import services_fakes


@pytest.fixture(autouse=True)
def _reglages_propres(monkeypatch):
    for cle in ("GROQ_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "IA_DELAI_MAX_S"):
        monkeypatch.delenv(cle, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def texte(tour) -> str:
    return " ".join(p.texte for p in tour.phrases)


def appel_regles(monkeypatch, produit_touche="2"):
    """Vraie analyse (règles de secours à la place de l'IA) + moteur avec fakes."""
    monkeypatch.setattr(QV, "comprendre", lambda t, **k: comprendre_par_regles(t))
    moteur = Moteur(services_fakes(question=QV.analyser_question), voix_active=True)
    sess = moteur.nouvelle_session("i2")

    def jouer(type_, valeur=None):
        return moteur.traiter(sess, Evenement(type=type_, valeur=valeur))

    jouer("DECROCHE")
    jouer("TOUCHE", produit_touche)
    jouer("TOUCHE", "3")
    return jouer


QUINZE_MILLE = "texte:on me propose quinze mille pour le soja à Bohicon c'est bon ?"


# ---------- 1. bug « quinze mille » sans unité ----------
def test_bug_quinze_mille_soja_analyse(monkeypatch) -> None:
    monkeypatch.setattr(QV, "comprendre", lambda t, **k: comprendre_par_regles(t))
    r = QV.analyser_question(QUINZE_MILLE)
    assert r["intention"] == "juger_offre" and r["famille"] == "soja"
    assert r["montant"] == 15000 and r["unite"] is None and r["marche"] == "Bohicon"


def test_bug_quinze_mille_on_demande_l_unite(monkeypatch) -> None:
    jouer = appel_regles(monkeypatch)
    tour = jouer("VOIX", QUINZE_MILLE)
    t = texte(tour)
    assert tour.etat == "CHOISIR_UNITE" and tour.touches_valides == ["1", "2", "3"]
    assert "L'acheteur propose quinze mille francs." in t
    assert "pas bien compris le montant" not in t
    assert "prix d'un kilo, tapez 1" in t and "sac de 100 kilos, tapez 2" in t


def test_quinze_mille_le_sac_de_100_kilos(monkeypatch) -> None:
    jouer = appel_regles(monkeypatch)
    jouer("VOIX", QUINZE_MILLE)
    t = texte(jouer("TOUCHE", "2"))
    assert "cent cinquante francs le kilo" in t and "Bohicon" in t and "relevé le" in t
    assert "en dessous" in t  # soja de test : 407 F le kilo


def test_quinze_mille_le_kilo(monkeypatch) -> None:
    jouer = appel_regles(monkeypatch)
    jouer("VOIX", QUINZE_MILLE)
    t = texte(jouer("TOUCHE", "1"))
    assert "quinze mille francs le kilo" in t and "au-dessus" in t


def test_quinze_mille_autre_sac_on_tape(monkeypatch) -> None:
    jouer = appel_regles(monkeypatch)
    jouer("VOIX", QUINZE_MILLE)
    tour = jouer("TOUCHE", "3")
    assert tour.etat == "OFFRE_MONTANT" and "sac de 100 kilos" in texte(tour)


def test_choisir_unite_touche_invalide(monkeypatch) -> None:
    jouer = appel_regles(monkeypatch)
    jouer("VOIX", QUINZE_MILLE)
    tour = jouer("TOUCHE", "9")
    assert "pas valide" in texte(tour) and tour.etat == "CHOISIR_UNITE"


@pytest.mark.parametrize("phrase, produit_touche, montant", [
    ("un acheteur me donne 15 000 pour mon soja", "2", "quinze mille"),
    ("à Covè on m'offre vingt-cinq mille cinq cents pour le haricot rouge, je vends ou pas ?",
     "3", "vingt-cinq mille cinq cents"),
    ("le commerçant dit 12000 pour mon maïs jaune, c'est bien ?", "1", "douze mille"),
])
def test_variantes_sans_unite(monkeypatch, phrase, produit_touche, montant) -> None:
    jouer = appel_regles(monkeypatch, produit_touche)
    tour = jouer("VOIX", "texte:" + phrase)
    assert tour.etat == "CHOISIR_UNITE"
    assert f"L'acheteur propose {montant} francs." in texte(tour)


def test_unite_de_l_ia_ignoree_sans_mot_d_unite(monkeypatch) -> None:
    monkeypatch.setattr(QV, "comprendre", lambda t, **k: {
        "intention": "juger_offre", "produit": "soja", "marche": "bohicon",
        "variete": None, "montant_offre": 15000, "unite_offre": "sac"})
    r = QV.analyser_question(QUINZE_MILLE)
    assert r["montant"] == 15000 and r["unite"] is None  # l'IA ne choisit pas l'unité


# ---------- 2. règles d'offre renforcées (Q12, Q16) ----------
@pytest.mark.parametrize("phrase", [
    "À Abomey, on m'offre onze mille francs le sac de maïs, je vends ou pas ?",  # Q12
    "Un commerçant me propose soixante mille francs pour mon sac de haricot à Bohicon, c'est bien ?",  # Q16
    "Abomey, onze mille francs pour le sac de maïs",  # Q12 mal transcrit, sans verbe
    "le commerçant dit soixante mille pour mon haricot",
    "un acheteur veut mon maïs, c'est bien ?",
    "on m'a offert 125 francs le kilo",
    "quinze mille pour le soja",
])
def test_regles_offre(phrase) -> None:
    assert comprendre_par_regles(phrase)["intention"] == "juger_offre"


@pytest.mark.parametrize("phrase", [
    "Allô, le soja à Houndjro, il est à combien ?",  # Q27
    "quel est le prix du maïs à Bohicon",
    "combien coûte le sac de 100 kilos de maïs à Covè",  # 100 kilos = poids, pas un montant
])
def test_regles_prix_restent_prix(phrase) -> None:
    assert comprendre_par_regles(phrase)["intention"] == "prix"


@pytest.mark.parametrize("phrase", [
    "Quelle est la capitale du Burkina Faso ?",
    "Qui a gagné le match des Écureuils hier soir ?",
    "Je dois voir le docteur, comment je prends rendez-vous ?",
    "Peux-tu me donner une recette de sauce gombo ?",
    "Peux-tu me raconter une histoire pour les enfants ?",
])
def test_hors_sujet_reste_hors_sujet(phrase) -> None:
    assert comprendre_par_regles(phrase)["intention"] in ("autre", "inconnu")


# ---------- 3. 429 : attente et réessai borné ----------
def test_attente_429() -> None:
    assert delais.attente_429({"retry-after": "0.4"}) == 0.4
    assert delais.attente_429({"Retry-After": "1"}) == 1.0
    assert delais.attente_429({}) == delais.ATTENTE_429_DEFAUT_S
    assert delais.attente_429({"retry-after": "demain"}) == delais.ATTENTE_429_DEFAUT_S
    assert delais.attente_429(None) == delais.ATTENTE_429_DEFAUT_S


def test_reessai_possible_borne() -> None:
    loin = time.monotonic() + 5.0
    assert delais.reessai_possible(0.75, loin)
    assert not delais.reessai_possible(3.0, loin)  # Retry-After trop long : repli
    assert not delais.reessai_possible(0.75, time.monotonic() + 1.0)  # plus de budget


def _erreur_http(code: int, entetes: dict | None = None) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://api.groq.com/x")
    rep = httpx.Response(code, request=req, headers=entetes or {})
    return httpx.HTTPStatusError(f"{code}", request=req, response=rep)


@pytest.fixture
def groq_actif(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    get_settings.cache_clear()
    attentes: list[float] = []
    monkeypatch.setattr(TR.time, "sleep", attentes.append)
    return attentes


def test_transcription_429_puis_ok(monkeypatch, groq_actif) -> None:
    appels: list[float] = []

    def groq(chemin, timeout=None):
        appels.append(timeout)
        if len(appels) == 1:
            raise _erreur_http(429, {"retry-after": "0.3"})
        return "prix du soja", 3.0

    monkeypatch.setattr(TR, "_groq", groq)
    monkeypatch.setattr(TR, "_local", lambda c: pytest.fail("pas de repli attendu"))
    r = TR.transcrire_detail("q.wav")
    assert r["moteur"] == "groq" and len(appels) == 2 and groq_actif == [0.3]
    assert all(t <= 5.5 - TR.RESERVE_APRES_GROQ_S for t in appels)


def test_transcription_429_retry_after_trop_long_repli_local(monkeypatch, groq_actif) -> None:
    appels = []

    def groq(chemin, timeout=None):
        appels.append(timeout)
        raise _erreur_http(429, {"retry-after": "20"})

    monkeypatch.setattr(TR, "_groq", groq)
    monkeypatch.setattr(TR, "_local", lambda c: ("local", 3.0))
    r = TR.transcrire_detail("q.wav")
    assert r["moteur"] == "local" and len(appels) == 1 and groq_actif == []


def test_transcription_deux_429_un_seul_reessai(monkeypatch, groq_actif) -> None:
    appels = []

    def groq(chemin, timeout=None):
        appels.append(timeout)
        raise _erreur_http(429)

    monkeypatch.setattr(TR, "_groq", groq)
    monkeypatch.setattr(TR, "_local", lambda c: ("local", 3.0))
    assert TR.transcrire_detail("q.wav")["moteur"] == "local"
    assert len(appels) == 2 and groq_actif == [delais.ATTENTE_429_DEFAUT_S]


def test_transcription_autre_erreur_pas_de_reessai(monkeypatch, groq_actif) -> None:
    appels = []

    def groq(chemin, timeout=None):
        appels.append(timeout)
        raise _erreur_http(500)

    monkeypatch.setattr(TR, "_groq", groq)
    monkeypatch.setattr(TR, "_local", lambda c: ("local", 3.0))
    assert TR.transcrire_detail("q.wav")["moteur"] == "local" and len(appels) == 1


def test_transcription_budget_epuise_repli_direct(monkeypatch, groq_actif) -> None:
    monkeypatch.setattr(TR, "_groq", lambda *a, **k: pytest.fail("Groq ne doit pas être appelé"))
    monkeypatch.setattr(TR, "_local", lambda c: ("local", 3.0))
    r = TR.transcrire_detail("q.wav", echeance=time.monotonic() + 1.0)
    assert r["moteur"] == "local"


def test_delai_groq_raccourci_par_le_budget(monkeypatch, groq_actif) -> None:
    vus = []
    monkeypatch.setattr(TR, "_groq", lambda c, timeout=None: vus.append(timeout) or ("ok", 3.0))
    TR.transcrire_detail("q.wav", echeance=time.monotonic() + 4.0)
    assert vus and vus[0] <= 2.0  # 4 s de budget − 2 s gardées pour repli + intention


def _rate_limit(entetes: dict | None = None) -> openai.RateLimitError:
    rep = httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com/x"),
                         headers=entetes or {})
    return openai.RateLimitError("429", response=rep, body=None)


def test_intention_429_puis_ok(monkeypatch) -> None:
    attentes: list[float] = []
    monkeypatch.setattr(I.time, "sleep", attentes.append)
    appels = []

    def groq(texte, timeout=I.TIMEOUT_SECONDS):
        appels.append(timeout)
        if len(appels) == 1:
            raise _rate_limit({"retry-after": "0.5"})
        return I.IntentionResult(intention="juger_offre", produit="soja", source="groq")

    monkeypatch.setattr(I, "_appeler_groq", groq)
    r = I.comprendre("on me propose quinze mille pour le soja")
    assert r["source"] == "groq" and r["intention"] == "juger_offre"
    assert len(appels) == 2 and attentes == [0.5]
    assert all(t <= I.TIMEOUT_SECONDS for t in appels)


def test_intention_429_deux_fois_repli_regles(monkeypatch) -> None:
    monkeypatch.setattr(I.time, "sleep", lambda s: None)
    appels = []

    def groq(texte, timeout=I.TIMEOUT_SECONDS):
        appels.append(timeout)
        raise _rate_limit()

    monkeypatch.setattr(I, "_appeler_groq", groq)
    r = I.comprendre("on me propose quinze mille pour le soja")
    assert r["source"] == "regles" and r["intention"] == "juger_offre" and len(appels) == 2


# ---------- 4. plafond global : repli avant 6 s ----------
def test_intention_budget_epuise_regles_sans_appel(monkeypatch) -> None:
    monkeypatch.setattr(I, "_appeler_groq", lambda *a, **k: pytest.fail("pas d'appel Groq"))
    debut = time.perf_counter()
    r = I.comprendre("le soja à Houndjro, il est à combien ?", echeance=time.monotonic() - 1)
    assert r["source"] == "regles" and r["intention"] == "prix"
    assert time.perf_counter() - debut < 0.5


def test_question_partage_une_seule_echeance(monkeypatch) -> None:
    vues = {}
    monkeypatch.setattr(QV, "transcrire", lambda c, echeance=None: vues.setdefault("t", echeance)
                        and "le prix du soja à Bohicon")
    monkeypatch.setattr(QV, "comprendre", lambda t, echeance=None: vues.setdefault("c", echeance)
                        and comprendre_par_regles(t))
    debut = time.monotonic()
    QV.analyser_question("q.wav")
    assert vues["t"] == vues["c"]
    assert debut + 5.0 <= vues["t"] <= time.monotonic() + 5.6  # IA_DELAI_MAX_S = 5,5 s


def test_delai_max_reglable(monkeypatch) -> None:
    monkeypatch.setenv("IA_DELAI_MAX_S", "4")
    get_settings.cache_clear()
    assert delais.nouvelle_echeance() - time.monotonic() == pytest.approx(4.0, abs=0.1)


# ---------- script G8 : pause entre audios ----------
def test_script_option_pause() -> None:
    from data.scripts.test_touche3_audios import construire_parser

    base = ["--classeur", "a.xlsx", "--audios", "a", "--wav", "w", "--sortie", "s.xlsx"]
    assert construire_parser().parse_args(base).pause == 0.0
    assert construire_parser().parse_args([*base, "--pause", "1.5"]).pause == 1.5
