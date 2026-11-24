"""Chargement idempotent des produits, marchés, sources et admin."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TypeVar

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Marche, Produit, Source, Utilisateur
from app.db.session import get_session_factory
from data.scripts.import_fpma import SOURCE_CODE

T = TypeVar("T", Produit, Marche)
SEEDS_DIR = Path(__file__).resolve().parents[2] / "data" / "seeds"

SOURCE_SAISIE = "saisie"


def _bool_value(value: str, *, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "oui", "yes"}:
        return True
    if normalized in {"0", "false", "non", "no"}:
        return False
    raise ValueError(f"Valeur booléenne invalide pour {field}: {value!r}")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Fichier de données absent : {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"En-têtes CSV absents : {path}")
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in reader
        ]


def _upsert_rows(
    session: Session,
    model: type[T],
    rows: list[dict[str, str]],
    *,
    required: tuple[str, ...],
) -> int:
    inserted = 0
    for row in rows:
        if not row.get("code"):
            raise ValueError(f"Le champ code est obligatoire pour {model.__name__}")
        missing = [field for field in required if not row.get(field)]
        if missing:
            raise ValueError(
                f"Champs obligatoires absents pour {row['code']}: {', '.join(missing)}"
            )
        current = session.scalar(select(model).where(model.code == row["code"]))
        values: dict[str, object] = {
            key: value if value else None
            for key, value in row.items()
            if key not in {"code", "actif"} and key in model.__table__.columns
        }
        if model is Produit:
            values["touche"] = int(row["touche"])
        values["actif"] = _bool_value(row.get("actif", "true"), field="actif")
        if current is None:
            session.add(model(code=row["code"], **values))
            inserted += 1
        else:
            for key, value in values.items():
                setattr(current, key, value)
    return inserted


def charger_donnees(session: Session, dossier: Path = SEEDS_DIR) -> dict[str, int]:
    """Insère ou actualise les référentiels ; ne crée jamais de prix."""
    produits = _read_csv(dossier / "produits.csv")
    marches = _read_csv(dossier / "marches.csv")
    return {
        "produits": _upsert_rows(
            session, Produit, produits, required=("nom", "touche")
        ),
        "marches": _upsert_rows(
            session, Marche, marches, required=("nom", "commune")
        ),
    }


def charger_sources_et_admin(session: Session) -> dict[str, int]:
    """Ajoute les sources FAO/saisie et le compte admin initial (si demandé)."""
    ajoutes = {"sources": 0, "admin": 0}
    sources = [
        {
            "code": SOURCE_CODE,
            "nom": "FPMA – SIM-Bénin",
            "url": "https://fpma.review.fao.org/",
            "licence": "Source publique FPMA",
        },
        {
            "code": SOURCE_SAISIE,
            "nom": "Saisie manuelle",
            "url": None,
            "licence": None,
        },
    ]
    for row in sources:
        if session.scalar(select(Source).where(Source.code == row["code"])) is None:
            session.add(Source(**row))
            ajoutes["sources"] += 1

    settings = get_settings()
    if settings.admin_email and settings.admin_password_initial:
        email = settings.admin_email.strip().lower()
        if session.scalar(select(Utilisateur).where(Utilisateur.email == email)) is None:
            hashed = bcrypt.hashpw(
                settings.admin_password_initial.encode(),
                bcrypt.gensalt(),
            ).decode()
            session.add(
                Utilisateur(
                    email=email,
                    nom_affiche="Administrateur",
                    role="admin",
                    mot_de_passe_hash=hashed,
                    actif=True,
                )
            )
            ajoutes["admin"] = 1
    return ajoutes


def run() -> dict[str, int]:
    """Charge les CSV, sources et admin dans une transaction."""
    factory = get_session_factory()
    with factory.begin() as session:
        resume = charger_donnees(session)
        resume.update(charger_sources_et_admin(session))
        return resume


if __name__ == "__main__":
    print(run())
