"""Tests des routes du simulateur (contrat 5.1)."""
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api import sim
from app.dialogue.moteur import Moteur, Phrase, Session, Tour
from app.ia.transcription import AudioTropLong
from app.main import app
from tests.fakes import services_fakes

client = TestClient(app)
NUMERO = "+22990000000"
BASE = "/api/sim/appels"


class MoteurBidon:
    """Moteur minimal : une session déjà en attente de la question à voix haute."""

    def __init__(self):
        self.evenements = []

    def nouvelle_session(self, appel_id):
        return Session(appel_id=appel_id, etat="QUESTION_VOIX")

    def traiter(self, sess, ev):
        self.evenements.append(ev)
        return Tour(etat="MENU_PRINCIPAL", phrases=[Phrase(id="M01", texte="ok")],
                    attente="touche", touches_valides=["1"])


def _interdit(*a, **k):
    raise AssertionError("ne devait pas être appelé")


@pytest.fixture(autouse=True)
def _propre(monkeypatch):
    sim._APPELS.clear()
    moteur = Moteur(services_fakes())
    monkeypatch.setattr(sim, "get_moteur", lambda: moteur)


def _bip():
    r = client.post("/api/sim/bip", json={"numero": NUMERO})
    assert r.status_code == 200
    return r.json()


def _voix(appel_id, nom="q.webm", mime="audio/webm", donnees=b"fake"):
    return client.post(f"{BASE}/{appel_id}/voix",
                       files={"fichier": (nom, donnees, mime)})


def _avec_bidon(monkeypatch):
    moteur = MoteurBidon()
    monkeypatch.setattr(sim, "get_moteur", lambda: moteur)
    return moteur


def test_bip_ok():
    d = _bip()
    assert d["rappel_dans_s"] == 5
    uuid.UUID(d["appel_id"])


def test_bip_numero_invalide():
    assert client.post("/api/sim/bip", json={"numero": "123"}).status_code == 422


def test_bip_refuse_par_anti_abus(monkeypatch):
    monkeypatch.setattr(sim, "hasher_numero", lambda n: "h")
    monkeypatch.setattr(sim, "bip_autorise", lambda h: False)
    assert client.post("/api/sim/bip", json={"numero": NUMERO}).status_code == 429


def test_numero_jamais_garde():
    appel_id = _bip()["appel_id"]
    assert NUMERO not in repr(sim._APPELS[appel_id][0])


def test_appel_complet_avec_le_vrai_moteur():
    appel_id = _bip()["appel_id"]
    t = client.post(f"{BASE}/{appel_id}/decroche").json()
    assert {"etat", "phrases", "attente", "touches_valides", "delai_s", "fin"} <= set(t)
    assert t["etat"] == "CHOIX_PRODUIT" and t["phrases"]
    assert {"id", "texte", "audio"} <= set(t["phrases"][0])
    t = client.post(f"{BASE}/{appel_id}/touche", json={"touche": "1"}).json()
    assert t["etat"] == "MENU_PRINCIPAL"
    t = client.post(f"{BASE}/{appel_id}/touche", json={"touche": "1"}).json()
    assert t["phrases"]
    assert client.post(f"{BASE}/{appel_id}/raccroche").json() == {"ok": True}
    assert client.post(f"{BASE}/{appel_id}/decroche").status_code == 404


def test_appel_inconnu_404():
    inconnu = uuid.uuid4()
    assert client.post(f"{BASE}/{inconnu}/decroche").status_code == 404
    assert client.post(f"{BASE}/{inconnu}/touche", json={"touche": "1"}).status_code == 404


def test_touche_invalide_422():
    appel_id = _bip()["appel_id"]
    for touche in ("x", "12", ""):
        r = client.post(f"{BASE}/{appel_id}/touche", json={"touche": touche})
        assert r.status_code == 422


def test_raccroche_idempotent():
    r = client.post(f"{BASE}/{uuid.uuid4()}/raccroche")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_voix_transcrit_puis_passe_au_moteur(monkeypatch):
    moteur = _avec_bidon(monkeypatch)
    vu = {}

    def faux(chemin):
        vu["chemin"], vu["existe"] = chemin, os.path.exists(chemin)
        return {"texte": "combien le soja à Bohicon", "duree_s": 1.7, "ms": 900,
                "moteur": "groq"}

    monkeypatch.setattr(sim, "transcrire_detail", faux)
    r = _voix(_bip()["appel_id"])
    assert r.status_code == 200
    d = r.json()
    assert d["transcription"] == "combien le soja à Bohicon" and "intention" in d
    assert d["etat"] == "MENU_PRINCIPAL"
    ev = moteur.evenements[-1]
    # Texte déjà transcrit : préfixe « texte: » pour ne pas le retranscrire.
    assert ev.type == "VOIX" and ev.valeur == "texte:" + d["transcription"]
    assert vu["chemin"].endswith(".webm") and vu["existe"]
    assert not os.path.exists(vu["chemin"])


def test_voix_extension_selon_le_type(monkeypatch):
    _avec_bidon(monkeypatch)
    vu = {}

    def faux(chemin):
        vu["chemin"] = chemin
        return {"texte": "ok", "duree_s": 1.0, "ms": 1, "moteur": "local"}

    monkeypatch.setattr(sim, "transcrire_detail", faux)
    _voix(_bip()["appel_id"], nom="blob", mime="audio/ogg;codecs=opus")
    assert vu["chemin"].endswith(".ogg")


def test_voix_audio_trop_long(monkeypatch):
    moteur = _avec_bidon(monkeypatch)

    def faux(chemin):
        raise AudioTropLong("9 s au lieu de 8 s")

    monkeypatch.setattr(sim, "transcrire_detail", faux)
    d = _voix(_bip()["appel_id"]).json()
    assert d["transcription"] == "" and d["erreur"] == "audio_trop_long"
    assert moteur.evenements[-1].valeur == ""


def test_voix_hors_question_sans_transcrire(monkeypatch):
    monkeypatch.setattr(sim, "transcrire_detail", _interdit)
    appel_id = _bip()["appel_id"]
    client.post(f"{BASE}/{appel_id}/decroche")
    r = _voix(appel_id)
    assert r.status_code == 200 and r.json()["transcription"] == ""


def test_voix_trop_volumineuse(monkeypatch):
    _avec_bidon(monkeypatch)
    monkeypatch.setattr(sim, "transcrire_detail", _interdit)
    r = _voix(_bip()["appel_id"], donnees=b"x" * (sim.TAILLE_MAX + 1))
    assert r.status_code == 413


_GET_MOTEUR_REEL = sim.get_moteur  # avant tout monkeypatch


def test_moteur_reel_se_construit():
    _GET_MOTEUR_REEL.cache_clear()
    try:
        assert isinstance(_GET_MOTEUR_REEL(), Moteur)
    finally:
        _GET_MOTEUR_REEL.cache_clear()


def _voix_reelle(monkeypatch, resultat):
    services = services_fakes(question=lambda valeur: {**resultat, "vu": valeur})
    moteur = Moteur(sim.suivre_question(services), voix_active=True)
    monkeypatch.setattr(sim, "get_moteur", lambda: moteur)
    monkeypatch.setattr(sim, "transcrire_detail", lambda chemin: {
        "texte": "combien le soja à Bohicon", "duree_s": 1.0, "ms": 1, "moteur": "groq"})
    appel_id = _bip()["appel_id"]
    client.post(f"{BASE}/{appel_id}/decroche")
    client.post(f"{BASE}/{appel_id}/touche", json={"touche": "2"})
    t = client.post(f"{BASE}/{appel_id}/touche", json={"touche": "3"}).json()
    assert t["attente"] == "voix"
    return _voix(appel_id).json()


def test_voix_renvoie_intention(monkeypatch):
    d = _voix_reelle(monkeypatch, {
        "erreur": None, "texte": "combien le soja à Bohicon", "intention": "prix",
        "famille": "soja", "variete": None, "marche": "Bohicon",
        "montant": None, "unite": None})
    assert d["intention"] == "prix"
    assert d["compris"]["famille"] == "soja" and d["compris"]["marche"] == "Bohicon"
    assert "vu" not in d["compris"]


def test_voix_sans_intention_si_erreur_ia(monkeypatch):
    d = _voix_reelle(monkeypatch, {"erreur": "ia", "intention": "inconnu"})
    assert d["intention"] is None and "compris" not in d


def test_phrases_audibles_clip_ou_navigateur(monkeypatch, tmp_path):
    from app.dialogue.adaptateurs import sim as adaptateur

    (tmp_path / "A01.wav").write_bytes(b"RIFF")
    tts = adaptateur._tts()
    monkeypatch.setattr(tts, "dossier_clips", tmp_path)
    monkeypatch.setattr(adaptateur, "_piper_pret", lambda: False)
    t = client.post(f"{BASE}/{_bip()['appel_id']}/decroche").json()
    a01, p00 = t["phrases"]
    assert a01["audio"] == "/audio/A01.wav" and a01["audio_source"] == "clip"
    assert p00["audio"] is None and p00["audio_source"] == "navigateur"


def test_page_simulateur_servie():
    r = client.get("/simulateur/")
    assert r.status_code == 200 and "Biper" in r.text
    assert client.get("/simulateur/app.js").status_code == 200
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/simulateur/"
