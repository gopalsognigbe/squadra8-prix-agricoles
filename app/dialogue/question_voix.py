"""Touche 3 : de l'audio de l'appelant à une demande comprise (sans aucun prix).

    analyser_question(valeur) -> dict

valeur : chemin d'un fichier audio, ou « texte:... » pour tester sans audio
(console, simulateur). Le résultat ne contient jamais de prix de référence :
seulement l'intention, le produit, la couleur, le marché (nom FAO exact)
et, pour une offre, le montant dit par l'appelant.

Clés renvoyées :
    erreur    : None | "trop_long" | "vide" | "transcription" | "ia"
    texte     : transcription
    intention : "prix" | "juger_offre" | "autre" | "inconnu"
    famille   : "mais" | "soja" | "haricot" | None
    variete   : "blanc" | "jaune" | "noir" | "rouge" | None
    marche    : "Bohicon" | "Houndjro (Abomey)" | "Azogotchébou (Covè)" | None
    montant   : int | None   (francs, tel que dit)
    unite     : "kg" | "100kg" | "sac" | None
"""

from __future__ import annotations

import logging

from app.ia.intention import comprendre
from app.ia.regles import PRODUITS, extraire_offre, trouver_variete
from app.ia.transcription import AudioTropLong, transcrire

logger = logging.getLogger(__name__)

PREFIXE_TEXTE = "texte:"

# Code IA → nom FAO exact (3 marchés MVP seulement, pas d'autre marché).
MARCHE_FAO = {
    "bohicon": "Bohicon",
    "abomey": "Houndjro (Abomey)",
    "cove": "Azogotchébou (Covè)",
}


def _resultat(erreur: str | None, texte: str = "", **autres) -> dict:
    base = {
        "erreur": erreur,
        "texte": texte,
        "intention": "inconnu",
        "famille": None,
        "variete": None,
        "marche": None,
        "montant": None,
        "unite": None,
    }
    base.update(autres)
    return base


def analyser_question(valeur: str) -> dict:
    """Transcrit puis comprend la question. Ne lève jamais d'exception."""
    valeur = (valeur or "").strip()
    if valeur.startswith(PREFIXE_TEXTE):
        texte = valeur[len(PREFIXE_TEXTE):].strip()
    else:
        try:
            texte = transcrire(valeur)
        except AudioTropLong as exc:
            logger.info("Question trop longue : %s", exc)
            return _resultat("trop_long")
        except Exception as exc:  # noqa: BLE001 — l'appel ne doit jamais planter
            logger.warning("Transcription impossible : %s", exc)
            return _resultat("transcription")

    if not texte.strip():
        return _resultat("vide")

    try:
        compris = comprendre(texte)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Intention impossible : %s", exc)
        return _resultat("ia", texte)

    famille = compris.get("produit")
    if famille not in PRODUITS:
        famille = None
    marche = MARCHE_FAO.get(compris.get("marche") or "")
    offre = extraire_offre(texte)
    return _resultat(
        None,
        texte,
        intention=compris.get("intention") or "inconnu",
        famille=famille,
        variete=trouver_variete(texte, famille),
        marche=marche,
        montant=offre["montant"],
        unite=offre["unite"],
    )
