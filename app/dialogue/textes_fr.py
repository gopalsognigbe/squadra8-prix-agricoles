"""Toutes les phrases du service. Rien n'est écrit en dur dans moteur.py."""

from __future__ import annotations

from app.dialogue.nombres import date_en_lettres, en_lettres, francs
from app.services.calculs import (
    arrondir_au_franc,
    marche_net_le_plus_eleve,
    marche_prix_le_plus_eleve,
    vers_100kg,
)
from app.services.transport import TOUCHE_COMMUNE  # noqa: F401 — réexporté pour le moteur

# Phrases fixes (mêmes identifiants que app/voix/phrases.csv)
TEXTES = {
    "A01": "Bonjour. Ici le service des prix agricoles. Nos prix viennent du système public d'information sur les marchés et sont vérifiés par une personne.",
    "P00": "Pour le maïs, tapez 1. Pour le soja, tapez 2. Pour le haricot, tapez 3.",
    "M01": "Pour les prix sur 3 marchés, tapez 1.",
    "M02": "Pour juger l'offre d'un acheteur, tapez 2.",
    "M03": "Pour poser votre question à voix haute, tapez 3.",
    "M03B": "Pour poser votre question à voix haute, tapez 3 : bientôt disponible.",
    "M04": "Pour réécouter, tapez 4.",
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
    # Touche 3 (question à voix haute)
    "X02": "Votre question est trop longue. Posez-la en une phrase courte.",
    "X03": "Je peux donner le prix du maïs, du soja ou du haricot, ou juger l'offre d'un acheteur.",
    "V01": "Pour le maïs blanc, tapez 1. Pour le maïs jaune, tapez 2.",
    "V02": "Pour le haricot blanc, tapez 1. Pour le haricot noir, tapez 2. Pour le haricot rouge, tapez 3.",
    "O03": "Je n'ai pas bien compris le montant.",
    "O04": "Si c'est un sac de 100 kilos, tapez 1. Sinon, tapez 2.",
    "D02": "Il n'y a pas de prix récent pour ce produit sur ce marché.",
    "C01": "Pour compter le transport, d'où partez-vous ? Abomey, tapez 1. Agbangnizoun, tapez 2. Bohicon, tapez 3. Covè, tapez 4. Djidja, tapez 5. Ouinhi, tapez 6. Zagnanado, tapez 7. Za-Kpota, tapez 8. Zogbodomey, tapez 9. Autre commune, tapez 0.",
    "O05": "Si c'est le prix d'un kilo, tapez 1. Si c'est le prix d'un sac de 100 kilos, tapez 2. Pour un autre sac, tapez 3.",
}

NOMS_PRODUITS = {
    "mais": "Maïs blanc",
    "soja": "Soja",
    "haricot": "Haricot blanc",
    # Produits précisés par la touche 3 (couleur dite ou choisie par l'appelant).
    "mais blanc": "Maïs blanc",
    "mais jaune": "Maïs jaune",
    "haricot blanc": "Haricot blanc",
    "haricot noir": "Haricot noir",
    "haricot rouge": "Haricot rouge",
}
TOUCHE_PRODUIT = {"1": "mais", "2": "soja", "3": "haricot"}

# Touche 3 : couleur demandée quand l'appelant ne l'a pas dite (jamais devinée).
CHOIX_VARIETES = {
    "mais": ("V01", {"1": "blanc", "2": "jaune"}),
    "haricot": ("V02", {"1": "blanc", "2": "noir", "3": "rouge"}),
}


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


_VERDICTS_MARCHE = {
    "au-dessus": "l'offre est au-dessus de ce prix",
    "proche": "l'offre est proche de ce prix",
    "en dessous": "l'offre est en dessous de ce prix",
}


# Unité de la réponse = unité de l'offre : "kg" (franc par kilo) ou "sac" (sac de 100 kg).
_UNITES = {"kg": ("le kilo", "le kilo"), "sac": ("le sac de cent kilos", "le sac")}


def _en_unite(valeur_kg: float, unite: str) -> int:
    """Montant annoncé, arrondi au franc : au kilo, ou ×100 pour un sac de 100 kg."""
    return arrondir_au_franc(valeur_kg * 100 if unite == "sac" else valeur_kg)


def _f(n: int) -> str:
    return f"{en_lettres(n)} {francs(n)}"


def phrase_offre_kilo(offre_kg: float, unite: str = "kg") -> str:
    offre = _en_unite(offre_kg, unite)
    return f"L'acheteur propose {_f(offre)} {_UNITES[unite][0]}."


_VERDICTS_NET = {
    "au-dessus": "l'offre est au-dessus de ce qui vous resterait",
    "proche": "l'offre est proche de ce qui vous resterait",
    "en dessous": "l'offre est en dessous de ce qui vous resterait",
}


def phrase_offre_marche_transport(c: dict, commune: str, unite: str = "kg") -> str:
    """Prix de détail, date, transport depuis la commune, net et verdict sur le net."""
    ref = _en_unite(c["reference_kg"], unite)
    cout = _en_unite(c["transport_kg"], unite)
    net = _en_unite(c["net_kg"], unite)
    estime = c.get("statut_transport") != "verifie"
    transport = (
        f"Le transport depuis {commune} coûte environ {_f(cout)} {_UNITES[unite][1]}"
        + (", c'est une estimation" if estime else "")
    )
    verdict = _VERDICTS_NET.get(c.get("verdict"), "l'offre a été comparée à ce montant")
    return (
        f"À {c['marche']}, {_UNITES[unite][0]} est à {_f(ref)}, "
        f"relevé le {date_en_lettres(c['date_releve'])}. {transport}. "
        f"Il vous resterait {_f(net)} : {verdict}."
    )


def phrase_offre_marche(c: dict, commune: str | None = None, unite: str = "kg") -> str:
    """Une phrase par marché : prix de détail, date du relevé, verdict."""
    if c.get("reference_kg") is None:
        return f"À {c['marche']}, il n'y a pas de prix récent pour ce produit."
    if c.get("net_kg") is not None and commune:
        return phrase_offre_marche_transport(c, commune, unite)
    ref = _en_unite(c["reference_kg"], unite)
    verdict = _VERDICTS_MARCHE.get(c.get("verdict"), "l'offre a été comparée à ce prix")
    return (
        f"À {c['marche']}, {_UNITES[unite][0]} est à {_f(ref)}, "
        f"relevé le {date_en_lettres(c['date_releve'])} : {verdict}."
    )


def phrases_offre(o: dict, unite: str = "kg") -> list[str]:
    """Annonce l'offre comparée au prix de détail de chaque marché (date du relevé).

    ``unite`` : "kg" (réponse au kilo) ou "sac" (réponse par sac de 100 kilos),
    la même unité que l'offre. Le verdict, lui, ne dépend pas de l'unité.
    """
    if unite not in _UNITES:
        unite = "kg"
    marches = o.get("marches")
    if marches:
        phrases = [phrase_offre_kilo(o["offre_kg"], unite)]
        commune = o.get("commune")
        phrases += [phrase_offre_marche(c, commune, unite) for c in marches]
        meilleur_net = marche_net_le_plus_eleve(marches) if commune else None
        meilleur = marche_prix_le_plus_eleve(marches)
        if meilleur_net:
            phrases.append(f"Après le transport, c'est à {meilleur_net} qu'il vous resterait le plus.")
        elif meilleur:
            phrases.append(f"Le prix de détail le plus élevé est à {meilleur}.")
        return phrases

    # Ancien format (un seul marché) : gardé pour les services qui ne
    # renvoient pas encore « marches ».
    verdict = o.get("verdict", "")
    if verdict == "proche":
        jugement = "L'offre est proche du prix de détail."
    elif verdict == "au-dessus":
        jugement = "L'offre est au-dessus du prix de détail."
    elif verdict == "en dessous":
        jugement = "L'offre est en dessous du prix de détail."
    else:
        jugement = "L'offre a été comparée au prix de détail."

    ref = _en_unite(o["reference_kg"], unite)
    return [
        phrase_offre_kilo(o["offre_kg"], unite),
        (
            f"Au détail, {_UNITES[unite][0]} est à {_f(ref)} "
            f"à {o['marche']}, relevé le {date_en_lettres(o['date_releve'])}."
        ),
        jugement,
    ]


def phrase_offre_sac(montant: int) -> str:
    """Rappelle le montant dit pour un sac dont le poids n'est pas précisé."""
    return f"L'acheteur propose {en_lettres(montant)} {francs(montant)} le sac."


def phrase_offre_montant(montant: int) -> str:
    """Rappelle le montant dit quand l'unité (kilo ou sac) n'est pas précisée."""
    return f"L'acheteur propose {en_lettres(montant)} {francs(montant)}."
