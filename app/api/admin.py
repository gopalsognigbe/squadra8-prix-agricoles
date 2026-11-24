"""API d'administration : authentification, saisie et validation humaine."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Journal, Marche, Prix, Produit, Source, Utilisateur
from app.db.session import get_session
from app.services.analyse_prix import analyser_et_marquer_prix

router = APIRouter()
COOKIE = "squadra8_admin"
COOKIE_TTL = 8 * 60 * 60


def _secret() -> bytes:
    settings = get_settings()
    value = settings.admin_session_secret or settings.hash_pepper
    if not value:
        raise HTTPException(503, "ADMIN_SESSION_SECRET ou HASH_PEPPER doit être configuré.")
    return value.encode()


def _token(user: Utilisateur) -> str:
    payload = {"uid": user.id, "exp": int(datetime.now(timezone.utc).timestamp()) + COOKIE_TTL,
               "nonce": secrets.token_hex(8)}
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
    return raw + "." + sig


def _user_from_cookie(request: Request, db: Session) -> Utilisateur:
    token = request.cookies.get(COOKIE, "")
    try:
        raw, signature = token.rsplit(".", 1)
        expected = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        if int(payload["exp"]) < int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("expired")
        user = db.get(Utilisateur, int(payload["uid"]))
        if user is None or not user.actif:
            raise ValueError("inactive")
        return user
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentification requise.") from None


def current_user(request: Request, db: Session = Depends(get_session)) -> Utilisateur:
    return _user_from_cookie(request, db)


def _require_roles(*roles: str):
    def dependency(user: Utilisateur = Depends(current_user)) -> Utilisateur:
        if user.role not in roles:
            raise HTTPException(403, "Droits insuffisants.")
        return user
    return dependency


class LoginIn(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=200)


class PrixIn(BaseModel):
    produit: str
    marche: str
    prix_fcfa: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    unite: Literal["kg", "sac_100kg"] = "kg"
    type_prix: Literal["detail", "gros"] = "detail"
    date_releve: date
    source: str = "saisie"


class RejetIn(BaseModel):
    motif: str = Field(min_length=3, max_length=1000)


def _journal(db: Session, user: Utilisateur, action: str, cible: str) -> None:
    db.add(Journal(utilisateur_id=user.id, action=action, cible=cible))


def _serialize(row: Prix, db: Session) -> dict:
    produit = db.get(Produit, row.produit_id)
    marche = db.get(Marche, row.marche_id)
    source = db.get(Source, row.source_id)
    return {
        "id": row.id, "produit": produit.nom if produit else None,
        "produit_code": produit.code if produit else None,
        "marche": marche.nom if marche else None,
        "prix_fcfa": float(row.prix_fcfa), "unite": row.unite,
        "type_prix": row.type_prix, "date_releve": row.date_releve.isoformat(),
        "source": source.nom if source else None, "statut": row.statut,
        "score_anomalie": row.score_anomalie, "motif_anomalie": row.motif_anomalie,
        "motif_rejet": row.motif_rejet,
    }


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_session)):
    user = db.scalar(select(Utilisateur).where(Utilisateur.email == body.email.strip().lower()))
    if user is None or not user.actif or not bcrypt.checkpw(body.password.encode(), user.mot_de_passe_hash.encode()):
        raise HTTPException(401, "Identifiants invalides.")
    response.set_cookie(COOKIE, _token(user), httponly=True, secure=request.url.scheme == "https",
                        samesite="strict", max_age=COOKIE_TTL, path="/")
    return {"ok": True, "utilisateur": {"nom": user.nom_affiche, "role": user.role}}


@router.post("/logout")
def logout(request: Request, response: Response):
    response.delete_cookie(COOKIE, path="/", httponly=True, secure=request.url.scheme == "https", samesite="strict")
    return {"ok": True}


@router.get("/me")
def me(user: Utilisateur = Depends(current_user)):
    return {"id": user.id, "email": user.email, "nom": user.nom_affiche, "role": user.role}


@router.get("/prix")
def lister_prix(statut: Literal["en_attente", "valide", "rejete"] = "en_attente",
                db: Session = Depends(get_session),
                user: Utilisateur = Depends(_require_roles("admin", "validateur", "saisie"))):
    rows = db.scalars(select(Prix).where(Prix.statut == statut).order_by(Prix.date_releve.desc(), Prix.id.desc())).all()
    return [_serialize(row, db) for row in rows]


@router.post("/prix", status_code=201)
def creer_prix(body: PrixIn, db: Session = Depends(get_session),
               user: Utilisateur = Depends(_require_roles("admin", "saisie"))):
    produit = db.scalar(select(Produit).where(Produit.code == body.produit, Produit.actif.is_(True)))
    marche = db.scalar(select(Marche).where(Marche.code == body.marche, Marche.actif.is_(True)))
    source = db.scalar(select(Source).where(Source.code == body.source))
    if not produit or not marche or not source:
        raise HTTPException(422, "Produit, marché ou source inconnus/inactifs.")
    row = Prix(produit_id=produit.id, marche_id=marche.id, prix_fcfa=body.prix_fcfa,
               unite=body.unite, type_prix=body.type_prix, date_releve=body.date_releve,
               source_id=source.id, statut="en_attente", saisi_par=user.id)
    db.add(row)
    try:
        db.flush()
        analyser_et_marquer_prix(db, row)
        _journal(db, user, "prix_creation", str(row.id))
        db.commit()
        db.refresh(row)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Une observation existe déjà pour cette clé (produit, marché, date, type, source).") from None
    return _serialize(row, db)


@router.post("/prix/{prix_id}/valider")
def valider_prix(prix_id: int, db: Session = Depends(get_session),
                 user: Utilisateur = Depends(_require_roles("admin", "validateur"))):
    row = db.get(Prix, prix_id)
    if row is None:
        raise HTTPException(404, "Prix introuvable.")
    if row.statut != "en_attente":
        raise HTTPException(409, "Seul un prix en attente peut être validé.")
    row.statut = "valide"
    row.valide_par = user.id
    row.date_validation = datetime.now(timezone.utc)
    _journal(db, user, "prix_validation", str(row.id))
    db.commit()
    db.refresh(row)
    return _serialize(row, db)


@router.post("/prix/{prix_id}/rejeter")
def rejeter_prix(prix_id: int, body: RejetIn, db: Session = Depends(get_session),
                 user: Utilisateur = Depends(_require_roles("admin", "validateur"))):
    row = db.get(Prix, prix_id)
    if row is None:
        raise HTTPException(404, "Prix introuvable.")
    if row.statut != "en_attente":
        raise HTTPException(409, "Seul un prix en attente peut être rejeté.")
    row.statut = "rejete"
    row.valide_par = user.id
    row.date_validation = datetime.now(timezone.utc)
    row.motif_rejet = body.motif
    _journal(db, user, "prix_rejet", f"{row.id}: {body.motif}")
    db.commit()
    db.refresh(row)
    return _serialize(row, db)


@router.post("/import/fpma")
def importer_fpma(db: Session = Depends(get_session),
                  user: Utilisateur = Depends(_require_roles("admin", "saisie"))):
    """Importe le CSV FAO déjà présent (pas d'appel réseau ici). Prix en_attente."""
    from data.scripts.import_fpma import CSV_DEFAUT, importer_lignes, lire_csv

    if not CSV_DEFAUT.is_file():
        raise HTTPException(
            404,
            f"CSV FAO absent ({CSV_DEFAUT}). Lancer d'abord python data/scripts/maj_fao.py.",
        )
    lignes = lire_csv(CSV_DEFAUT)
    resume = importer_lignes(db, lignes)
    ajoutes = int(resume.get("importees", 0))
    _journal(db, user, "import_fpma", f"{ajoutes} observations")
    db.commit()
    return {"succes": True, "nouveaux": ajoutes, "detail": resume}


@router.get("/rappels")
def rappels(db: Session = Depends(get_session),
            user: Utilisateur = Depends(_require_roles("admin", "validateur"))):
    from app.db.models import DemandeRappel
    rows = db.scalars(select(DemandeRappel).where(DemandeRappel.statut == "en_attente").order_by(DemandeRappel.cree_le)).all()
    return [{"id": r.id, "numero_hash": r.numero_hash, "motif": r.motif,
             "cree_le": r.cree_le.isoformat() if r.cree_le else None,
             "statut": r.statut} for r in rows]
