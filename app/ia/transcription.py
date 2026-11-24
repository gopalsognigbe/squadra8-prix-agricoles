"""Transcription de la voix en texte (I2) : Groq (Whisper) d'abord, faster-whisper local en secours.

Responsable : Guillaume.

    transcrire(chemin_audio) -> str
    transcrire_detail(chemin_audio) -> {'texte', 'duree_s', 'ms', 'moteur'}

Réglages (.env) :
    GROQ_API_KEY    clé Groq, ou OPENAI_API_KEY si OPENAI_BASE_URL pointe vers Groq
                    (aucune clé = Whisper local seul)
    GROQ_MODELE     whisper-large-v3-turbo (par défaut)
    GROQ_TIMEOUT_S  6 (par défaut) ; au-delà, repli sur le local
    WHISPER_MODELE  base (par défaut) ou small
    WHISPER_MODELES_DIR, WHISPER_BEAM, WHISPER_THREADS : réglages du Whisper local
    AUDIO_MAX_S     durée maximale d'une question (8 s par défaut)
"""
import logging
import os
import threading
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

RACINE = Path(__file__).resolve().parents[2]
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
INDICE = ("maïs, soja, haricot, Bohicon, Abomey, Covè, Zogbodomey, "
          "prix, offre, combien")


class AudioTropLong(Exception):
    """La question dépasse la durée maximale autorisée."""


def _cle_reglages():
    """Clé et URL lues comme le reste du projet (app.config), sans toucher à os.environ."""
    try:
        from app.config import get_settings
        s = get_settings()
        return (getattr(s, "openai_api_key", None),
                getattr(s, "openai_base_url", None) or "")
    except Exception:
        return None, ""


def _cle_groq():
    cle = os.getenv("GROQ_API_KEY")
    if cle:
        return cle
    cle = os.getenv("OPENAI_API_KEY")
    base = os.getenv("OPENAI_BASE_URL")
    if not (cle and base):
        c2, b2 = _cle_reglages()
        cle, base = cle or c2, base or b2
    return cle if cle and "groq" in (base or "") else None


def _controler(duree):
    maxi = float(os.getenv("AUDIO_MAX_S", "8"))
    if duree > maxi:
        raise AudioTropLong(f"{duree:.1f} s au lieu de {maxi:.0f} s au plus")


def _groq(chemin):
    with open(chemin, "rb") as f:
        r = httpx.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {_cle_groq()}"},
            data={"model": os.getenv("GROQ_MODELE", "whisper-large-v3-turbo"),
                  "language": "fr", "temperature": "0",
                  "response_format": "verbose_json", "prompt": INDICE},
            files={"file": (Path(chemin).name, f)},
            timeout=float(os.getenv("GROQ_TIMEOUT_S", "6")))
    r.raise_for_status()
    j = r.json()
    return j["text"].strip(), float(j.get("duration", 0))


_modele = None
_verrou = threading.Lock()


def _local(chemin):
    global _modele
    with _verrou:
        if _modele is None:
            from faster_whisper import WhisperModel  # import tardif
            dossier = Path(os.getenv("WHISPER_MODELES_DIR", "models/whisper"))
            if not dossier.is_absolute():
                dossier = RACINE / dossier
            _modele = WhisperModel(
                os.getenv("WHISPER_MODELE", "base"), device="cpu",
                compute_type="int8",
                cpu_threads=int(os.getenv("WHISPER_THREADS", "0")),
                download_root=str(dossier))
        segments, info = _modele.transcribe(
            str(chemin), language="fr", vad_filter=True,
            beam_size=int(os.getenv("WHISPER_BEAM", "1")),
            initial_prompt=INDICE, condition_on_previous_text=False)
        _controler(info.duration)  # avant de décoder : inutile si trop long
        texte = " ".join(s.text.strip() for s in segments).strip()
    return texte, info.duration


def transcrire_detail(chemin_audio):
    debut = time.perf_counter()
    resultat, moteur = None, "local"
    if _cle_groq():
        try:
            resultat, moteur = _groq(chemin_audio), "groq"
        except Exception as e:
            log.warning("Groq indisponible (%s), repli sur Whisper local", e)
    if resultat is None:
        resultat = _local(chemin_audio)
    texte, duree = resultat
    _controler(duree)
    return {"texte": texte, "duree_s": round(duree, 2),
            "ms": int((time.perf_counter() - debut) * 1000), "moteur": moteur}


def transcrire(chemin_audio) -> str:
    """Écrit en texte ce qui a été dit (interface du squelette)."""
    return transcrire_detail(chemin_audio)["texte"]
