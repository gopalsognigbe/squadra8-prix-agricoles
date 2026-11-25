"""Routes des prix et de l'offre (écart en francs par rapport au détail au kilo).

Responsable : Gopal.

Aucun prix inventé : lecture via get_source_prix() (CSV FAO plan B).
Chaque prix porte sa date de relevé — jamais « prix d'aujourd'hui ».
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, model_validator

from app.services.calculs import comparer_offre_marches, juger_offre
from app.services import prix_service
from app.services.source_prix import ORDRE_MARCHES, resoudre_produit

router = APIRouter()

MSG_ABSENT = "Pas de prix disponible pour ce produit et ce marché."
MSG_ABSENT_PRODUIT = "Pas de prix disponible pour ce produit."
MSG_PRODUIT_INCONNU = "Produit inconnu. Pas de prix disponible."


class OffreIn(BaseModel):
    produit: str = Field(min_length=1, max_length=200)
    marche: str | None = None
    offre_kg: float | None = Field(default=None, gt=0)
    montant_sac: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _au_moins_un_montant(self) -> OffreIn:
        if self.offre_kg is None and self.montant_sac is None:
            raise ValueError("fournir offre_kg ou montant_sac")
        return self


def _reponse_prix(
    produit_demande: str,
    *,
    marche: str | None,
    liste: list[dict],
) -> dict:
    produit_fao = resoudre_produit(produit_demande) or produit_demande.strip()
    if not liste:
        corps: dict = {
            "disponible": False,
            "produit": produit_fao,
            "prix": [],
            "message": MSG_ABSENT if marche else MSG_ABSENT_PRODUIT,
        }
        if marche:
            corps["marche"] = marche
        if resoudre_produit(produit_demande) is None:
            corps["message"] = MSG_PRODUIT_INCONNU
        return corps
    return {
        "disponible": True,
        "produit": liste[0]["produit"],
        "prix": liste,
    }


@router.get("/prix")
def get_prix(
    produit: str = Query(..., min_length=1),
    marche: str | None = Query(default=None),
) -> dict:
    """Prix du relevé FAO pour un produit (marché optionnel)."""
    if marche:
        un = prix_service.dernier_prix(produit, marche)
        liste = [un] if un else []
        return _reponse_prix(produit, marche=marche, liste=liste)
    return _reponse_prix(produit, marche=None, liste=prix_service.prix_du_jour(produit))


@router.get("/prix/{produit}")
def get_prix_chemin(
    produit: str,
    marche: str | None = Query(default=None),
) -> dict:
    """Même chose que GET /prix, produit dans le chemin."""
    return get_prix(produit=produit, marche=marche)


@router.post("/offre")
def post_offre(body: OffreIn) -> dict:
    """Compare une offre au prix de détail (touche 2), sans inventer de référence."""
    produit_fao = resoudre_produit(body.produit)
    if produit_fao is None:
        return {
            "disponible": False,
            "produit": body.produit.strip(),
            "prix": [],
            "message": MSG_PRODUIT_INCONNU,
        }

    if body.marche:
        ref = prix_service.dernier_prix(produit_fao, body.marche)
    else:
        dispo = prix_service.prix_du_jour(produit_fao)
        ref = dispo[0] if dispo else None

    if ref is None:
        corps = {
            "disponible": False,
            "produit": produit_fao,
            "prix": [],
            "message": MSG_ABSENT if body.marche else MSG_ABSENT_PRODUIT,
        }
        if body.marche:
            corps["marche"] = body.marche
        return corps

    offre_kg = body.offre_kg
    if offre_kg is None:
        # montant_sac = prix pour 100 kg → ramener au kilo
        offre_kg = float(body.montant_sac) / 100.0  # type: ignore[arg-type]

    jugement = juger_offre(offre_kg, float(ref["prix_kg"]))
    # Même offre comparée aux 3 marchés (marché de référence en premier) ;
    # un marché sans prix récent a reference_kg = None (jamais inventé).
    dispo = [p for p in prix_service.prix_du_jour(produit_fao) if p["marche"] != ref["marche"]]
    marches = comparer_offre_marches(
        offre_kg, [ref, *dispo], ORDRE_MARCHES, marche_dit=ref["marche"],
    )
    return {
        "disponible": True,
        "produit": ref["produit"],
        "marche": ref["marche"],
        "date_releve": ref["date_releve"],
        "prix_kg": ref["prix_kg"],
        "prix_fcfa": ref["prix_fcfa"],
        "offre_kg": offre_kg,
        **jugement,
        "marches": marches,
    }
