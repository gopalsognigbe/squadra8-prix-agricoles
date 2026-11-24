"""Test G8 de la touche 3 sur les audios de questions-test (tâche manuelle).

Passe chaque fichier dans la vraie chaîne app.ia.transcription puis
app.ia.intention, remplit une copie du classeur, et affiche les taux.

Usage (depuis la racine du dépôt) :

  python -m data.scripts.test_touche3_audios \\
    --classeur data/test_touche3/Questions_test_vocales_Lube.xlsx \\
    --audios data/test_touche3/audios \\
    --wav data/test_touche3/wav \\
    --sortie data/test_touche3/Questions_test_vocales_resultats.xlsx
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

# Intention acceptée selon le type_attendu du classeur (critère G8 : intention seule).
TYPE_VERS_INTENTIONS = {
    "prix": frozenset({"prix"}),
    "offre": frozenset({"juger_offre"}),
    "hors_sujet": frozenset({"autre", "inconnu"}),
}

COLONNES_DEV = (
    "transcription_whisper",
    "intention_trouvee",
    "correct",
    "latence_s",
)


def normaliser_texte(valeur: str | None) -> str:
    """Minuscules sans accents, pour comparer les libellés du classeur aux codes."""
    texte = unicodedata.normalize("NFD", (valeur or "").strip().lower())
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


def intentions_acceptees(type_attendu: str) -> frozenset[str]:
    """Ensemble d'intentions code qui rendent la ligne juste au sens de G8."""
    cle = normaliser_texte(type_attendu).replace("-", "_").replace(" ", "_")
    return TYPE_VERS_INTENTIONS.get(cle, frozenset())


def est_correct_g8(type_attendu: str, intention: str | None) -> bool:
    """Vrai si l'intention renvoyée est juste (G8). Produit et marché ignorés.

    Mapping : prix → prix ; offre → juger_offre ; hors_sujet → autre ou inconnu.
    """
    return (intention or "") in intentions_acceptees(type_attendu)


def normaliser_produit(valeur: str | None) -> str | None:
    """Ramène un libellé Excel ou un code IA vers mais / soja / haricot."""
    if valeur is None or not str(valeur).strip():
        return None
    n = normaliser_texte(str(valeur))
    if "mais" in n.split() or n.startswith("mais"):
        return "mais"
    if "soja" in n or n == "soy":
        return "soja"
    if "haricot" in n or "niebe" in n:
        return "haricot"
    return n or None


def normaliser_marche(valeur: str | None) -> str | None:
    """Ramène un libellé Excel ou un code IA vers bohicon / abomey / cove."""
    if valeur is None or not str(valeur).strip():
        return None
    n = normaliser_texte(str(valeur))
    if "bohicon" in n:
        return "bohicon"
    if "houndjro" in n or "abomey" in n or "abome" in n:
        return "abomey"
    if "azogotchebou" in n or "cove" in n:
        return "cove"
    return n or None


def formater_intention(detail: dict | None) -> str:
    """Format compact pour la colonne intention_trouvee."""
    if not detail:
        return ""
    intention = detail.get("intention") or ""
    produit = detail.get("produit") or "-"
    marche = detail.get("marche") or "-"
    source = detail.get("source") or "-"
    return f"{intention} | {produit} | {marche} | {source}"


def _taux(ok: int, total: int) -> str:
    if total <= 0:
        return "n/a"
    return f"{ok}/{total} = {100.0 * ok / total:.1f} %"


def _oui_non(valeur: str | bool | None) -> str:
    if isinstance(valeur, bool):
        return "oui" if valeur else "non"
    n = normaliser_texte(str(valeur or "non"))
    return "oui" if n in {"oui", "o", "1", "true", "vrai"} else "non"


def convertir_en_wav(source: Path, dest: Path) -> None:
    """Convertit un audio en wav mono 16 kHz (prétraitement, hors latence G8)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    commande = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(dest),
    ]
    proc = subprocess.run(commande, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        message = err[-1] if err else f"code {proc.returncode}"
        raise RuntimeError(f"ffmpeg a échoué pour {source.name} : {message}")


def trouver_source(dossier_audios: Path, nom: str) -> Path | None:
    """Retrouve le fichier nommé dans le classeur, éventuellement dans un sous-dossier."""
    direct = dossier_audios / nom
    if direct.is_file():
        return direct
    candidats = list(dossier_audios.rglob(nom))
    return candidats[0] if candidats else None


def preparer_wav(nom_fichier: str, dossier_audios: Path, dossier_wav: Path) -> Path:
    """Retourne le wav 16 kHz, en le créant depuis le m4a/mp4 si besoin."""
    stem = Path(nom_fichier).stem
    wav = dossier_wav / f"{stem}.wav"
    if wav.is_file() and wav.stat().st_size > 0:
        return wav
    deja = dossier_audios / f"{stem}.wav"
    if deja.is_file() and deja.stat().st_size > 0:
        if deja.resolve() != wav.resolve():
            convertir_en_wav(deja, wav)
            return wav
        return deja
    source = trouver_source(dossier_audios, nom_fichier)
    if source is None:
        raise FileNotFoundError(f"audio introuvable : {nom_fichier}")
    convertir_en_wav(source, wav)
    return wav


def _lire_en_tete(feuille, ligne: int) -> dict[str, int]:
    en_tete: dict[str, int] = {}
    for col in range(1, feuille.max_column + 1):
        valeur = feuille.cell(ligne, col).value
        if valeur:
            en_tete[str(valeur).strip()] = col
    return en_tete


def trouver_ligne_en_tete(feuille) -> int:
    for ligne in range(1, min(feuille.max_row, 10) + 1):
        en_tete = _lire_en_tete(feuille, ligne)
        if "id" in en_tete and "nom_du_fichier_audio" in en_tete:
            return ligne
    raise ValueError("ligne d'en-têtes introuvable (id, nom_du_fichier_audio)")


def evaluer_ligne(
    type_attendu: str,
    produit_attendu: str | None,
    marche_attendu: str | None,
    intention_detail: dict | None,
) -> dict:
    """Calcule correct G8 et les diagnostics produit / marché / strict."""
    intention = (intention_detail or {}).get("intention")
    correct = est_correct_g8(type_attendu, intention)
    prod_att = normaliser_produit(produit_attendu)
    prod_tr = normaliser_produit((intention_detail or {}).get("produit"))
    march_att = normaliser_marche(marche_attendu)
    march_tr = normaliser_marche((intention_detail or {}).get("marche"))
    prod_ok = (prod_tr == prod_att) if prod_att else None
    march_ok = (march_tr == march_att) if march_att else None
    strict = correct
    if prod_ok is False:
        strict = False
    if march_ok is False:
        strict = False
    return {
        "correct": correct,
        "produit_ok": prod_ok,
        "marche_ok": march_ok,
        "strict": strict,
    }


def _imprimer_taux(titre: str, lignes: list[dict]) -> None:
    ok = sum(1 for L in lignes if L["correct"])
    print(f"  {titre}: {_taux(ok, len(lignes))}")


def afficher_rapport(lignes: list[dict], modele_whisper: str) -> None:
    """Affiche les taux G8, les diagnostics et la décision. N'invente rien."""
    n = len(lignes)
    print()
    print("=" * 72)
    print("Règle « correct » (G8) : intention seulement.")
    print("  type_attendu prix        → intention prix")
    print("  type_attendu offre       → intention juger_offre")
    print("  type_attendu hors_sujet  → intention autre ou inconnu")
    print("Produit et marché : diagnostic, hors du 80 % G8.")
    print(f"Moteurs de ce run : transcription locale faster-whisper « {modele_whisper} »")
    print("  (pas Groq Whisper) ; intention selon la chaîne du code")
    print("  (Groq → Gemini → règles). S'il n'y a pas de clé, ce sont les règles.")
    print("=" * 72)

    erreurs = [L for L in lignes if L.get("erreur")]
    print(f"Lignes traitées : {n}/30")
    print(f"Erreurs techniques (fichier manquant, AudioTropLong, exception) : {len(erreurs)}")
    for L in erreurs:
        print(f"  - {L['id']}: {L['erreur']}")

    print()
    print("Taux de réussite G8 (intention) :")
    _imprimer_taux("global", lignes)
    for voix in ("L01", "L02", "L03"):
        sous = [L for L in lignes if L.get("code_locuteur") == voix]
        _imprimer_taux(f"voix {voix}", sous)
    _imprimer_taux("avec bruit", [L for L in lignes if L.get("avec_bruit") == "oui"])
    _imprimer_taux("sans bruit", [L for L in lignes if L.get("avec_bruit") == "non"])
    for typ in ("prix", "offre", "hors_sujet"):
        sous = [L for L in lignes if normaliser_texte(L.get("type_attendu")) == typ]
        _imprimer_taux(f"type {typ}", sous)

    prod = [L for L in lignes if L.get("produit_ok") is not None]
    march = [L for L in lignes if L.get("marche_ok") is not None]
    print()
    print("Diagnostic (hors G8) :")
    print(
        f"  produit (lignes avec produit_attendu) : {_taux(sum(1 for L in prod if L['produit_ok']), len(prod))}"
    )
    print(
        f"  marché  (lignes avec marche_attendu)  : {_taux(sum(1 for L in march if L['marche_ok']), len(march))}"
    )
    print(
        f"  taux strict (intention + slots attendus) : {_taux(sum(1 for L in lignes if L['strict']), n)}"
    )

    latences = [L["latence_s"] for L in lignes if L.get("latence_s") is not None]
    print()
    if latences:
        mediane = statistics.median(latences)
        maximum = max(latences)
        depass = [L for L in lignes if (L.get("latence_s") or 0) > 6]
        print("Latence (transcription + intention uniquement) :")
        print(f"  médiane : {mediane:.3f} s")
        print(f"  maximale : {maximum:.3f} s")
        print(
            f"  lignes > 6 s : {len(depass)}"
            + (f" ({', '.join(L['id'] for L in depass)})" if depass else "")
        )
    else:
        mediane = None
        print("Latence : aucune mesure.")

    trans_moteurs = Counter(L.get("moteur_transcription") or "?" for L in lignes)
    int_moteurs = Counter(L.get("moteur_intention") or "?" for L in lignes)
    print()
    print(f"Moteurs transcription : {dict(trans_moteurs)}")
    print(f"Moteurs intention     : {dict(int_moteurs)}")

    ratees = [L for L in lignes if not L["correct"]]
    print()
    print(f"Questions ratées ({len(ratees)}) :")
    if not ratees:
        print("  (aucune)")
    for L in ratees:
        print(
            f"  - {L['id']} type={L.get('type_attendu')} trouvé={L.get('intention_trouvee')!r}"
            f"  transcription={L.get('transcription')!r}"
        )

    ok = sum(1 for L in lignes if L["correct"])
    taux = (100.0 * ok / n) if n else 0.0
    print()
    print("Décision G8 (≥ 80 % d'intentions justes et latence médiane ≤ 6 s) :")
    if n == 0 or mediane is None:
        print("  Impossible de trancher (aucune ligne ou pas de latence).")
        return
    atteint = (taux >= 80.0) and (mediane <= 6.0)
    if atteint:
        print(
            f"  ATTEINT ({taux:.1f} %, médiane {mediane:.3f} s) → recommandation : montrer la touche 3"
        )
        print("  (touche 3 branchée : QUESTION_VOIX_ACTIVE=true dans .env pour la montrer).")
    else:
        print(f"  NON ATTEINT ({taux:.1f} %, médiane {mediane:.3f} s) → « bientôt disponible ».")
    if latences and max(latences) > 6:
        print("  Attention : au moins une latence dépasse 6 s (risque, hors échec automatique).")


def executer(
    classeur: Path,
    dossier_audios: Path,
    dossier_wav: Path,
    sortie: Path,
    modele_whisper: str,
) -> list[dict]:
    """Parcourt le classeur, lance la vraie chaîne, écrit la copie de résultats."""
    # Import tardif : openpyxl n'est pas dans requirements.txt (script manuel).
    import openpyxl

    from app.config import get_settings
    from app.ia.intention import comprendre
    from app.ia.transcription import AudioTropLong, transcrire_detail

    get_settings.cache_clear()
    settings = get_settings()
    print(
        f"Réglages : whisper_modele={settings.whisper_modele} "
        f"audio_max_s={settings.audio_max_s} "
        f"clé Groq={'oui' if (settings.openai_api_key or '').strip() else 'non'} "
        f"clé Gemini={'oui' if (settings.gemini_api_key or '').strip() else 'non'}"
    )
    if settings.whisper_modele != modele_whisper:
        print(
            f"Attention : --modele={modele_whisper} mais settings={settings.whisper_modele}. "
            "Exportez WHISPER_MODELE avant le lancement.",
            file=sys.stderr,
        )

    wb = openpyxl.load_workbook(classeur)
    if "4_A_remplir" not in wb.sheetnames:
        raise ValueError(f"onglet 4_A_remplir absent (onglets : {wb.sheetnames})")
    feuille = wb["4_A_remplir"]
    ligne_en_tete = trouver_ligne_en_tete(feuille)
    cols = _lire_en_tete(feuille, ligne_en_tete)
    for nom in ("id", "type_attendu", "nom_du_fichier_audio", *COLONNES_DEV):
        if nom not in cols:
            raise ValueError(f"colonne manquante : {nom}")

    lignes: list[dict] = []
    for row in range(ligne_en_tete + 1, feuille.max_row + 1):
        identifiant = feuille.cell(row, cols["id"]).value
        if not identifiant:
            continue
        identifiant = str(identifiant).strip()
        if not identifiant.upper().startswith("Q"):
            continue
        nom_audio = feuille.cell(row, cols["nom_du_fichier_audio"]).value
        type_attendu = feuille.cell(row, cols["type_attendu"]).value
        produit_attendu = (
            feuille.cell(row, cols.get("produit_attendu", 0)).value
            if "produit_attendu" in cols
            else None
        )
        marche_attendu = (
            feuille.cell(row, cols.get("marche_attendu", 0)).value
            if "marche_attendu" in cols
            else None
        )
        locuteur = (
            feuille.cell(row, cols.get("code_locuteur", 0)).value
            if "code_locuteur" in cols
            else None
        )
        bruit = feuille.cell(row, cols.get("avec_bruit", 0)).value if "avec_bruit" in cols else None

        enregistrement: dict = {
            "id": identifiant,
            "code_locuteur": str(locuteur or "").strip(),
            "avec_bruit": _oui_non(bruit),
            "type_attendu": str(type_attendu or "").strip(),
            "produit_attendu": produit_attendu,
            "marche_attendu": marche_attendu,
            "transcription": "",
            "intention_trouvee": "",
            "correct": False,
            "strict": False,
            "produit_ok": None,
            "marche_ok": None,
            "latence_s": None,
            "erreur": "",
            "moteur_transcription": "",
            "moteur_intention": "",
        }

        texte = ""
        detail = None
        debut = None
        try:
            wav = preparer_wav(str(nom_audio or "").strip(), dossier_audios, dossier_wav)
            debut = time.perf_counter()
            tr = transcrire_detail(wav)
            texte = (tr.get("texte") or "").strip()
            enregistrement["moteur_transcription"] = tr.get("moteur") or ""
            detail = comprendre(texte)
            enregistrement["latence_s"] = round(time.perf_counter() - debut, 3)
            enregistrement["moteur_intention"] = (detail or {}).get("source") or ""
        except AudioTropLong as exc:
            if debut is not None:
                enregistrement["latence_s"] = round(time.perf_counter() - debut, 3)
            enregistrement["erreur"] = f"AudioTropLong: {exc}"
            enregistrement["moteur_transcription"] = "local"
        except Exception as exc:  # noqa: BLE001 — on veut continuer les 30 lignes
            if debut is not None:
                enregistrement["latence_s"] = round(time.perf_counter() - debut, 3)
            enregistrement["erreur"] = f"{type(exc).__name__}: {exc}"

        enregistrement["transcription"] = texte or enregistrement["erreur"]
        enregistrement["intention_trouvee"] = formater_intention(detail)
        verdict = evaluer_ligne(
            enregistrement["type_attendu"],
            produit_attendu,
            marche_attendu,
            detail,
        )
        if enregistrement["erreur"]:
            verdict["correct"] = False
            verdict["strict"] = False
        enregistrement.update(verdict)

        feuille.cell(row, cols["transcription_whisper"]).value = enregistrement["transcription"]
        feuille.cell(row, cols["intention_trouvee"]).value = enregistrement["intention_trouvee"]
        feuille.cell(row, cols["correct"]).value = "oui" if enregistrement["correct"] else "non"
        feuille.cell(row, cols["latence_s"]).value = enregistrement["latence_s"]
        lignes.append(enregistrement)
        etat = "oui" if enregistrement["correct"] else "NON"
        print(
            f"{identifiant} correct={etat} {enregistrement['latence_s']}s "
            f"{enregistrement['intention_trouvee'] or enregistrement['erreur']}",
            flush=True,
        )

    sortie.parent.mkdir(parents=True, exist_ok=True)
    wb.save(sortie)
    print(f"\nClasseur résultats : {sortie}")
    afficher_rapport(lignes, modele_whisper=modele_whisper)
    return lignes


def construire_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test G8 touche 3 sur les 30 audios.")
    parser.add_argument(
        "--classeur", type=Path, required=True, help="xlsx source (onglet 4_A_remplir)"
    )
    parser.add_argument(
        "--audios", type=Path, required=True, help="dossier des m4a/mp4 (ou wav déjà convertis)"
    )
    parser.add_argument(
        "--wav", type=Path, required=True, help="dossier de sortie des wav 16 kHz mono"
    )
    parser.add_argument(
        "--sortie", type=Path, required=True, help="copie xlsx remplie (ne pas écraser la source)"
    )
    parser.add_argument(
        "--modele",
        default="base",
        help="modèle faster-whisper (ex. base ou small) ; définit WHISPER_MODELE avant les imports IA",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = construire_parser().parse_args(argv)
    if args.sortie.resolve() == args.classeur.resolve():
        print("Erreur : --sortie doit être une copie, pas le classeur source.", file=sys.stderr)
        return 2
    # Avant d'importer app.config / transcription, pour que get_settings() lise la bonne valeur.
    import os

    os.environ["WHISPER_MODELE"] = args.modele
    executer(
        classeur=args.classeur,
        dossier_audios=args.audios,
        dossier_wav=args.wav,
        sortie=args.sortie,
        modele_whisper=args.modele,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
