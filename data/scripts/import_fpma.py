"""Importe les observations FPMA dans PostgreSQL sans les valider.

Les correspondances sont lues dans data/seeds/produits.csv et marches.csv
via leur colonne nom_fpma. Aucune correspondance n'est devinée.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from app.db.models import Marche, Prix, Produit, Source  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.services.analyse_prix import analyser_et_marquer_prix  # noqa: E402

CSV_DEFAUT = RACINE / "data" / "raw" / "prix_fao.csv"
SOURCE_CODE = "FAO_FPMA"
SOURCE_NOM = "FAO - FPMA"
SOURCE_URL = "https://www.fao.org/giews/food-prices/tool/public/"
DEVISES_XOF = {"XOF", "FCFA", "CFA", "CFA FRANC", "CFA FRANC BCEAO"}
logger = logging.getLogger("import_fpma")


def normaliser(value: str | None) -> str:
    """Normalise les libellés pour comparer sans casse ni accents."""
    texte = unicodedata.normalize("NFKD", (value or "").strip().casefold())
    return " ".join("".join(c for c in texte if not unicodedata.combining(c)).split())


def lire_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Fichier CSV introuvable : {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"produit", "marche", "date", "prix", "type", "unite", "devise"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Colonnes CSV absentes : " + ", ".join(sorted(missing)))
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def _indexer_referentiel(session: Session, model: type[Produit] | type[Marche]) -> dict[str, Any]:
    objets = session.scalars(select(model)).all()
    return {
        normaliser(obj.nom_fpma): obj
        for obj in objets
        if obj.nom_fpma and obj.actif
    }


def _unite(value: str) -> str | None:
    texte = normaliser(value).replace(" ", "")
    if texte in {"kg", "kilogramme", "kilograms"}:
        return "kg"
    if texte in {"100kg", "100kgs", "100kilogrammes", "sac100kg"}:
        return "sac_100kg"
    return None


def _type_prix(value: str) -> str | None:
    texte = normaliser(value)
    if texte in {"detail", "retail"}:
        return "detail"
    if texte in {"gros", "wholesale"}:
        return "gros"
    return None


def importer_lignes(
    session: Session,
    lignes: list[dict[str, str]],
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """Importe les lignes mappées ; les prix restent toujours en_attente."""
    produits = _indexer_referentiel(session, Produit)
    marches = _indexer_referentiel(session, Marche)
    resume = {
        "lues": len(lignes),
        "importees": 0,
        "doublons": 0,
        "produit_inconnu": 0,
        "marche_inconnu": 0,
        "donnee_invalide": 0,
    }

    source: Source | None = session.scalar(
        select(Source).where(Source.code == SOURCE_CODE)
    )

    for ligne in lignes:
        produit = produits.get(normaliser(ligne.get("produit")))
        marche = marches.get(normaliser(ligne.get("marche")))
        if produit is None:
            resume["produit_inconnu"] += 1
            continue
        if marche is None:
            resume["marche_inconnu"] += 1
            continue

        devise = normaliser(ligne.get("devise")).upper()
        unite = _unite(ligne.get("unite", ""))
        type_prix = _type_prix(ligne.get("type", ""))
        try:
            date_releve = date.fromisoformat(ligne.get("date", ""))
            montant = Decimal(ligne.get("prix", ""))
        except (ValueError, InvalidOperation):
            resume["donnee_invalide"] += 1
            continue

        if (
            devise not in DEVISES_XOF
            or unite is None
            or type_prix is None
            or not montant.is_finite()
            or montant <= 0
        ):
            resume["donnee_invalide"] += 1
            continue

        if source is None:
            source = Source(code=SOURCE_CODE, nom=SOURCE_NOM, url=SOURCE_URL)
            session.add(source)
            session.flush()

        cle = (
            Prix.produit_id == produit.id,
            Prix.marche_id == marche.id,
            Prix.date_releve == date_releve,
            Prix.type_prix == type_prix,
            Prix.source_id == source.id,
        )
        if session.scalar(select(Prix.id).where(*cle)) is not None:
            resume["doublons"] += 1
            continue

        row = Prix(
            produit_id=produit.id,
            marche_id=marche.id,
            prix_fcfa=montant,
            unite=unite,
            type_prix=type_prix,
            date_releve=date_releve,
            source_id=source.id,
            statut="en_attente",
        )
        session.add(row)
        session.flush()
        analyser_et_marquer_prix(session, row)
        resume["importees"] += 1

    if dry_run:
        session.flush()
        session.rollback()
    else:
        session.flush()
    return resume


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importe les prix FPMA du CSV dans PostgreSQL."
    )
    parser.add_argument("--csv", type=Path, default=CSV_DEFAUT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simule l'import puis annule la transaction.",
    )
    args = parser.parse_args()

    lignes = lire_csv(args.csv)
    factory = get_session_factory()
    if args.dry_run:
        with factory() as session:
            resume = importer_lignes(session, lignes, dry_run=True)
    else:
        with factory.begin() as session:
            resume = importer_lignes(session, lignes)

    for cle, valeur in resume.items():
        logger.info("%s : %s", cle, valeur)
    if resume["produit_inconnu"] or resume["marche_inconnu"] or resume["donnee_invalide"]:
        logger.warning("Certaines lignes n'ont pas été importées ; voir les référentiels et le CSV.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
