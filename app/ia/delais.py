"""Budget de temps d'une question vocale (critère G8 : réponse en moins de 6 s).

Une question = transcription + intention. Les deux partagent une échéance
(time.monotonic). Les appels réseau raccourcissent leur délai pour la respecter,
et un 429 (quota) n'est réessayé qu'une fois, si l'attente tient dans le budget.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

from app.config import get_settings

DELAI_MAX_DEFAUT_S = 5.5
ATTENTE_429_DEFAUT_S = 0.75
TIMEOUT_MIN_S = 0.5  # en dessous, un appel réseau n'a aucune chance : on passe au repli


def nouvelle_echeance() -> float:
    delai = getattr(get_settings(), "ia_delai_max_s", DELAI_MAX_DEFAUT_S)
    return time.monotonic() + float(delai)


def restant(echeance: float) -> float:
    return echeance - time.monotonic()


def attente_429(entetes: Mapping[str, str] | None) -> float:
    """Attente demandée par le serveur (Retry-After en secondes), sinon 0,75 s."""
    entetes = entetes or {}
    for cle in ("retry-after", "Retry-After"):
        valeur = entetes.get(cle)
        if valeur is None:
            continue
        try:
            return max(0.0, float(str(valeur).strip().rstrip("s")))
        except ValueError:
            break
    return ATTENTE_429_DEFAUT_S


def reessai_possible(attente: float, echeance: float, reserve: float = 0.0) -> bool:
    """Vrai si l'on peut attendre puis refaire un appel utile avant l'échéance."""
    maxi = float(getattr(get_settings(), "groq_reessai_max_s", 1.5))
    return attente <= maxi and restant(echeance) - attente - reserve >= TIMEOUT_MIN_S
