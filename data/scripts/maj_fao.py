"""Mise à jour incrémentale des prix FAO (API publique FPMA uniquement).

Usage :
  python data/scripts/maj_fao.py
  python data/scripts/maj_fao.py --tout-benin

Aucun scraping SIM-AH. Aucune donnée inventée.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Racine du dépôt (data/scripts/maj_fao.py → parents[2]).
RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

API_BENIN = "https://fpma.review.fao.org/giews/v4/ben/price_module/api/v1"
API_GLOBAL = "https://fpma.fao.org/giews/v4/global/price_module/api/v1"

USER_AGENT = "Squadra8-prix-agricoles/1.0 (recherche; FAO FPMA public API)"
CSV_DEFAUT = RACINE / "data" / "raw" / "prix_fao.csv"
TAILLE_LOT = 40
PAUSE_LOTS_S = 0.25
MAX_TENTATIVES = 5

PRODUITS_MVP = frozenset(
    {
        "Maïs Blanc",
        "Maïs Jaune",
        "Soja",
        "Haricot blanc",
        "Haricot noir",
        "Haricot rouge",
    }
)
MARCHES_MVP = frozenset(
    {
        "Bohicon",
        "Houndjro (Abomey)",
        "Azogotchébou (Covè)",
    }
)

COLONNES = [
    "pays",
    "marche",
    "departement",
    "commune",
    "produit",
    "type",
    "unite",
    "devise",
    "date",
    "prix",
    "source_serie_id",
    "periodicite",
    "source",
    "type_marche",
]

logger = logging.getLogger("maj_fao")


def _configurer_journal() -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def normaliser_departement(admin_unit: str | None) -> str:
    """Retire un suffixe éventuel « department (1) » (API mondiale)."""
    texte = (admin_unit or "").strip()
    return re.sub(r"\s*department\s*\(\s*1\s*\)\s*$", "", texte, flags=re.IGNORECASE).strip()


def mapper_type_prix(price_type: str | None) -> str:
    libelle = (price_type or "").strip()
    haut = libelle.upper()
    if any(m in haut for m in ("DETAIL", "DÉTAIL", "RETAIL")):
        return "detail"
    if any(m in haut for m in ("GROS", "WHOLESALE")):
        return "gros"
    return libelle


def choisir_periodicite(serie: dict[str, Any]) -> str | None:
    """Périodicité native (calculated faux) : daily > weekly > monthly."""
    periodes = serie.get("periodicity") or []
    if not isinstance(periodes, list):
        return None
    natives: list[str] = []
    for item in periodes:
        if not isinstance(item, dict):
            continue
        if item.get("calculated"):
            continue
        period = str(item.get("period") or "").strip().lower()
        if period:
            natives.append(period)
    for pref in ("daily", "weekly", "monthly"):
        if pref in natives:
            return pref
    return natives[0] if natives else None


def get_json(url: str, *, tentatives: int = MAX_TENTATIVES) -> Any:
    """GET JSON avec retries exponentiels. Lève en dernier recours."""
    dernier: Exception | None = None
    for essai in range(tentatives):
        try:
            requete = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            with urllib.request.urlopen(requete, timeout=60) as reponse:
                return json.loads(reponse.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            dernier = exc
            if essai + 1 >= tentatives:
                break
            attente = min(2**essai, 30)
            logger.warning("Échec GET %s (%s) — nouvel essai dans %ss", url, exc, attente)
            time.sleep(attente)
    assert dernier is not None
    raise dernier


def _pages(url_depart: str) -> list[dict[str, Any]]:
    """Suit la pagination (liste brute ou {results, next})."""
    items: list[dict[str, Any]] = []
    url: str | None = url_depart
    while url:
        payload = get_json(url)
        if isinstance(payload, list):
            items.extend(x for x in payload if isinstance(x, dict))
            break
        if isinstance(payload, dict):
            results = payload.get("results")
            if isinstance(results, list):
                items.extend(x for x in results if isinstance(x, dict))
            suivant = payload.get("next")
            url = suivant if isinstance(suivant, str) and suivant else None
            continue
        break
    return items


def lister_series(base: str, filtre: str = "") -> list[dict[str, Any]]:
    """Liste les séries FpmaSerieDomestic (filtre vide = module Bénin)."""
    url = f"{base}/FpmaSerieDomestic/{filtre}"
    return _pages(url)


def filtrer_series_mvp(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Égalité exacte sur commodity_name et market_name (accents compris)."""
    retenues: list[dict[str, Any]] = []
    for serie in series:
        produit = serie.get("commodity_name")
        marche = serie.get("market_name")
        if produit in PRODUITS_MVP and marche in MARCHES_MVP:
            retenues.append(serie)
    return retenues


def telecharger_prix(
    base: str,
    uuids: list[str],
    periodicity: str,
) -> list[dict[str, Any]]:
    """Prix par lots de 40 UUID, pause entre lots."""
    observations: list[dict[str, Any]] = []
    for i in range(0, len(uuids), TAILLE_LOT):
        lot = uuids[i : i + TAILLE_LOT]
        if i > 0:
            time.sleep(PAUSE_LOTS_S)
        uuid_in = ",".join(lot)
        url = f"{base}/FpmaSeriePrice/?uuid__in={uuid_in}&periodicity={periodicity}"
        observations.extend(_pages(url))
    return observations


def _ligne_depuis_point(
    serie: dict[str, Any],
    point: dict[str, Any],
    periodicite_demande: str,
) -> dict[str, str] | None:
    prix = point.get("price_value")
    date = point.get("date")
    if prix is None or date is None or str(date).strip() == "":
        return None
    periodicite = str(point.get("periodicity") or periodicite_demande or "").strip()
    return {
        "pays": "Bénin",
        "marche": str(serie.get("market_name") or ""),
        "departement": normaliser_departement(serie.get("admin_unit")),
        "commune": str(serie.get("admin_unit2") or ""),
        "produit": str(serie.get("commodity_name") or ""),
        "type": mapper_type_prix(serie.get("price_type")),
        "unite": str(serie.get("measure_unit_label") or ""),
        "devise": str(serie.get("currency") or ""),
        "date": str(date).strip()[:10],
        "prix": str(prix),
        "source_serie_id": str(serie.get("uuid") or ""),
        "periodicite": periodicite,
        "source": str(serie.get("source_name") or ""),
        "type_marche": str(serie.get("market_type") or ""),
    }


def lire_csv(chemin: Path) -> list[dict[str, str]]:
    if not chemin.is_file():
        return []
    with chemin.open("r", encoding="utf-8-sig", newline="") as f:
        lecteur = csv.DictReader(f)
        return [{c: (row.get(c) or "") for c in COLONNES} for row in lecteur]


def ecrire_csv(chemin: Path, lignes: list[dict[str, str]]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLONNES)
        writer.writeheader()
        for ligne in lignes:
            writer.writerow({c: ligne.get(c, "") for c in COLONNES})


def _dernieres_dates(lignes: list[dict[str, str]]) -> dict[str, str]:
    """Dernière date connue par source_serie_id."""
    max_par_serie: dict[str, str] = {}
    for ligne in lignes:
        sid = ligne.get("source_serie_id") or ""
        date = ligne.get("date") or ""
        if not sid or not date:
            continue
        if sid not in max_par_serie or date > max_par_serie[sid]:
            max_par_serie[sid] = date
    return max_par_serie


def _derniere_date_globale(lignes: list[dict[str, str]]) -> str | None:
    dates = [ligne.get("date") or "" for ligne in lignes if ligne.get("date")]
    return max(dates) if dates else None


def _fusionner(
    existantes: list[dict[str, str]],
    nouvelles: list[dict[str, str]],
) -> tuple[list[dict[str, str]], int]:
    """Fusion sans doublon sur (source_serie_id, date). Retourne (tout, nb_nouveaux)."""
    index: dict[tuple[str, str], dict[str, str]] = {}
    for ligne in existantes:
        cle = (ligne.get("source_serie_id") or "", ligne.get("date") or "")
        if cle[0] and cle[1]:
            index[cle] = ligne
    ajoutes = 0
    for ligne in nouvelles:
        cle = (ligne.get("source_serie_id") or "", ligne.get("date") or "")
        if not cle[0] or not cle[1]:
            continue
        if cle not in index:
            index[cle] = ligne
            ajoutes += 1
    fusion = sorted(index.values(), key=lambda r: (r.get("date") or "", r.get("source_serie_id") or ""))
    return fusion, ajoutes


def _collecter_observations(
    series: list[dict[str, Any]],
    base: str,
    dernieres: dict[str, str],
    *,
    premier_lancement: bool,
) -> list[dict[str, str]]:
    """Télécharge les prix et ne garde que les nouveaux points si CSV existant."""
    par_periodicite: dict[str, list[dict[str, Any]]] = {}
    for serie in series:
        period = choisir_periodicite(serie)
        if not period or not serie.get("uuid"):
            continue
        par_periodicite.setdefault(period, []).append(serie)

    series_par_uuid = {str(s["uuid"]): s for s in series if s.get("uuid")}
    nouvelles: list[dict[str, str]] = []

    for period, groupe in par_periodicite.items():
        uuids = [str(s["uuid"]) for s in groupe]
        lots = telecharger_prix(base, uuids, period)
        for obs in lots:
            uuid = str(obs.get("uuid") or "")
            serie = series_par_uuid.get(uuid)
            if not serie:
                continue
            seuil = None if premier_lancement else dernieres.get(uuid)
            for point in obs.get("datapoints") or []:
                if not isinstance(point, dict):
                    continue
                date = str(point.get("date") or "").strip()[:10]
                if not date:
                    continue
                if seuil is not None and not (date > seuil):
                    continue
                ligne = _ligne_depuis_point(serie, point, period)
                if ligne:
                    nouvelles.append(ligne)
    return nouvelles


def _journal_base_non_prete() -> None:
    logger.info("base non prête, CSV uniquement")


def lancer_maj_fao(
    *,
    chemin_csv: Path | str | None = None,
    tout_benin: bool = False,
) -> dict[str, Any]:
    """Met à jour le CSV FAO de façon incrémentale.

    N'élève pas d'exception réseau vers l'appelant : journalise et retourne l'échec.
    """
    _configurer_journal()
    chemin = Path(chemin_csv) if chemin_csv else CSV_DEFAUT
    resume: dict[str, Any] = {
        "succes": False,
        "nouveaux": 0,
        "derniere_date": None,
        "series_demandees": 0,
        "series_telechargees": 0,
        "erreur": None,
        "chemin": str(chemin),
    }

    _journal_base_non_prete()

    try:
        existantes = lire_csv(chemin)
        premier = len(existantes) == 0
        dernieres = _dernieres_dates(existantes)

        # Par défaut : API Bénin seule. --tout-benin : Bénin + mondial.
        bases: list[tuple[str, str]] = [(API_BENIN, "")]
        if tout_benin:
            bases.append((API_GLOBAL, "?iso3_country_code=BEN&limit=200"))

        series_retenues: list[tuple[str, dict[str, Any]]] = []
        for base, filtre in bases:
            brutes = lister_series(base, filtre)
            retenues = brutes if tout_benin else filtrer_series_mvp(brutes)
            for serie in retenues:
                series_retenues.append((base, serie))

        resume["series_demandees"] = len(series_retenues)
        logger.info("Séries demandées : %s", resume["series_demandees"])

        # Grouper par API (base URL) pour les appels prix.
        par_base: dict[str, list[dict[str, Any]]] = {}
        for base, serie in series_retenues:
            par_base.setdefault(base, []).append(serie)

        toutes_nouvelles: list[dict[str, str]] = []
        telechargees = 0
        for base, groupe in par_base.items():
            telechargees += len(groupe)
            toutes_nouvelles.extend(
                _collecter_observations(
                    groupe,
                    base,
                    dernieres,
                    premier_lancement=premier,
                )
            )
        resume["series_telechargees"] = telechargees
        logger.info("Séries téléchargées : %s", telechargees)

        if premier:
            # Premier lancement : écrire toutes les observations collectées.
            fusion, ajoutes = _fusionner([], toutes_nouvelles)
        else:
            fusion, ajoutes = _fusionner(existantes, toutes_nouvelles)

        ecrire_csv(chemin, fusion)
        resume["nouveaux"] = ajoutes
        resume["derniere_date"] = _derniere_date_globale(fusion)
        resume["succes"] = True
        logger.info("Nouveaux prix ajoutés : %s", ajoutes)
        logger.info("Dernière date présente : %s", resume["derniere_date"])
        return resume

    except Exception as exc:  # noqa: BLE001 — volontaire : ne pas casser le démarrage
        resume["erreur"] = str(exc)
        logger.error(
            "Échec réseau ou lecture FAO : %s — on garde les données existantes",
            exc,
        )
        # Ne pas détruire le CSV existant.
        if chemin.is_file():
            existantes = lire_csv(chemin)
            resume["derniere_date"] = _derniere_date_globale(existantes)
        return resume


def _main(argv: list[str] | None = None) -> int:
    _configurer_journal()
    parser = argparse.ArgumentParser(description="Mise à jour incrémentale des prix FAO (FPMA).")
    parser.add_argument(
        "--tout-benin",
        action="store_true",
        help="Tous les produits/marchés du Bénin (API Bénin + API mondiale).",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Chemin du CSV de sortie (défaut : data/raw/prix_fao.csv).",
    )
    args = parser.parse_args(argv)

    import os

    tout = bool(args.tout_benin) or os.environ.get("MAJ_FAO_TOUT_BENIN", "").lower() in {
        "1",
        "true",
        "oui",
        "yes",
    }
    resume = lancer_maj_fao(chemin_csv=args.csv, tout_benin=tout)
    return 0 if resume.get("succes") else 1


if __name__ == "__main__":
    raise SystemExit(_main())
