"""Touche 3 : de l'audio de l'appelant à une demande comprise (sans aucun prix).

    analyser_question(valeur) -> dict

valeur : chemin d'un fichier audio, ou « texte:... » pour tester sans audio
(console, simulateur). Le résultat ne contient jamais de prix de référence :
seulement l'intention, le produit, la couleur, le marché (nom FAO exact)
et, pour une offre, le montant dit par l'appelant.

Clés renvoyées :
    erreur    : None | "trop_long" | "vide" | "transcription" | "ia"

Chaque précision vient de l'IA ET d'une règle de secours lue dans la phrase.
Si les deux se contredisent (couleur, marché, montant, unité), la valeur est
None : le moteur demande à l'appelant au lieu de deviner.
    texte     : transcription
    intention : "prix" | "juger_offre" | "autre" | "inconnu"
    famille   : "mais" | "soja" | "haricot" | None
    variete   : "blanc" | "jaune" | "noir" | "rouge" | None
    marche    : "Bohicon" | "Houndjro (Abomey)" | "Azogotchébou (Covè)" | None
    montant   : int | None   (francs, tel que dit)
    unite     : "kg" | "100kg" | "sac" | None
    commune   : commune de départ dite (« je suis à Zagnanado »), sinon None
"""

from __future__ import annotations

import logging

from app.ia.delais import nouvelle_echeance
from app.ia.intention import comprendre
from app.ia.regles import (
    PRODUITS,
    VARIETES,
    extraire_offre,
    groupes_nombres,
    resoudre_ville_marche,
    trouver_produit,
    trouver_variete,
)
from app.services.transport import trouver_commune
from app.ia.transcription import AudioTropLong, transcrire

logger = logging.getLogger(__name__)

PREFIXE_TEXTE = "texte:"


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
        "commune": None,
    }
    base.update(autres)
    return base


def analyser_question(valeur: str) -> dict:
    """Transcrit puis comprend la question. Ne lève jamais d'exception."""
    valeur = (valeur or "").strip()
    # Un seul budget (IA_DELAI_MAX_S) pour transcription + intention : réponse < 6 s.
    echeance = nouvelle_echeance()
    if valeur.startswith(PREFIXE_TEXTE):
        texte = valeur[len(PREFIXE_TEXTE):].strip()
    else:
        try:
            texte = transcrire(valeur, echeance=echeance)
        except AudioTropLong as exc:
            logger.info("Question trop longue : %s", exc)
            return _resultat("trop_long")
        except Exception as exc:  # noqa: BLE001 — l'appel ne doit jamais planter
            logger.warning("Transcription impossible : %s", exc)
            return _resultat("transcription")

    if not texte.strip():
        return _resultat("vide")

    try:
        compris = comprendre(texte, echeance=echeance)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Intention impossible : %s", exc)
        return _resultat("ia", texte)

    return _fusionner(texte, compris)


def _accord(ia, regle):
    """IA et règle d'accord, ou une seule des deux. En désaccord → None (on demande)."""
    if ia is not None and regle is not None and ia != regle:
        return None
    return ia if ia is not None else regle


def _fusionner(texte: str, compris: dict) -> dict:
    """Croise la réponse de l'IA avec la règle de secours lue dans la phrase."""
    # Produit : l'IA d'abord (« mais » est aussi un mot courant), la règle en secours.
    ia_famille = compris.get("produit") if compris.get("produit") in PRODUITS else None
    famille = ia_famille or trouver_produit(texte)

    ia_variete = compris.get("variete")
    if ia_variete not in VARIETES.get(famille or "", {}):
        ia_variete = None
    variete = _accord(ia_variete, trouver_variete(texte, famille))

    marche = _accord(resoudre_ville_marche(compris.get("marche")), resoudre_ville_marche(texte))

    regle = extraire_offre(texte)
    ia_montant = compris.get("montant_offre")
    if not isinstance(ia_montant, int) or ia_montant <= 0 or not groupes_nombres(texte):
        ia_montant = None  # aucun nombre dans la phrase : montant de l'IA refusé
    montant = _accord(ia_montant, regle["montant"])
    ia_unite = compris.get("unite_offre")
    if regle["unite"] is None:
        ia_unite = None  # aucun mot d'unité (kilo, sac) dans la phrase : on demandera
    unite = _accord(ia_unite, regle["unite"])

    return _resultat(
        None,
        texte,
        intention=compris.get("intention") or "inconnu",
        famille=famille,
        variete=variete,
        marche=marche,
        montant=montant,
        unite=unite,
        # Commune de départ : règle seule (tournure « je suis à … »), jamais devinée.
        commune=trouver_commune(texte),
    )
