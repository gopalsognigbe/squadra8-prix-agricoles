import unicodedata
from pathlib import Path

import pytest

from app.ia import transcription as t


def sans_accents(texte):
    brut = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in brut if unicodedata.category(c) != "Mn")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for nom in ("GROQ_API_KEY", "OPENAI_API_KEY", "AUDIO_MAX_S"):
        monkeypatch.delenv(nom, raising=False)
    monkeypatch.setattr(t, "_cle_reglages", lambda: (None, ""))


def _interdit(*a, **k):
    raise AssertionError("ne devait pas être appelé")


def test_groq_en_premier(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
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
    monkeypatch.setattr(t, "_groq", lambda c: ("bla", 9.0))
    monkeypatch.setattr(t, "_local", _interdit)
    with pytest.raises(t.AudioTropLong):
        t.transcrire("x.wav")


def test_duree_maximale_reglable(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    monkeypatch.setenv("AUDIO_MAX_S", "12")
    monkeypatch.setattr(t, "_groq", lambda c: ("ok", 9.0))
    assert t.transcrire("x.wav") == "ok"


def test_cle_groq_via_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "gsk_x")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
    assert t._cle_groq() == "gsk_x"
    monkeypatch.setenv("OPENAI_BASE_URL", "https://autre.exemple/v1")
    assert t._cle_groq() is None


AUDIO = Path("tests/audio/q3.wav")
MODELES = Path("models/whisper")


@pytest.mark.skipif(not (AUDIO.exists() and MODELES.exists()),
                    reason="audio d'essai ou modèle Whisper absent")
def test_vraie_transcription_locale():
    r = t.transcrire_detail(AUDIO)
    print(f"{r['texte']!r} en {r['ms']} ms ({r['moteur']})")
    texte = sans_accents(r["texte"])
    assert "kilo" in texte and ("120" in texte or "cent vingt" in texte)


def test_cle_groq_via_reglages(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setattr(t, "_cle_reglages",
                        lambda: ("gsk_y", "https://api.groq.com/openai/v1"))
    assert t._cle_groq() == "gsk_y"
