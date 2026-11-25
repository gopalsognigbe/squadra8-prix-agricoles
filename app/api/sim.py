"""Routes du simulateur (faux téléphone dans le navigateur) : contrat 5.1.

Responsable : Guillaume.
"""
import logging
import os
import tempfile
import threading
import time
import uuid
from functools import lru_cache

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.config import get_settings
from app.dialogue.adaptateurs.sim import tour_vers_json
from app.dialogue.moteur import Evenement, Moteur, Services, Session
from app.dialogue.question_voix import PREFIXE_TEXTE
from app.dialogue.services_prix import services_reels
from app.ia.transcription import AudioTropLong, transcrire_detail
from app.services.anti_abus import bip_autorise
from app.services.numeros import hasher_numero

log = logging.getLogger(__name__)
router = APIRouter()

RAPPEL_DANS_S = 5
DUREE_VIE_S = 30 * 60
TAILLE_MAX = 3 * 1024 * 1024
EXTENSIONS = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/wav": ".wav",
              "audio/x-wav": ".wav", "audio/mpeg": ".mp3", "audio/mp4": ".m4a"}

# appel_id -> (session du moteur, dernière activité). En mémoire : démo seulement.
_APPELS: dict[str, tuple[Session, float]] = {}
# Dernier résultat de la touche 3 (par fil d'exécution) pour remplir « intention ».
_SUIVI = threading.local()
CHAMPS_COMPRIS = ("intention", "famille", "variete", "marche", "montant", "unite")


class BipIn(BaseModel):
    numero: str = Field(pattern=r"^\+\d{8,15}$")


class ToucheIn(BaseModel):
    touche: str = Field(pattern=r"^[0-9*#]$")


def suivre_question(services: Services) -> Services:
    """Garde le résultat de services.question pour l'afficher dans le simulateur."""
    origine = services.question
    if origine is None:
        return services

    def question(valeur: str) -> dict:
        res = origine(valeur)
        _SUIVI.resultat = res
        return res

    services.question = question
    return services


@lru_cache
def get_moteur() -> Moteur:
    s = get_settings()
    return Moteur(suivre_question(services_reels()), voix_active=s.question_voix_active,
                  delai_voix=int(getattr(s, "audio_max_s", 8)))


def _bip_autorise(numero: str) -> bool:
    try:
        return bip_autorise(hasher_numero(numero))
    except NotImplementedError:
        log.warning("Anti-abus pas encore implémenté (S3/S4) : bip autorisé")
        return True


def _purger() -> None:
    limite = time.time() - DUREE_VIE_S
    for cle in [k for k, (_, t) in _APPELS.items() if t < limite]:
        del _APPELS[cle]


def _session(appel_id: str) -> Session:
    _purger()
    if appel_id not in _APPELS:
        raise HTTPException(404, "Appel inconnu ou terminé.")
    sess = _APPELS[appel_id][0]
    _APPELS[appel_id] = (sess, time.time())
    return sess


def _extension(fichier: UploadFile) -> str:
    mime = (fichier.content_type or "").split(";")[0].strip().lower()
    ext = EXTENSIONS.get(mime) or os.path.splitext(fichier.filename or "")[1].lower()
    return ext if ext in EXTENSIONS.values() else ".webm"


def _transcrire(donnees: bytes, ext: str) -> tuple[str, str | None]:
    chemin = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(donnees)
            chemin = f.name
        r = transcrire_detail(chemin)
        log.info("voix : %s en %s ms", r.get("moteur"), r.get("ms"))
        return r["texte"], None
    except AudioTropLong:
        return "", "audio_trop_long"
    except Exception:
        log.exception("Transcription impossible")
        return "", "transcription_indisponible"
    finally:
        if chemin and os.path.exists(chemin):
            os.remove(chemin)


@router.post("/bip")
def post_bip(body: BipIn) -> dict:
    if not _bip_autorise(body.numero):  # le numéro n'est pas conservé
        raise HTTPException(429, "Trop de bips pour ce numéro. Réessaie plus tard.")
    _purger()
    appel_id = str(uuid.uuid4())
    _APPELS[appel_id] = (get_moteur().nouvelle_session(appel_id), time.time())
    return {"appel_id": appel_id, "rappel_dans_s": RAPPEL_DANS_S}


@router.post("/appels/{appel_id}/decroche")
def post_decroche(appel_id: str) -> dict:
    tour = get_moteur().traiter(_session(appel_id), Evenement(type="DECROCHE"))
    return tour_vers_json(tour)


@router.post("/appels/{appel_id}/touche")
def post_touche(appel_id: str, body: ToucheIn) -> dict:
    ev = Evenement(type="TOUCHE", valeur=body.touche)
    return tour_vers_json(get_moteur().traiter(_session(appel_id), ev))


@router.post("/appels/{appel_id}/voix")
def post_voix(appel_id: str, fichier: UploadFile = File(...)) -> dict:
    sess = _session(appel_id)
    donnees = fichier.file.read(TAILLE_MAX + 1)
    if len(donnees) > TAILLE_MAX:
        raise HTTPException(413, "Enregistrement trop volumineux.")
    texte, erreur = "", None
    if sess.etat == "QUESTION_VOIX":
        texte, erreur = _transcrire(donnees, _extension(fichier))
    # Le texte est déjà transcrit : préfixe « texte: » pour que question_voix ne
    # cherche pas à le retranscrire comme un fichier audio.
    valeur = f"{PREFIXE_TEXTE}{texte}" if texte.strip() else ""
    _SUIVI.resultat = None
    tour = get_moteur().traiter(sess, Evenement(type="VOIX", valeur=valeur))
    compris = getattr(_SUIVI, "resultat", None)
    _SUIVI.resultat = None
    reponse = {**tour_vers_json(tour), "transcription": texte, "intention": None}
    if isinstance(compris, dict) and not compris.get("erreur"):
        reponse["intention"] = compris.get("intention")
        reponse["compris"] = {k: compris.get(k) for k in CHAMPS_COMPRIS}
    if erreur:
        reponse["erreur"] = erreur
    return reponse


@router.post("/appels/{appel_id}/raccroche")
def post_raccroche(appel_id: str) -> dict:
    entree = _APPELS.pop(appel_id, None)
    if entree:
        get_moteur().traiter(entree[0], Evenement(type="RACCROCHE"))
    return {"ok": True}
