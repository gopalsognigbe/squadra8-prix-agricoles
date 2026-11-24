import unicodedata
from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.ia import transcription as t
from data.scripts.maj_fao import PRODUITS_MVP


def sans_accents(texte):
    brut = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in brut if unicodedata.category(c) != "Mn")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    # Chaînes vides : masquent une éventuelle clé du fichier .env local.
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    for nom in (
        "OPENAI_BASE_URL",
        "AUDIO_MAX_S",
        "GROQ_MODELE",
        "GROQ_TIMEOUT_S",
        "WHISPER_MODELE",
    ):
        monkeypatch.delenv(nom, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _interdit(*a, **k):
    raise AssertionError("ne devait pas être appelé")


def test_indice_catalogue_mvp() -> None:
    assert "Bohicon" in t.INDICE
    assert "Houndjro (Abomey)" in t.INDICE
    assert "Azogotchébou (Covè)" in t.INDICE
    for produit in PRODUITS_MVP:
        assert produit in t.INDICE
    assert "Zogbodomey" not in t.INDICE
    assert "Hlanxi" not in t.INDICE
    # Pas de marché nommé seulement « Abomey » ou « Covè ».
    parties = [p.strip() for p in t.INDICE.split(",")]
    assert "Abomey" not in parties
    assert "Covè" not in parties
    assert "prix" in t.INDICE and "offre" in t.INDICE and "combien" in t.INDICE


def test_defaut_whisper_modele_base() -> None:
    assert Settings.model_fields["whisper_modele"].default == "base"


def test_groq_en_premier(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    get_settings.cache_clear()
    monkeypatch.setattr(t, "_groq", lambda c: ("prix du maïs", 3.0))
    monkeypatch.setattr(t, "_local", _interdit)
    r = t.transcrire_detail("x.wav")
    assert r["texte"] == "prix du maïs" and r["moteur"] == "groq"
    assert r["duree_s"] == 3.0 and r["ms"] >= 0
    assert t.transcrire("x.wav") == "prix du maïs"


def test_repli_local_si_groq_echoue(monkeypatch):
    def ko(c):
        raise RuntimeError("réseau")

    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    get_settings.cache_clear()
    monkeypatch.setattr(t, "_groq", ko)
    monkeypatch.setattr(t, "_local", lambda c: ("local", 2.0))
    r = t.transcrire_detail("x.wav")
    assert r["texte"] == "local" and r["moteur"] == "local"


def test_sans_cle_groq_pas_appele(monkeypatch):
    monkeypatch.setattr(t, "_groq", _interdit)
    monkeypatch.setattr(t, "_local", lambda c: ("local", 2.0))
    assert t.transcrire("x.wav") == "local"


def test_audio_trop_long_sans_repli(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    get_settings.cache_clear()
    monkeypatch.setattr(t, "_groq", lambda c: ("bla", 9.0))
    monkeypatch.setattr(t, "_local", _interdit)
    with pytest.raises(t.AudioTropLong):
        t.transcrire("x.wav")


def test_duree_maximale_reglable(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    monkeypatch.setenv("AUDIO_MAX_S", "12")
    get_settings.cache_clear()
    monkeypatch.setattr(t, "_groq", lambda c: ("ok", 9.0))
    assert t.transcrire("x.wav") == "ok"


def test_cle_groq_via_openai(monkeypatch):
    # Sans GROQ_API_KEY : l'alias OPENAI_API_KEY + base Groq doit suffire.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "gsk_x")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
    get_settings.cache_clear()
    assert t._cle_groq() == "gsk_x"
    monkeypatch.setenv("OPENAI_BASE_URL", "https://autre.exemple/v1")
    get_settings.cache_clear()
    assert t._cle_groq() is None


def test_cle_groq_via_settings(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_y")
    get_settings.cache_clear()
    assert t._cle_groq() == "gsk_y"


AUDIO = Path("tests/audio/q3.wav")
MODELES = Path("models/whisper")


@pytest.mark.skipif(
    not (AUDIO.exists() and MODELES.exists()),
    reason="audio d'essai ou modèle Whisper absent",
)
def test_vraie_transcription_locale():
    r = t.transcrire_detail(AUDIO)
    print(f"{r['texte']!r} en {r['ms']} ms ({r['moteur']})")
    texte = sans_accents(r["texte"])
    assert "kilo" in texte and ("120" in texte or "cent vingt" in texte)
