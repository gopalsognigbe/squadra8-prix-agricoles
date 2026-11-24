"""Fakes pour les tests unitaires du moteur uniquement."""

from __future__ import annotations

from app.dialogue.moteur import Services
from app.services.calculs import juger_offre, vers_100kg

SOURCE = "SIM-Bénin (FAO FPMA)"

# Ordre = ORDRE_MARCHES (Bohicon en premier). Noms FAO exacts. Pas de 4e marché.
PRIX = {
    "mais": [
        {
            "marche": "Bohicon",
            "prix_fcfa": 137.36,
            "prix_kg": 137.36,
            "prix_100kg": vers_100kg(137.36),
            "unite": "Kilogramme",
            "type_prix": "detail",
            "date_releve": "2026-10-25",
            "source": SOURCE,
        },
        {
            "marche": "Houndjro (Abomey)",
            "prix_fcfa": 128.57,
            "prix_kg": 128.57,
            "prix_100kg": vers_100kg(128.57),
            "unite": "Kilogramme",
            "type_prix": "detail",
            "date_releve": "2026-10-19",
            "source": SOURCE,
        },
        {
            "marche": "Azogotchébou (Covè)",
            "prix_fcfa": 140.0,
            "prix_kg": 140.0,
            "prix_100kg": vers_100kg(140.0),
            "unite": "Kilogramme",
            "type_prix": "detail",
            "date_releve": "2026-10-28",
            "source": SOURCE,
        },
    ],
    "soja": [
        {
            "marche": "Bohicon",
            "prix_fcfa": 407.0,
            "prix_kg": 407.0,
            "prix_100kg": vers_100kg(407.0),
            "unite": "Kilogramme",
            "type_prix": "detail",
            "date_releve": "2026-10-25",
            "source": SOURCE,
        },
    ],
    "haricot": [
        {
            "marche": "Bohicon",
            "prix_fcfa": 652.0,
            "prix_kg": 652.0,
            "prix_100kg": vers_100kg(652.0),
            "unite": "Kilogramme",
            "type_prix": "detail",
            "date_releve": "2026-10-25",
            "source": SOURCE,
        },
    ],
}


class FakeJournal:
    def __init__(self) -> None:
        self.lignes: list[tuple[str, str, str]] = []

    def __call__(self, appel_id: str, etape: str, entree: str) -> None:
        self.lignes.append((appel_id, etape, entree))


def _question_en_panne(valeur: str) -> dict:
    return {"erreur": "ia"}


def services_fakes(*, sans_prix: bool = False, journal=None, question=None) -> Services:
    def _liste(produit: str) -> list[dict]:
        # « mais jaune » → prix de la famille « mais » (données de test seulement).
        famille = (produit or "").split(" ")[0]
        return [] if sans_prix else list(PRIX.get(famille, []))

    def prix(produit: str) -> list[dict]:
        return _liste(produit)

    def offre(produit: str, montant_sac: float, marche: str | None = None) -> dict | None:
        liste = _liste(produit)
        if not liste:
            return None
        # Marché demandé s'il a un prix, sinon premier de la liste (Bohicon).
        du_marche = [p for p in liste if p["marche"] == marche]
        ref = du_marche[0] if du_marche else liste[0]
        offre_kg = float(montant_sac) / 100.0
        jugement = juger_offre(offre_kg, float(ref["prix_fcfa"]))
        return {
            "offre_kg": offre_kg,
            "reference_kg": float(ref["prix_fcfa"]),
            "marche": ref["marche"],
            "date_releve": ref["date_releve"],
            **jugement,
        }

    kw = {"question": question or _question_en_panne}
    if journal is not None:
        kw["journal"] = journal
    return Services(prix=prix, offre=offre, **kw)
