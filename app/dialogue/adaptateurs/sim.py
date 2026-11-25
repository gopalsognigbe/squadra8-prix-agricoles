"""Adaptateur simulateur : traduit un tour du moteur en JSON (contrat 5.1).

Responsable : Guillaume.
"""
from app.dialogue.moteur import Tour


def tour_vers_json(tour: Tour) -> dict:
    """Le Tour du moteur a déjà le format du contrat : etat, phrases, attente..."""
    return tour.model_dump()
