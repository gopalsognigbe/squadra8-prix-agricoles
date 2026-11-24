"""Repli sans IA : mots-clés et noms de marchés approchés.

Responsable : Gopal.
"""

from __future__ import annotations

import re
import unicodedata


PRODUITS = {
    "mais": ("mais", "maïs"),
    "soja": ("soja", "soy"),
    "haricot": ("haricot", "haricots", "niebe", "niébé"),
}

MARCHES = {
    "bohicon": ("bohicon",),
    "abomey": ("abomey", "abomé"),
    "cove": ("cove", "covè"),
    # 4e marché : pas encore décidé
}


def _normaliser(texte: str) -> str:
    texte = texte.lower().strip()
    texte = unicodedata.normalize("NFD", texte)
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


def _trouver(code_vers_mots: dict[str, tuple[str, ...]], texte: str) -> str | None:
    for code, mots in code_vers_mots.items():
        for mot in mots:
            motif = r"\b" + re.escape(_normaliser(mot)) + r"\b"
            if re.search(motif, texte):
                return code
    return None


def comprendre_par_regles(texte: str) -> dict:
    """Retourne l'intention à partir de mots-clés (secours si Groq échoue)."""
    brut = texte or ""
    n = _normaliser(brut)

    produit = _trouver(PRODUITS, n)
    marche = _trouver(MARCHES, n)

    if any(
        m in n
        for m in (
            "juger",
            "offre",
            "propose",
            "proposition",
            "acheter a",
            "c'est bon",
            "c est bon",
            "c'est correct",
            "c est correct",
            "accepter",
            "me payer",
            "bon prix",
        )
    ):
        intention = "juger_offre"
    elif any(m in n for m in ("prix", "coute", "coûte", "combien", "tarif", "cours")):
        intention = "prix"
    elif produit or marche:
        intention = "prix"
    else:
        intention = "inconnu"

    confiance = 0.55 if intention != "inconnu" else 0.2
    if produit:
        confiance += 0.15
    if marche:
        confiance += 0.15

    return {
        "intention": intention,
        "produit": produit,
        "marche": marche,
        "confiance": min(confiance, 0.9),
        "source": "regles",
    }
