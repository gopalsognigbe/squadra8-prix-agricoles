"""Adaptateur simulateur : traduit un tour du moteur en JSON (contrat 5.1).

Responsable : Guillaume.

Pour que le service soit audible dans le navigateur, chaque phrase reçoit :
- « audio » : URL d'un vrai clip (servi sous /audio) s'il existe sur le disque,
  ou s'il peut être fabriqué par Piper (phrases calculées) ; sinon None ;
- « audio_source » : « clip » ou « navigateur » (le navigateur lit alors le texte).
"""
import logging
from functools import lru_cache
from importlib.util import find_spec

from app.dialogue.moteur import Tour
from app.voix.piper_tts import PiperTTS

log = logging.getLogger(__name__)


@lru_cache
def _tts() -> PiperTTS:
    return PiperTTS()


@lru_cache
def _piper_pret() -> bool:
    """Piper installé et voix téléchargée : on peut fabriquer les phrases calculées."""
    tts = _tts()
    return find_spec("piper") is not None and (
        tts.dossier_voix / f"{tts.nom_voix}.onnx").exists()


def _audio(phrase: dict) -> str | None:
    tts = _tts()
    url = phrase.get("audio")
    if url and (tts.dossier_clips / url.rsplit("/", 1)[-1]).exists():
        return url
    if not _piper_pret():
        return None
    try:
        return tts.url_dynamique(phrase["texte"])
    except Exception:  # noqa: BLE001 — sans clip, le navigateur lit le texte
        log.warning("Clip Piper impossible pour %s", phrase.get("id"), exc_info=True)
        return None


def tour_vers_json(tour: Tour) -> dict:
    """Le Tour du moteur a déjà le format du contrat : etat, phrases, attente..."""
    donnees = tour.model_dump()
    for phrase in donnees["phrases"]:
        phrase["audio"] = _audio(phrase)
        phrase["audio_source"] = "clip" if phrase["audio"] else "navigateur"
    return donnees
