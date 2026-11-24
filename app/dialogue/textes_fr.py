"""Toutes les phrases du service. Rien n'est écrit en dur dans moteur.py."""

from __future__ import annotations

from app.dialogue.nombres import date_en_lettres, en_lettres, francs
from app.services.calculs import arrondir_au_franc, vers_100kg

# Phrases fixes (mêmes identifiants que app/voix/phrases.csv)
TEXTES = {
    "A01": "Bonjour. Ici le service des prix agricoles. Nos prix viennent du système public d'information sur les marchés et sont vérifiés par une personne.",
    "P00": "Pour le maïs, tapez 1. Pour le soja, tapez 2. Pour le haricot, tapez 3.",
    "M01": "Pour les prix sur 3 marchés, tapez 1.",
    "M02": "Pour juger l'offre d'un acheteur, tapez 2.",
    "M03": "Pour poser votre question à voix haute, tapez 3.",
    "M03B": "Pour poser votre question à voix haute, tapez 3 : bientôt disponible.",
    "M04": "Pour réécouter, tapez 4.",
    "R01": "Pour une autre information, tapez 1, 2 ou 3. Pour réécouter, tapez 4.",
    "V05": "Cette fonction arrive bientôt.",
    # Ajoutées pour le moteur
    "AV01": "Ce prix est un repère, pas une garantie.",
    "AV02": "Source : le système public d'information sur les marchés du Bénin.",
    "E01": "Cette touche n'est pas valide.",
    "S01": "Je n'ai rien entendu.",
    "N01": "Je n'ai pas compris.",
    "F01": "Merci de votre appel. Au revoir.",
    "O01": "Tapez le prix proposé pour un sac de 100 kilos, puis dièse.",
    "O02": "Ce montant n'est pas valide.",
    "X01": "Posez votre question après le bip.",
    "D01": "Il n'y a pas de prix récent pour ce produit.",
}

NOMS_PRODUITS = {"mais": "Maïs blanc", "soja": "Soja", "haricot": "Haricot blanc"}
TOUCHE_PRODUIT = {"1": "mais", "2": "soja", "3": "haricot"}


def _prix_annonce_kg(p: dict) -> int:
    """Prix au kilo annoncé : franc le plus proche (pas aux 5 F)."""
    return arrondir_au_franc(p.get("prix_kg", p["prix_fcfa"]))


def phrase_entete_prix(produit: str) -> str:
    return f"{NOMS_PRODUITS[produit]}, prix de détail au kilo."


def phrase_marche(p: dict) -> str:
    prix = _prix_annonce_kg(p)
    return (
        f"{p['marche']} : {en_lettres(prix)} {francs(prix)}, "
        f"relevé le {date_en_lettres(p['date_releve'])}."
    )


def phrase_cent_kilos(p: dict) -> str:
    if p.get("prix_100kg") is not None:
        total = int(p["prix_100kg"])
    else:
        total = vers_100kg(float(p.get("prix_kg", p["prix_fcfa"])))
    return (
        f"Soit environ {en_lettres(total)} francs pour cent kilos "
        f"au prix de détail à {p['marche']}."
    )


def phrases_offre(o: dict) -> list[str]:
    """Annonce l'offre avec le verdict de juger_offre et la date du relevé."""
    verdict = o.get("verdict", "")
    if verdict == "proche":
        jugement = "L'offre est proche du prix de détail."
    elif verdict == "au-dessus":
        jugement = "L'offre est au-dessus du prix de détail."
    elif verdict == "en dessous":
        jugement = "L'offre est en dessous du prix de détail."
    else:
        jugement = "L'offre a été comparée au prix de détail."

    ref = float(o["reference_kg"])
    offre = float(o["offre_kg"])
    return [
        f"L'acheteur propose {en_lettres(offre)} {francs(offre)} le kilo.",
        (
            f"Au détail, le kilo est à {en_lettres(ref)} {francs(ref)} "
            f"à {o['marche']}, relevé le {date_en_lettres(o['date_releve'])}."
        ),
        jugement,
    ]
