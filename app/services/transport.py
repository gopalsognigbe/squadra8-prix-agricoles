"""Coûts de transport commune → marché (F CFA par sac de 100 kg).

Les coûts sont dans data/transport/couts_transport.csv (ou TRANSPORT_CSV).
Ce sont des ESTIMATIONS (statut « estime ») tant qu'un membre de l'équipe ne
les a pas vérifiés dans le dashboard (/admin/), qui les passe à « verifie ».
Méthode et sources : docs/transport/methode_couts_transport.md.
"""

from __future__ import annotations

import csv
import os
import threading
import unicodedata
from pathlib import Path

# Les 9 communes du Zou, dans l'ordre des touches 1 à 9 (0 = autre commune).
COMMUNES = (
    "Abomey", "Agbangnizoun", "Bohicon", "Covè", "Djidja",
    "Ouinhi", "Zagnanado", "Za-Kpota", "Zogbodomey",
)
TOUCHE_COMMUNE = {str(i + 1): nom for i, nom in enumerate(COMMUNES)}
STATUTS = ("estime", "verifie")
CHAMPS = (
    "id", "commune", "marche", "distance_km", "cout_sac_100kg", "cout_min", "cout_max",
    "mode", "source", "date_estimation", "statut", "modifie_par", "modifie_le",
)
CSV_DEFAUT = Path(__file__).resolve().parents[2] / "data" / "transport" / "couts_transport.csv"
_verrou = threading.Lock()


def chemin_csv() -> Path:
    return Path(os.environ.get("TRANSPORT_CSV") or CSV_DEFAUT)


def lire_couts(chemin: Path | None = None) -> list[dict]:
    """Toutes les lignes du tableau (liste vide si le fichier manque)."""
    chemin = chemin or chemin_csv()
    if not chemin.is_file():
        return []
    with chemin.open(encoding="utf-8", newline="") as f:
        lignes = list(csv.DictReader(f))
    for ligne in lignes:
        ligne["id"] = int(ligne["id"])
        ligne["distance_km"] = float(ligne["distance_km"]) if ligne.get("distance_km") else None
        for champ in ("cout_sac_100kg", "cout_min", "cout_max"):
            ligne[champ] = int(float(ligne[champ])) if ligne.get(champ) else None
    return lignes


def ecrire_couts(lignes: list[dict], chemin: Path | None = None) -> None:
    """Réécrit le fichier (écriture atomique : fichier temporaire puis remplacement)."""
    chemin = chemin or chemin_csv()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CHAMPS)
        w.writeheader()
        for ligne in lignes:
            w.writerow({c: ("" if ligne.get(c) is None else ligne.get(c)) for c in CHAMPS})
    os.replace(tmp, chemin)


def modifier_cout(id_ligne: int, modifs: dict, auteur: str, quand: str,
                  chemin: Path | None = None) -> dict | None:
    """Modifie une ligne (coût, mode, source, statut). Renvoie la ligne ou None."""
    with _verrou:
        lignes = lire_couts(chemin)
        cible = next((ligne for ligne in lignes if ligne["id"] == id_ligne), None)
        if cible is None:
            return None
        for champ in ("cout_sac_100kg", "cout_min", "cout_max", "mode", "source", "statut"):
            if modifs.get(champ) is not None:
                cible[champ] = modifs[champ]
        cible["modifie_par"] = auteur
        cible["modifie_le"] = quand
        ecrire_couts(lignes, chemin)
        return cible


def cout_transport(commune: str | None, marche: str) -> dict | None:
    """Coût d'un sac de 100 kg de la commune au marché, ou None s'il manque."""
    if not commune:
        return None
    for ligne in lire_couts():
        if ligne["commune"] == commune and ligne["marche"] == marche:
            if not ligne["cout_sac_100kg"] or ligne["cout_sac_100kg"] < 0:
                return None
            return {
                "cout_sac_100kg": ligne["cout_sac_100kg"],
                "cout_kg": ligne["cout_sac_100kg"] / 100.0,
                "statut": ligne["statut"] if ligne["statut"] in STATUTS else "estime",
                "mode": ligne["mode"],
            }
    return None


def transport_disponible() -> bool:
    return bool(lire_couts())


# ---------- commune dite à la touche 3 ----------
def _norm(texte: str) -> str:
    sans = unicodedata.normalize("NFKD", texte.lower())
    sans = "".join(c for c in sans if not unicodedata.combining(c))
    sans = "".join(c if c.isalnum() else " " for c in sans)  # ponctuation → espace
    return " ".join(sans.split())


_VARIANTES_COMMUNES = {
    "Abomey": ("abomey", "abome"),
    "Agbangnizoun": ("agbangnizoun", "agbangnizou", "agbagnizoun"),
    "Bohicon": ("bohicon", "bohikon", "boicon"),
    "Covè": ("cove", "kove", "covet", "covey"),
    "Djidja": ("djidja", "djija", "jidja"),
    "Ouinhi": ("ouinhi", "wouinhi", "ouini"),
    "Zagnanado": ("zagnanado", "zangnanado", "zagnando"),
    "Za-Kpota": ("za kpota", "zakpota", "za kpota"),
    "Zogbodomey": ("zogbodomey", "zogbodome", "zogbodomè"),
}
# La commune n'est prise que si elle suit une tournure de départ : « Bohicon »
# seul est un MARCHÉ, pas forcément la commune de l'appelant.
_AMORCES = ("je suis a", "je suis de", "j habite a", "j habite", "je viens de",
            "depuis", "je pars de", "chez moi a", "moi a", "je vis a", "je reste a")


def trouver_commune(texte: str | None) -> str | None:
    """Commune de départ dite dans la phrase (« je suis à Zagnanado »), sinon None."""
    if not texte:
        return None
    n = f" {_norm(texte)} "
    for amorce in _AMORCES:
        debut = n.find(f" {amorce} ")
        while debut != -1:
            suite = n[debut + len(amorce) + 2:]
            for nom, variantes in _VARIANTES_COMMUNES.items():
                if any(suite.startswith(v + " ") for v in variantes):
                    return nom
            debut = n.find(f" {amorce} ", debut + 1)
    return None
