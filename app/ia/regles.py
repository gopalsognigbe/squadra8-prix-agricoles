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


# ---------- Touche 3 : précisions lues dans la phrase transcrite ----------
# Couleurs possibles par famille (noms FAO : Maïs Blanc/Jaune, Haricot blanc/noir/rouge).
VARIETES = {
    "mais": {"blanc": ("blanc", "blanche"), "jaune": ("jaune",)},
    "haricot": {
        "blanc": ("blanc", "blancs", "blanche"),
        "noir": ("noir", "noirs"),
        "rouge": ("rouge", "rouges"),
    },
}

_NOMBRE = re.compile(r"\d{1,3}(?:[ \u00a0\u202f.]\d{3})+|\d+")
_CENT_KILOS = re.compile(r"\b(?:100|cent)\s*(?:kg|kilos?|kilogrammes?)\b")
_KILO = re.compile(r"\b(?:kg|kilos?|kilogrammes?)\b")


def trouver_variete(texte: str, famille: str | None) -> str | None:
    """Couleur dite pour le maïs ou le haricot ; None si absente ou ambiguë.

    Ne devine jamais : deux couleurs différentes dans la phrase → None.
    """
    if famille not in VARIETES:
        return None
    n = _normaliser(texte or "")
    trouvees = {
        code
        for code, mots in VARIETES[famille].items()
        if any(re.search(r"\b" + re.escape(m) + r"\b", n) for m in mots)
    }
    return trouvees.pop() if len(trouvees) == 1 else None


def extraire_offre(texte: str) -> dict:
    """Montant proposé (en chiffres) et unité, lus dans la transcription.

    unite : "kg" (le kilo), "100kg" (sac de 100 kilos), "sac" (taille non dite)
    ou None. montant None si aucun nombre ou plusieurs montants différents.
    Les nombres collés à « kilo » (ex. « 100 kilos ») ne sont pas des montants.
    """
    n = _normaliser(texte or "")
    cent_kilos = bool(_CENT_KILOS.search(n))
    sans_poids = _CENT_KILOS.sub(" ", n)
    montants = {
        int(re.sub(r"\D", "", m.group(0)))
        for m in _NOMBRE.finditer(sans_poids)
    }
    montants.discard(0)
    montant = montants.pop() if len(montants) == 1 else None

    if cent_kilos:
        unite = "100kg"
    elif re.search(r"\bsacs?\b", n):
        unite = "sac"
    elif _KILO.search(sans_poids):
        unite = "kg"
    else:
        unite = None
    return {"montant": montant, "unite": unite}
