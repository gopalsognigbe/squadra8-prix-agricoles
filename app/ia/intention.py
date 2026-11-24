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
from typing import Any, Literal

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import get_settings
from app.ia.regles import comprendre_par_regles

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 3.0
Sources = Literal["groq", "gemini", "regles"]
Intentions = Literal["prix", "juger_offre", "autre", "inconnu"]

SYSTEM_PROMPT = """Tu analyses une phrase d'un producteur agricole du Bénin (département du Zou).
Tu renvoies UNIQUEMENT un objet JSON valide, sans markdown, avec exactement ces clés :
- intention : "prix" | "juger_offre" | "autre" | "inconnu"
- produit : code parmi "mais", "soja", "haricot", ou null si absent / flou
- marche : code parmi "bohicon", "abomey", "cove", ou null si absent / flou
- confiance : nombre entre 0 et 1

Interdits : ne donne jamais de prix, de montant, de devise, ni de conseil d'achat/vente.
Si la demande est hors sujet, intention = "autre".
Si tu ne comprends pas, intention = "inconnu".

Règle d'intention :
- "prix" : le producteur demande le cours, sans qu'on lui propose un montant.
- "juger_offre" : quelqu'un propose un montant (francs, sac, kilo) et demande si c'est bon, correct, ou s'il faut accepter.
Une demande de cours sans montant proposé reste "prix".

Exemples :
- "quel est le prix du maïs à Bohicon" → intention "prix"
- "on me propose 12 000 francs le sac de maïs à Bohicon, c'est bon" → intention "juger_offre"
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

    @field_validator("produit", "marche", mode="before")
    @classmethod
    def _vide_vers_none(cls, value: Any) -> Any:
        if value is None:
            return None
        text = str(value).strip().lower()
        return text or None


def _client(api_key: str, base_url: str) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=TIMEOUT_SECONDS,
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
) -> IntentionResult:
    if not api_key:
        raise RuntimeError(f"clé API manquante pour {source}")

    response = _client(api_key, base_url).chat.completions.create(
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


def _appeler_groq(texte: str) -> IntentionResult:
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
    )


def _appeler_gemini(texte: str) -> IntentionResult:
    settings = get_settings()
    return _appeler_llm(
        texte,
        api_key=settings.gemini_api_key,
        base_url=settings.gemini_base_url,
        model=settings.gemini_model,
        source="gemini",
    )


def comprendre(texte: str) -> dict:
    """Retourne l'intention, le produit et le marché, sans aucun prix.

    Ordre : Groq → Gemini (si clé) → règles de secours.
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

    try:
        return _appeler_groq(texte).model_dump()
    except _ERREURS_LLM as exc:
        logger.warning("Groq indisponible ou réponse invalide : %s", exc)

    settings = get_settings()
    if settings.gemini_api_key:
        try:
            return _appeler_gemini(texte).model_dump()
        except _ERREURS_LLM as exc:
            logger.warning("Gemini indisponible ou réponse invalide, repli sur règles : %s", exc)
    else:
        logger.warning("Pas de clé Gemini, repli sur règles")

    return comprendre_par_regles(texte)
