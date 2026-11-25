"""Adaptateur : Services du moteur ← get_source_prix() (plan B FAO) et IA touche 3."""

from __future__ import annotations

from app.dialogue.moteur import Services
from app.dialogue.question_voix import analyser_question
from app.services.calculs import comparer_offre_marches
from app.services.source_prix import ORDRE_MARCHES, get_source_prix


def services_reels() -> Services:
    """Construit l'objet Services branché sur la source de prix configurée."""

    def prix(produit: str) -> list[dict]:
        return get_source_prix().prix_du_jour(produit)

    def offre(produit: str, montant_sac: float, marche: str | None = None) -> dict | None:
        liste = get_source_prix().prix_du_jour(produit)
        if not liste:
            return None
        offre_kg = float(montant_sac) / 100.0
        # Offre comparée aux 3 marchés (marché dit à la touche 3 en premier).
        # Un marché sans prix récent est signalé, jamais complété.
        marches = comparer_offre_marches(offre_kg, liste, ORDRE_MARCHES, marche_dit=marche)
        ref = next(c for c in marches if c["reference_kg"] is not None)
        return {
            "offre_kg": offre_kg,
            # Champs historiques : premier marché ayant un prix.
            "reference_kg": ref["reference_kg"],
            "marche": ref["marche"],
            "date_releve": ref["date_releve"],
            "ecart_f": ref["ecart_f"],
            "ecart_pct": ref["ecart_pct"],
            "verdict": ref["verdict"],
            "marches": marches,
        }

    return Services(prix=prix, offre=offre, question=analyser_question)
