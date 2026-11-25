"""Repli sans IA : mots-clés et noms de marchés approchés.

Responsable : Gopal.
"""

from __future__ import annotations

import difflib
import re
import unicodedata


PRODUITS = {
    "mais": ("mais", "maïs"),
    "soja": ("soja", "soy"),
    "haricot": ("haricot", "haricots", "niebe", "niébé"),
}

MARCHES = {
    "bohicon": ("bohicon", "bohikon"),
    "abomey": ("abomey", "abomé", "abome", "houndjro", "houndjoro"),
    "cove": ("cove", "covè", "kove", "azogotchebou", "azogotchébou"),
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


def trouver_produit(texte: str) -> str | None:
    """Famille de produit dite : "mais", "soja", "haricot" ou None."""
    return _trouver(PRODUITS, _normaliser(texte or ""))


_MOTS_ARGENT = re.compile(r"\b(?:francs?|f|fcfa|cfa|sacs?|kilos?|kg)\b")


def _montant_d_offre(n: str, produit: str | None) -> bool:
    """Un montant (≥ 10, pas un poids) avec un mot d'argent, d'unité ou un produit → offre.

    Une demande de prix ne contient pas de montant : « quinze mille pour le soja » en contient un.
    """
    if montant_en_francs(n) is None:
        return False
    return bool(_MOTS_ARGENT.search(n)) or produit is not None


def comprendre_par_regles(texte: str) -> dict:
    """Retourne l'intention à partir de mots-clés (secours si Groq échoue)."""
    brut = texte or ""
    n = _normaliser(brut)

    produit = _trouver(PRODUITS, n)
    marche = _trouver(MARCHES, n)
    if marche is None:
        # Variantes et fautes de transcription (houndjoro, kove…).
        fao = resoudre_ville_marche(brut)
        marche = next((c for c, nom in MARCHES_FAO.items() if nom == fao), None)

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
            # Ajouts touche 3 (offres classées « prix » au G8 après des 429)
            "offert",
            "acheteur",
            "commercant",
            "c'est bien",
            "c est bien",
            "vends ou pas",
            "vendre ou pas",
            "je dois vendre",
            "dois je vendre",
            "je vends ?",
        )
    ) or _montant_d_offre(n, produit):
        intention = "juger_offre"
    elif any(m in n for m in ("prix", "coute", "coûte", "combien", "tarif", "cours")):
        intention = "prix"
    elif produit or marche:
        intention = "prix"
    else:
        intention = "inconnu"

    offre = extraire_offre(brut)
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
        "variete": trouver_variete(brut, produit),
        "montant_offre": offre["montant"] if intention == "juger_offre" else None,
        "unite_offre": offre["unite"] if intention == "juger_offre" else None,
    }


# ---------- Touche 3 : précisions lues dans la phrase transcrite ----------
# Couleurs possibles par famille (noms FAO : Maïs Blanc/Jaune, Haricot blanc/noir/rouge).
VARIETES = {
    "mais": {"blanc": ("blanc", "blancs", "blanche"), "jaune": ("jaune", "jaunes")},
    "haricot": {
        "blanc": ("blanc", "blancs", "blanche", "blanches"),
        "noir": ("noir", "noirs", "noire", "noires"),
        "rouge": ("rouge", "rouges"),
    },
}

# Ville ↔ marché FAO, dans les deux sens. Variantes d'orthographe et de
# transcription tolérées (après normalisation : minuscules, sans accents).
MARCHES_FAO = {
    "bohicon": "Bohicon",
    "abomey": "Houndjro (Abomey)",
    "cove": "Azogotchébou (Covè)",
}
VILLE_DU_MARCHE = {
    "Bohicon": "Bohicon",
    "Houndjro (Abomey)": "Abomey",
    "Azogotchébou (Covè)": "Covè",
}
VARIANTES_MARCHES = {
    "bohicon": (
        "bohicon", "bohikon", "boicon", "boikon", "gbohicon", "bohicone",
        "abohicon", "aboicon", "abouicon", "abouicons",
    ),
    "abomey": (
        "abomey", "abome", "abomei", "abomay", "agbome", "agbomey",
        "houndjro", "houndjoro", "hounjro", "houndjro abomey", "hundjro", "houndro",
        "hondjro", "oundjro", "rondjro", "rondjort",
    ),
    "cove": (
        "cove", "kove", "covet", "kovet", "coveh", "covey", "acove", "akove",
        "azogotchebou", "azogotchebu", "azogochebou", "azongotchebou", "azogotcheboue",
        "azogo", "azogotche", "azogotebou",
    ),
}


def resoudre_ville_marche(valeur: str | None) -> str | None:
    """Ville ou marché dit (ou code IA) → nom FAO exact, sinon None.

    « Abomey », « abomé », « Houndjro » → « Houndjro (Abomey) » ;
    « Covè », « kove », « Azogotchébou » → « Azogotchébou (Covè) ».
    Deux marchés différents dans la même phrase → None (on ne choisit pas).
    """
    n = _normaliser(valeur or "")
    if not n:
        return None
    n = re.sub(r"[^a-z0-9]+", " ", n).strip()
    trouves: set[str] = set()
    for code, variantes in VARIANTES_MARCHES.items():
        if any(re.search(r"\b" + re.escape(v) + r"\b", n) for v in variantes):
            trouves.add(code)
    if not trouves:
        # Mots longs mal transcrits (houndjoro, azogotcheboux…) : proximité.
        longues = {v: c for c, vs in VARIANTES_MARCHES.items() for v in vs if len(v) >= 6}
        for mot in n.split():
            if len(mot) >= 6:
                proche = difflib.get_close_matches(mot, list(longues), n=1, cutoff=0.8)
                if proche:
                    trouves.add(longues[proche[0]])
    return MARCHES_FAO[trouves.pop()] if len(trouves) == 1 else None


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


# ---------- montants en chiffres ou en lettres ----------
_UNITES = {
    "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12,
    "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20,
    "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60,
    "septante": 70, "huitante": 80, "octante": 80, "nonante": 90,
}
_MULTIPLICATEURS = {"cent": 100, "cents": 100, "mille": 1000, "milles": 1000,
                    "million": 1_000_000, "millions": 1_000_000}
_POIDS = {"kg", "kilo", "kilos", "kilogramme", "kilogrammes"}
MONTANT_MIN = 10  # « deux sacs », « un acheteur » ne sont pas des montants


def _est_nombre(mot: str) -> bool:
    return mot.isdigit() or mot in _UNITES or mot in _MULTIPLICATEURS


def _valeur(mots: list[str]) -> int:
    """['vingt', 'cinq', 'mille', 'cinq', 'cents'] → 25500 ; accepte « 15 mille »."""
    total, courant, precedent = 0, 0, ""
    for mot in mots:
        if mot.isdigit():
            courant += int(mot)
        elif mot in ("vingt", "vingts") and precedent == "quatre":
            courant += 76  # quatre-vingt(s) = 4 + 76
        elif mot in _UNITES:
            courant += _UNITES[mot]
        elif mot in ("cent", "cents"):
            courant = (courant or 1) * 100
        elif mot in ("mille", "milles"):
            total += (courant or 1) * 1000
            courant = 0
        elif mot in ("million", "millions"):
            total += (courant or 1) * 1_000_000
            courant = 0
        precedent = mot
    return total + courant


def groupes_nombres(texte: str) -> list[tuple[int, str]]:
    """Suites de mots-nombres → (valeur, mot qui suit)."""
    n = _normaliser(texte or "")
    # « 12 000 », « 12.000 », « 12 000 » → « 12000 »
    n = re.sub(r"(?<=\d)[ .\u00a0\u202f](?=\d{3}\b)", "", n)
    mots = re.findall(r"[a-z]+|\d+", n.replace("-", " "))
    groupes: list[tuple[int, str]] = []
    i = 0
    while i < len(mots):
        if not _est_nombre(mots[i]):
            i += 1
            continue
        j = i
        suite: list[str] = []
        while j < len(mots) and (
            _est_nombre(mots[j])
            or (mots[j] == "et" and suite and j + 1 < len(mots) and _est_nombre(mots[j + 1]))
        ):
            if mots[j] != "et":
                suite.append(mots[j])
            j += 1
        if not all(m in ("un", "une") for m in suite):
            groupes.append((_valeur(suite), mots[j] if j < len(mots) else ""))
        i = j
    return groupes


def montant_en_francs(texte: str) -> int | None:
    """Montant dit (« quinze mille », « 15 000 », « 15 mille ») ou None.

    Les poids (« 100 kilos ») sont ignorés. Plusieurs montants différents → None.
    """
    montants = {
        v for v, suivant in groupes_nombres(texte)
        if suivant not in _POIDS and v >= MONTANT_MIN
    }
    return montants.pop() if len(montants) == 1 else None


def extraire_offre(texte: str) -> dict:
    """Montant proposé et unité, lus dans la transcription (règle de secours).

    unite : "kg" (le kilo), "100kg" (sac de 100 kilos), "sac" (poids non dit
    ou autre poids) ou None.
    """
    n = _normaliser(texte or "")
    poids = [v for v, suivant in groupes_nombres(texte) if suivant in _POIDS]
    if 100 in poids and len(set(poids)) == 1:
        unite = "100kg"
    elif re.search(r"\bsacs?\b", n):
        unite = "sac"
    elif re.search(r"\b(?:kg|kilos?|kilogrammes?)\b", n):
        unite = "kg"
    else:
        unite = None
    return {"montant": montant_en_francs(texte), "unite": unite}
