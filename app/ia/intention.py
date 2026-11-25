"""Comprend l'intention via Groq, puis Gemini, puis règles. Jamais de prix.

Responsable : Gopal.

Ordre de secours : Groq → Gemini → règles (app/ia/regles.py).
Règle : l'IA comprend seulement (intention, produit, marché).
Les prix viennent ensuite de la base, jamais du modèle.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Literal

from openai import OpenAI, OpenAIError, RateLimitError
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import get_settings
from app.ia.delais import (
    TIMEOUT_MIN_S,
    attente_429,
    nouvelle_echeance,
    reessai_possible,
    restant,
)
from app.ia.regles import comprendre_par_regles

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 3.0
Sources = Literal["groq", "gemini", "regles"]
Intentions = Literal["prix", "juger_offre", "autre", "inconnu"]
VARIETES_IA = {"blanc", "jaune", "noir", "rouge"}
UNITES_IA = {"kg", "100kg", "sac"}

SYSTEM_PROMPT = """Tu analyses une phrase d'un producteur agricole du Bénin (département du Zou).
Tu renvoies UNIQUEMENT un objet JSON valide, sans markdown, avec exactement ces clés :
- intention : "prix" | "juger_offre" | "autre" | "inconnu"
- produit : code parmi "mais", "soja", "haricot", ou null si absent / flou
- marche : code parmi "bohicon", "abomey", "cove", ou null si absent / flou
  (le marché Houndjro est à Abomey → "abomey" ; le marché Azogotchébou est à Covè → "cove")
- variete : couleur dite parmi "blanc", "jaune" (maïs), "blanc", "noir", "rouge" (haricot),
  ou null si la couleur n'est pas dite. Ne devine jamais la couleur.
- montant_offre : pour "juger_offre" seulement, le montant en francs que l'appelant dit
  qu'on lui propose, en nombre entier (« quinze mille » → 15000, « 15 000 » → 15000),
  sinon null. Recopie seulement ce qui est dit, n'invente jamais de montant.
- unite_offre : "kg" (le kilo), "100kg" (sac de 100 kilos), "sac" (sac sans poids
  ou d'un autre poids), ou null.
- confiance : nombre entre 0 et 1

Interdits : ne donne jamais de prix de marché, de devise, ni de conseil d'achat/vente.
Si la demande est hors sujet, intention = "autre".
Si tu ne comprends pas, intention = "inconnu".

Règle d'intention :
- "prix" : le producteur demande le cours, sans qu'on lui propose un montant.
- "juger_offre" : quelqu'un propose un montant (francs, sac, kilo) et demande si c'est bon, correct, ou s'il faut accepter.
Une demande de cours sans montant proposé reste "prix".

Exemples :
- "quel est le prix du maïs à Bohicon" → intention "prix"
- "on me propose 12 000 francs le sac de maïs à Bohicon, c'est bon" → intention "juger_offre", montant_offre 12000, unite_offre "sac"
- "le prix du maïs jaune à Houndjro" → intention "prix", produit "mais", variete "jaune", marche "abomey"
- "à Covè on m'offre vingt-cinq mille cinq cents francs le sac de haricot rouge" → intention "juger_offre", produit "haricot", variete "rouge", marche "cove", montant_offre 25500, unite_offre "sac"
- "l'acheteur dit 15 000 francs le sac, est-ce que je dois accepter" → intention "juger_offre"
- "le client veut me payer 130 francs le kilo, c'est correct" → intention "juger_offre"
"""

_ERREURS_LLM = (OpenAIError, ValidationError, ValueError, RuntimeError, TimeoutError)


class IntentionResult(BaseModel):
    """Sortie structurée : compréhension seule, aucun prix."""

    intention: Intentions
    produit: str | None = None
    marche: str | None = None
    confiance: float = Field(default=0.0, ge=0.0, le=1.0)
    source: Sources = "groq"
    # Touche 3 : couleur et offre DITES par l'appelant (jamais un prix de marché).
    variete: str | None = None
    montant_offre: int | None = None
    unite_offre: str | None = None

    @field_validator("variete", mode="before")
    @classmethod
    def _variete_connue(cls, value: Any) -> Any:
        texte = str(value or "").strip().lower()
        return texte if texte in VARIETES_IA else None

    @field_validator("unite_offre", mode="before")
    @classmethod
    def _unite_connue(cls, value: Any) -> Any:
        texte = str(value or "").strip().lower().replace(" ", "")
        return texte if texte in UNITES_IA else None

    @field_validator("montant_offre", mode="before")
    @classmethod
    def _montant_entier(cls, value: Any) -> Any:
        # Valeur illisible → None (la règle de secours ou le clavier prennent le relais).
        try:
            montant = int(round(float(str(value).replace(" ", "").replace(",", "."))))
        except (TypeError, ValueError):
            return None
        return montant if 0 < montant < 10_000_000 else None

    @field_validator("produit", "marche", mode="before")
    @classmethod
    def _vide_vers_none(cls, value: Any) -> Any:
        if value is None:
            return None
        text = str(value).strip().lower()
        return text or None


def _client(api_key: str, base_url: str, timeout: float = TIMEOUT_SECONDS) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=0,
    )


def _extraire_json(texte: str) -> dict[str, Any]:
    """Récupère un objet JSON même s'il est entouré de texte parasite."""
    texte = texte.strip()
    try:
        data = json.loads(texte)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", texte, flags=re.DOTALL)
    if not match:
        raise ValueError("pas de JSON dans la réponse du modèle")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("JSON non objet")
    return data


def _appeler_llm(
    texte: str,
    *,
    api_key: str,
    base_url: str,
    model: str,
    source: Sources,
    extra_options: dict[str, Any] | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> IntentionResult:
    if not api_key:
        raise RuntimeError(f"clé API manquante pour {source}")

    response = _client(api_key, base_url, timeout).chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": texte.strip()},
        ],
        temperature=0,
        max_tokens=400,
        **(extra_options or {}),
    )
    brut = (response.choices[0].message.content or "").strip()
    data = _extraire_json(brut)
    # Sécurité : si le modèle glisse un prix, on l'ignore (clés non prévues).
    data.pop("prix", None)
    data.pop("montant", None)
    data.pop("price", None)
    return IntentionResult.model_validate({**data, "source": source})


def _appeler_groq(texte: str, timeout: float = TIMEOUT_SECONDS) -> IntentionResult:
    settings = get_settings()
    options: dict[str, Any] = {}
    if settings.llm_reasoning_effort:
        options["reasoning_effort"] = settings.llm_reasoning_effort
    return _appeler_llm(
        texte,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.openai_model,
        source="groq",
        extra_options=options,
        timeout=timeout,
    )


def _appeler_gemini(texte: str, timeout: float = TIMEOUT_SECONDS) -> IntentionResult:
    settings = get_settings()
    return _appeler_llm(
        texte,
        api_key=settings.gemini_api_key,
        base_url=settings.gemini_base_url,
        model=settings.gemini_model,
        source="gemini",
        timeout=timeout,
    )


def _dans_le_budget(appel, texte: str, echeance: float) -> IntentionResult:
    """Appel LLM au délai raccourci ; un seul réessai court après un 429."""
    for essai in range(2):
        timeout = min(TIMEOUT_SECONDS, restant(echeance))
        if timeout < TIMEOUT_MIN_S:
            raise TimeoutError("plus de temps pour le LLM, repli")
        try:
            return appel(texte, timeout=timeout)
        except RateLimitError as exc:
            if essai == 1:
                raise
            reponse = getattr(exc, "response", None)
            attente = attente_429(getattr(reponse, "headers", None))
            if not reessai_possible(attente, echeance):
                raise
            logger.info("429 sur l'intention, réessai dans %.2f s", attente)
            time.sleep(attente)
    raise RuntimeError("inaccessible")


def comprendre(texte: str, echeance: float | None = None) -> dict:
    """Retourne l'intention, le produit et le marché, sans aucun prix.

    Ordre : Groq → Gemini (si clé) → règles de secours.
    echeance (time.monotonic) : fin du budget de la question ; passé ce délai,
    on saute directement aux règles.
    """
    texte = (texte or "").strip()
    if not texte:
        return IntentionResult(
            intention="inconnu",
            produit=None,
            marche=None,
            confiance=0.0,
            source="regles",
        ).model_dump()

    echeance = echeance if echeance is not None else nouvelle_echeance()
    try:
        return _dans_le_budget(_appeler_groq, texte, echeance).model_dump()
    except _ERREURS_LLM as exc:
        logger.warning("Groq indisponible ou réponse invalide : %s", exc)

    settings = get_settings()
    if settings.gemini_api_key:
        try:
            return _dans_le_budget(_appeler_gemini, texte, echeance).model_dump()
        except _ERREURS_LLM as exc:
            logger.warning("Gemini indisponible ou réponse invalide, repli sur règles : %s", exc)
    else:
        logger.warning("Pas de clé Gemini, repli sur règles")

    return comprendre_par_regles(texte)
