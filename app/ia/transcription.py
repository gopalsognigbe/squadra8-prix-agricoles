"""Transcription de la voix en texte (I2) : Groq (Whisper) d'abord, faster-whisper local en secours.

Responsable : Guillaume.

    transcrire(chemin_audio) -> str
    transcrire_detail(chemin_audio) -> {'texte', 'duree_s', 'ms', 'moteur'}

Réglages (app.config / .env) :
    GROQ_API_KEY / OPENAI_API_KEY + OPENAI_BASE_URL (groq) : clé cloud
    GROQ_MODELE, GROQ_TIMEOUT_S, AUDIO_MAX_S
    WHISPER_MODELE (défaut base), WHISPER_MODELES_DIR, WHISPER_BEAM, WHISPER_THREADS
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import httpx

from app.config import get_settings
from app.ia.delais import (
    TIMEOUT_MIN_S,
    attente_429,
    nouvelle_echeance,
    reessai_possible,
    restant,
)
from app.services.source_prix import ORDRE_MARCHES
from data.scripts.maj_fao import MARCHES_MVP, PRODUITS_MVP

log = logging.getLogger(__name__)

RACINE = Path(__file__).resolve().parents[2]
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Ordre stable des 6 produits MVP (identique aux graines / touches étendues).
_ORDRE_PRODUITS = (
    "Maïs Blanc",
    "Maïs Jaune",
    "Soja",
    "Haricot blanc",
    "Haricot noir",
    "Haricot rouge",
)
assert set(_ORDRE_PRODUITS) == PRODUITS_MVP
assert set(ORDRE_MARCHES) == MARCHES_MVP

INDICE = ", ".join([*_ORDRE_PRODUITS, *ORDRE_MARCHES, "prix", "offre", "combien"])


class AudioTropLong(Exception):
    """La question dépasse la durée maximale autorisée."""


def _cle_groq() -> str | None:
    """Clé Groq via Settings (aliases GROQ_API_KEY / OPENAI_API_KEY)."""
    settings = get_settings()
    cle = (settings.openai_api_key or "").strip()
    base = (settings.openai_base_url or "").casefold()
    return cle if cle and "groq" in base else None


def _controler(duree: float) -> None:
    maxi = float(get_settings().audio_max_s)
    if duree > maxi:
        raise AudioTropLong(f"{duree:.1f} s au lieu de {maxi:.0f} s au plus")


# Temps gardé pour le repli (Whisper local) et l'intention après Groq.
RESERVE_APRES_GROQ_S = 2.0


def _groq(chemin: str | Path, timeout: float | None = None) -> tuple[str, float]:
    settings = get_settings()
    with open(chemin, "rb") as f:
        r = httpx.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {_cle_groq()}"},
            data={
                "model": settings.groq_modele,
                "language": "fr",
                "temperature": "0",
                "response_format": "verbose_json",
                "prompt": INDICE,
            },
            files={"file": (Path(chemin).name, f)},
            timeout=float(timeout if timeout is not None else settings.groq_timeout_s),
        )
    r.raise_for_status()
    j = r.json()
    return j["text"].strip(), float(j.get("duration", 0))


_modele = None
_verrou = threading.Lock()


def _charger_modele_local():
    """Charge le modèle Whisper local une seule fois (à appeler sous _verrou)."""
    global _modele
    if _modele is None:
        from faster_whisper import WhisperModel  # import tardif

        settings = get_settings()
        dossier = Path(settings.whisper_modeles_dir)
        if not dossier.is_absolute():
            dossier = RACINE / dossier
        _modele = WhisperModel(
            settings.whisper_modele,
            device="cpu",
            compute_type="int8",
            cpu_threads=int(settings.whisper_threads),
            download_root=str(dossier),
        )
    return _modele


def prechauffer_local() -> bool:
    """Charge Whisper local à l'avance, pour que le repli ne coûte pas le
    chargement du modèle pendant un appel. Faux si faster-whisper manque."""
    try:
        with _verrou:
            _charger_modele_local()
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Préchauffage Whisper local impossible : %s", e)
        return False


def _local(chemin: str | Path) -> tuple[str, float]:
    settings = get_settings()
    with _verrou:
        _modele_local = _charger_modele_local()
        segments, info = _modele_local.transcribe(
            str(chemin),
            language="fr",
            vad_filter=True,
            beam_size=int(settings.whisper_beam),
            initial_prompt=INDICE,
            condition_on_previous_text=False,
        )
        _controler(info.duration)  # avant de décoder : inutile si trop long
        texte = " ".join(s.text.strip() for s in segments).strip()
    return texte, info.duration


def _groq_dans_le_budget(chemin: str | Path, echeance: float) -> tuple[str, float]:
    """Groq avec délai raccourci et un seul réessai court après un 429."""
    maxi = float(get_settings().groq_timeout_s)
    for essai in range(2):
        timeout = min(maxi, restant(echeance) - RESERVE_APRES_GROQ_S)
        if timeout < TIMEOUT_MIN_S:
            raise TimeoutError("plus de temps pour Groq, repli local")
        try:
            return _groq(chemin, timeout)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 429 or essai == 1:
                raise
            attente = attente_429(e.response.headers)
            if not reessai_possible(attente, echeance, RESERVE_APRES_GROQ_S):
                raise
            log.info("Groq 429 (transcription), réessai dans %.2f s", attente)
            time.sleep(attente)
    raise RuntimeError("inaccessible")


def transcrire_detail(chemin_audio: str | Path, echeance: float | None = None) -> dict:
    """Transcrit. echeance (time.monotonic) : fin du budget de la question."""
    debut = time.perf_counter()
    echeance = echeance if echeance is not None else nouvelle_echeance()
    resultat, moteur = None, "local"
    if _cle_groq():
        try:
            resultat, moteur = _groq_dans_le_budget(chemin_audio, echeance), "groq"
        except Exception as e:
            log.warning("Groq indisponible (%s), repli sur Whisper local", e)
    if resultat is None:
        resultat = _local(chemin_audio)
    texte, duree = resultat
    _controler(duree)
    return {
        "texte": texte,
        "duree_s": round(duree, 2),
        "ms": int((time.perf_counter() - debut) * 1000),
        "moteur": moteur,
    }


def transcrire(chemin_audio: str | Path, echeance: float | None = None) -> str:
    """Écrit en texte ce qui a été dit (interface du squelette)."""
    return transcrire_detail(chemin_audio, echeance)["texte"]
