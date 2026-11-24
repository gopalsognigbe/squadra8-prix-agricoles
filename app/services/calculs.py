"""Écart de l'offre, conversion kilo ↔ 100 kg, arrondis.

Responsable : Gopal.
"""

from __future__ import annotations


def arrondir_f(montant: float) -> int:
    """Arrondit aux 5 F les plus proches (hors annonces de prix)."""
    return int(round(montant / 5.0) * 5)


def arrondir_au_franc(montant: float) -> int:
    """Arrondit au franc le plus proche (annonces vocales et affichages)."""
    return int(round(float(montant)))


def vers_100kg(prix_kg: float) -> int:
    """Prix pour 100 kg au prix de détail (F), sans coefficient inventé."""
    return int(round(prix_kg * 100))


def juger_offre(offre_kg: float, prix_detail_kg: float) -> dict:
    """Compare l'offre au prix de détail, tous deux en F par kilo.

    Renvoie ecart_f, ecart_pct et verdict :
    - « au-dessus » si l'offre dépasse le prix de 5 % ou plus ;
    - « proche » entre −5 % et +5 % (bornes incluses sauf +5 % → au-dessus) ;
    - « en dessous » sinon.

    Lève ValueError si un des deux montants est absent ou ≤ 0.
    """
    if offre_kg is None or prix_detail_kg is None:
        raise ValueError("offre_kg et prix_detail_kg sont requis")
    if offre_kg <= 0 or prix_detail_kg <= 0:
        raise ValueError("offre_kg et prix_detail_kg doivent être > 0")

    ecart_f = offre_kg - prix_detail_kg
    ecart_pct = (ecart_f / prix_detail_kg) * 100.0

    if ecart_pct >= 5.0:
        verdict = "au-dessus"
    elif ecart_pct < -5.0:
        verdict = "en dessous"
    else:
        # −5 % ≤ écart < +5 %
        verdict = "proche"

    return {
        "ecart_f": ecart_f,
        "ecart_pct": ecart_pct,
        "verdict": verdict,
    }
