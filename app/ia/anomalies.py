"""IA 2 : signale les prix bizarres (importés ou saisis à la main).

Responsable : Gopal.

Le LLM ne décide jamais du statut. Quatre règles chiffrées (A–D) le font.
Un motif en français ne fait que reformuler les raisons déjà calculées.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Any, Sequence

logger = logging.getLogger(__name__)

_SEUILS_PATH = Path(__file__).with_name("seuils_anomalies.json")

CODES_RAISON = (
    "A_variation_dernier_prix",
    "B_ecart_marches_voisins",
    "C_hors_plage_historique",
    "D_prix_nul_ou_negatif",
    "D_unite_inattendue",
    "D_facteur_10",
    "D_confusion_sac_kilo",
)


@dataclass
class ResultatAnomalie:
    """Résultat d'analyse d'un prix proposé."""

    statut: str  # "ok" | "a_verifier"
    raisons: list[str] = field(default_factory=list)
    motif: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "statut": self.statut,
            "raisons": list(self.raisons),
            "motif": self.motif,
        }


def charger_seuils(chemin: Path | None = None) -> dict[str, Any]:
    """Charge les seuils depuis le JSON suivi par git (aucune clé API)."""
    path = chemin or _SEUILS_PATH
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _parse_date(valeur: date | datetime | str) -> date:
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    texte = str(valeur).strip()
    if "T" in texte:
        return datetime.fromisoformat(texte).date()
    return date.fromisoformat(texte)


def _entree_date(entree: dict[str, Any]) -> date:
    return _parse_date(entree["date"])


def _entree_prix(entree: dict[str, Any]) -> float:
    return float(entree["prix"])


def _meme_marche(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _historique_trie(
    historique: Sequence[dict[str, Any]] | None,
    date_ref: date,
) -> list[dict[str, Any]]:
    """Prix antérieurs strictement avant date_ref, du plus récent au plus ancien."""
    if not historique:
        return []
    anterieurs = [e for e in historique if _entree_date(e) < date_ref]
    return sorted(anterieurs, key=_entree_date, reverse=True)


def _dernier_prix_valide(
    historique: Sequence[dict[str, Any]] | None,
    date_ref: date,
) -> dict[str, Any] | None:
    for entree in _historique_trie(historique, date_ref):
        if entree.get("valide", True) is False:
            continue
        return entree
    return None


def _ecart_pct(prix: float, reference: float) -> float:
    if reference == 0:
        return float("inf")
    return abs(prix - reference) / abs(reference) * 100.0


def _appliquer_A(
    prix: float,
    date_ref: date,
    dernier: dict[str, Any] | None,
    seuils: dict[str, Any],
) -> tuple[str, str] | None:
    if dernier is None:
        return None
    jours = (date_ref - _entree_date(dernier)).days
    if jours > int(seuils["ecart_max_A_jours"]):
        return None
    ref = _entree_prix(dernier)
    if ref <= 0:
        return None
    ecart = _ecart_pct(prix, ref)
    if ecart <= float(seuils["seuil_A_pct"]):
        return None
    code = "A_variation_dernier_prix"
    motif = (
        f"Variation de {ecart:.0f} % par rapport au dernier prix validé "
        f"({ref:g} F, il y a {jours} jour{'s' if jours != 1 else ''})."
    )
    return code, motif


def _appliquer_B(
    prix: float,
    marche: str,
    date_ref: date,
    voisins: Sequence[dict[str, Any]] | None,
    seuils: dict[str, Any],
) -> tuple[str, str] | None:
    if not voisins:
        return None
    fenetre = int(seuils["fenetre_B_jours"])
    prix_voisins: list[float] = []
    for entree in voisins:
        if _meme_marche(str(entree.get("marche", "")), marche):
            continue
        delta = abs((_entree_date(entree) - date_ref).days)
        if delta > fenetre:
            continue
        prix_voisins.append(_entree_prix(entree))
    if len(prix_voisins) < int(seuils["min_voisins_B"]):
        return None
    med = float(median(prix_voisins))
    if med <= 0:
        return None
    ecart = _ecart_pct(prix, med)
    if ecart <= float(seuils["seuil_B_pct"]):
        return None
    code = "B_ecart_marches_voisins"
    motif = (
        f"Écart de {ecart:.0f} % par rapport à la médiane des marchés voisins "
        f"({med:g} F)."
    )
    return code, motif


def _appliquer_C(
    prix: float,
    date_ref: date,
    historique: Sequence[dict[str, Any]] | None,
    seuils: dict[str, Any],
) -> tuple[str, str] | None:
    mois = int(seuils["fenetre_C_mois"])
    try:
        debut = date_ref.replace(year=date_ref.year - mois)
    except ValueError:
        # 29 février → 28 février de l'année cible
        debut = date_ref.replace(year=date_ref.year - mois, day=28)

    points: list[float] = []
    for entree in historique or []:
        d = _entree_date(entree)
        if debut <= d < date_ref:
            points.append(_entree_prix(entree))
    if len(points) < int(seuils["min_observations_C"]):
        return None
    p_min = min(points)
    p_max = max(points)
    marge = float(seuils["marge_C_pct"]) / 100.0
    borne_basse = p_min * (1.0 - marge)
    borne_haute = p_max * (1.0 + marge)
    if borne_basse <= prix <= borne_haute:
        return None
    code = "C_hors_plage_historique"
    motif = (
        f"Prix hors de la plage historique "
        f"[{borne_basse:g} ; {borne_haute:g}] F "
        f"(min {p_min:g}, max {p_max:g}, marge {seuils['marge_C_pct']} %)."
    )
    return code, motif


def _appliquer_D(
    prix: float,
    unite: str | None,
    dernier: dict[str, Any] | None,
    seuils: dict[str, Any],
) -> list[tuple[str, str]]:
    resultats: list[tuple[str, str]] = []
    if prix <= 0:
        resultats.append(
            ("D_prix_nul_ou_negatif", "Prix nul ou négatif.")
        )

    if unite is not None and str(unite).strip() != "":
        unites = {str(u) for u in seuils["unites_acceptees"]}
        if str(unite).strip() not in unites:
            resultats.append(
                (
                    "D_unite_inattendue",
                    f"Unité inattendue : « {unite} » "
                    f"(attendues : {', '.join(sorted(unites))}).",
                )
            )

    if dernier is not None:
        ref = _entree_prix(dernier)
        if ref > 0 and prix > 0:
            rapport = prix / ref
            facteur = float(seuils["facteur_10_ratio"])
            confusion = float(seuils["confusion_sac_kilo_ratio"])
            if rapport >= facteur or rapport <= 1.0 / facteur:
                resultats.append(
                    (
                        "D_facteur_10",
                        f"Rapport au dernier prix = {rapport:.2g} "
                        f"(seuil facteur {facteur:g}).",
                    )
                )
            if rapport >= confusion or rapport <= 1.0 / confusion:
                resultats.append(
                    (
                        "D_confusion_sac_kilo",
                        f"Confusion probable sac 100 kg / kilo "
                        f"(rapport {rapport:.2g}, seuil {confusion:g}).",
                    )
                )
    return resultats


def analyser_prix(
    produit: str,
    marche: str,
    date_prix: date | datetime | str,
    prix: float,
    unite: str | None = None,
    historique: Sequence[dict[str, Any]] | None = None,
    voisins: Sequence[dict[str, Any]] | None = None,
    seuils: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analyse un prix proposé avec les seules règles A–D (aucun LLM).

    Paramètres historiques / voisins : listes de dicts déjà connus
    (``date``, ``prix``, et pour les voisins ``marche``). Si une règle
    manque de données, elle est ignorée — aucun prix inventé.
    """
    seuils_eff = seuils if seuils is not None else charger_seuils()
    date_ref = _parse_date(date_prix)
    prix_f = float(prix)

    raisons: list[str] = []
    motifs: list[str] = []

    # D d'abord pour les erreurs évidentes, puis A/B/C.
    dernier = _dernier_prix_valide(historique, date_ref)

    for code, motif in _appliquer_D(prix_f, unite, dernier, seuils_eff):
        raisons.append(code)
        motifs.append(motif)

    # A / D-ratio : si prix ≤ 0, les écarts relatifs n'ont pas de sens utile ;
    # A et B/C restent évaluables mais A sur prix ≤ 0 avec ref > 0 dépasse
    # toujours 30 % — on continue quand même pour signaler toutes les raisons.
    a = _appliquer_A(prix_f, date_ref, dernier, seuils_eff)
    if a is not None:
        raisons.append(a[0])
        motifs.append(a[1])

    b = _appliquer_B(prix_f, marche, date_ref, voisins, seuils_eff)
    if b is not None:
        raisons.append(b[0])
        motifs.append(b[1])

    c = _appliquer_C(prix_f, date_ref, historique, seuils_eff)
    if c is not None:
        raisons.append(c[0])
        motifs.append(c[1])

    # Ordre stable des codes connus, puis éventuels inconnus.
    ordre = {code: i for i, code in enumerate(CODES_RAISON)}
    paires = sorted(
        zip(raisons, motifs, strict=True),
        key=lambda p: ordre.get(p[0], 999),
    )
    raisons_triees = [p[0] for p in paires]
    motifs_tries = [p[1] for p in paires]

    statut = "ok" if not raisons_triees else "a_verifier"
    motif_final = " ".join(motifs_tries) if motifs_tries else ""

    return ResultatAnomalie(
        statut=statut,
        raisons=raisons_triees,
        motif=motif_final,
    ).as_dict()


def _charger_depuis_base(prix_ids: list[Any]) -> list[dict[str, Any]]:
    """Charge les prix en base si les modèles SQLAlchemy existent."""
    from app.db import models  # import local : modèles encore squelette

    modele_prix = getattr(models, "Prix", None)
    if modele_prix is None:
        raise RuntimeError(
            "Modèle Prix indisponible : passer prix_a_analyser=... pour tester."
        )

    from app.db.session import session_scope

    resultats: list[dict[str, Any]] = []
    with session_scope() as session:  # noqa: SIM117 — API session future
        for prix_id in prix_ids:
            row = session.get(modele_prix, prix_id)
            if row is None:
                logger.warning("Prix id=%s introuvable", prix_id)
                continue
            historique = []
            voisins = []
            # Quand le schéma sera prêt : charger historique / voisins ici.
            resultat = analyser_prix(
                produit=row.produit,
                marche=row.marche,
                date_prix=row.date,
                prix=float(row.prix),
                unite=getattr(row, "unite", None),
                historique=historique,
                voisins=voisins,
            )
            resultat["prix_id"] = prix_id
            resultats.append(resultat)
    return resultats


def analyser(
    prix_ids: list[Any] | None = None,
    *,
    prix_a_analyser: list[dict[str, Any]] | None = None,
    seuils: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Examine des prix en attente et signale les anomalies.

    - Si ``prix_a_analyser`` est fourni (tests / scripts) : analyse directe.
      Chaque élément : produit, marche, date, prix, et optionnellement unite,
      historique, voisins.
    - Sinon, avec ``prix_ids`` : tentative de chargement en base si les modèles
      existent.
    """
    if prix_a_analyser is not None:
        sorties: list[dict[str, Any]] = []
        for proposition in prix_a_analyser:
            resultat = analyser_prix(
                produit=str(proposition["produit"]),
                marche=str(proposition["marche"]),
                date_prix=proposition["date"],
                prix=float(proposition["prix"]),
                unite=proposition.get("unite"),
                historique=proposition.get("historique"),
                voisins=proposition.get("voisins"),
                seuils=seuils,
            )
            if "id" in proposition:
                resultat["prix_id"] = proposition["id"]
            sorties.append(resultat)
        return sorties

    if prix_ids is None:
        raise ValueError("Fournir prix_ids ou prix_a_analyser.")

    return _charger_depuis_base(list(prix_ids))
