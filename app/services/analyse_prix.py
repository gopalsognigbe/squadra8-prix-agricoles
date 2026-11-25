"""Analyse et annotation des prix proposés avant validation humaine."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Marche, Prix, Produit
from app.ia.anomalies import analyser_prix


def analyser_et_marquer_prix(session: Session, row: Prix) -> dict:
    """Analyse un prix en attente à partir des seules observations validées comparables."""
    produit = session.get(Produit, row.produit_id)
    marche = session.get(Marche, row.marche_id)
    if produit is None or marche is None:
        row.score_anomalie = None
        row.motif_anomalie = "Référentiel produit ou marché introuvable : vérification humaine requise."
        return {"statut": "a_verifier", "raisons": ["REFERENTIEL_MANQUANT"], "motif": row.motif_anomalie}

    base = (
        select(Prix, Marche.nom)
        .join(Marche, Marche.id == Prix.marche_id)
        .where(
            Prix.produit_id == row.produit_id,
            Prix.type_prix == row.type_prix,
            Prix.unite == row.unite,
            Prix.statut == "valide",
            Prix.date_releve < row.date_releve,
        )
    )
    historiques = session.execute(
        base.where(Prix.marche_id == row.marche_id).order_by(Prix.date_releve.desc())
    ).all()
    voisins = session.execute(
        select(Prix, Marche.nom)
        .join(Marche, Marche.id == Prix.marche_id)
        .where(
            Prix.produit_id == row.produit_id,
            Prix.marche_id != row.marche_id,
            Prix.type_prix == row.type_prix,
            Prix.unite == row.unite,
            Prix.statut == "valide",
        )
    ).all()

    historique_data = [
        {"date": p.date_releve, "prix": float(p.prix_fcfa), "valide": True}
        for p, _ in historiques
    ]
    voisins_data = [
        {"date": p.date_releve, "prix": float(p.prix_fcfa), "marche": nom}
        for p, nom in voisins
    ]
    resultat = analyser_prix(
        produit=produit.nom,
        marche=marche.nom,
        date_prix=row.date_releve,
        prix=float(row.prix_fcfa),
        unite=row.unite,
        historique=historique_data,
        voisins=voisins_data,
    )
    # Le moteur ne produit pas de score numérique : ne pas en inventer.
    row.score_anomalie = None
    if resultat["statut"] == "a_verifier":
        codes = ", ".join(resultat["raisons"])
        row.motif_anomalie = f"[{codes}] {resultat['motif']}".strip()
    else:
        row.motif_anomalie = None
    return resultat
