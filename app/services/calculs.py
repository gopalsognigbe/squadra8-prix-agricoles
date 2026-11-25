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


def comparer_offre_marches(
    offre_kg: float,
    liste: list[dict],
    ordre: tuple[str, ...] | list[str],
    marche_dit: str | None = None,
    transport=None,
) -> list[dict]:
    """Compare l'offre (F/kg) au prix de détail de chaque marché de ``ordre``.

    ``liste`` : prix disponibles (un par marché, clé ``prix_kg`` ou ``prix_fcfa``).
    Le marché dit (touche 3) passe en premier, puis les autres dans l'ordre.
    Un marché sans prix est rendu avec ``reference_kg = None`` : aucun prix
    n'est jamais inventé. Les seuils restent ceux de :func:`juger_offre`.

    ``transport(marche) -> dict | None`` (optionnel) : coût estimé ou vérifié
    depuis la commune de l'appelant (clés ``cout_kg`` et ``statut``). S'il est
    connu, le verdict compare l'offre au NET (prix de détail − transport) ;
    le verdict sur le prix brut reste dans ``verdict_brut``. Sans coût : rien
    ne change.
    """
    par_marche = {p["marche"]: p for p in liste}
    noms = list(ordre)
    for p in liste:  # marché présent dans les données mais hors de l'ordre
        if p["marche"] not in noms:
            noms.append(p["marche"])
    if marche_dit in noms:
        noms.remove(marche_dit)
        noms.insert(0, marche_dit)

    resultat: list[dict] = []
    for nom in noms:
        p = par_marche.get(nom)
        if p is None:
            resultat.append({"marche": nom, "reference_kg": None, "date_releve": None,
                             "verdict": None})
            continue
        ref = float(p.get("prix_kg", p.get("prix_fcfa")))
        ligne = {
            "marche": nom,
            "reference_kg": ref,
            "date_releve": p["date_releve"],
            **juger_offre(offre_kg, ref),
        }
        cout = transport(nom) if transport else None
        if cout is not None:
            net = ref - float(cout["cout_kg"])
            if net > 0:
                ligne["verdict_brut"] = ligne["verdict"]
                ligne.update(juger_offre(offre_kg, net))
                ligne.update({
                    "transport_kg": float(cout["cout_kg"]),
                    "statut_transport": cout.get("statut", "estime"),
                    "net_kg": net,
                })
        resultat.append(ligne)
    return resultat


def marche_net_le_plus_eleve(comparaisons: list[dict]) -> str | None:
    """Marché où il resterait le plus après transport (au franc), s'il est seul en tête."""
    avec_net = [c for c in comparaisons if c.get("net_kg") is not None]
    if len(avec_net) < 2:
        return None
    tries = sorted(avec_net, key=lambda c: arrondir_au_franc(c["net_kg"]), reverse=True)
    if arrondir_au_franc(tries[0]["net_kg"]) == arrondir_au_franc(tries[1]["net_kg"]):
        return None
    return tries[0]["marche"]


def marche_prix_le_plus_eleve(comparaisons: list[dict]) -> str | None:
    """Marché au prix de détail le plus élevé (au franc), s'il est seul en tête.

    Rien si moins de deux marchés ont un prix, ou en cas d'égalité.
    """
    avec_prix = [c for c in comparaisons if c.get("reference_kg") is not None]
    if len(avec_prix) < 2:
        return None
    tries = sorted(avec_prix, key=lambda c: arrondir_au_franc(c["reference_kg"]), reverse=True)
    if arrondir_au_franc(tries[0]["reference_kg"]) == arrondir_au_franc(tries[1]["reference_kg"]):
        return None
    return tries[0]["marche"]
