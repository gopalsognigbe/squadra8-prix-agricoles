"""Jouer un appel dans le terminal : python -m app.dialogue.console

Touche 3 (QUESTION_VOIX_ACTIVE=true) : quand le moteur attend la voix, taper
  v chemin/vers/question.wav   → vraie chaîne (transcription puis IA)
  t on me propose 12000 francs le kilo de soja   → saute la transcription
"""

from __future__ import annotations

import threading

from app.config import get_settings
from app.dialogue.moteur import Evenement, Moteur
from app.dialogue.question_voix import PREFIXE_TEXTE
from app.dialogue.services_prix import services_reels


def main() -> None:
    settings = get_settings()
    if settings.question_voix_active:
        # Whisper local chargé en fond : le repli ne coûte pas ce chargement en plein appel.
        from app.ia.transcription import prechauffer_local

        threading.Thread(target=prechauffer_local, daemon=True).start()
    moteur = Moteur(
        services_reels(),
        voix_active=settings.question_voix_active,
        delai_voix=int(settings.audio_max_s),
    )
    sess = moteur.nouvelle_session("console")
    tour = moteur.traiter(sess, Evenement(type="DECROCHE"))
    while True:
        for p in tour.phrases:
            print(f"  [{p.id}] {p.texte}")
        if tour.fin:
            print("--- fin de l'appel ---")
            break
        print(f"  (attend : {tour.attente} {tour.touches_valides})")
        if tour.attente == "voix":
            print("  (voix : « v fichier.wav » ou « t votre phrase »)")
        saisie = input("touche (vide = silence, q = raccrocher) > ").strip()
        if saisie == "q":
            evenements = [Evenement(type="RACCROCHE")]
        elif tour.attente == "voix" and saisie[:2] in ("v ", "t "):
            valeur = saisie[2:].strip()
            if saisie.startswith("t "):
                valeur = PREFIXE_TEXTE + valeur
            evenements = [Evenement(type="VOIX", valeur=valeur)]
        elif saisie == "":
            evenements = [Evenement(type="SILENCE")]
        else:
            evenements = [
                Evenement(type="TOUCHE", valeur=c) for c in saisie.replace(" ", "")
            ]
        for ev in evenements:
            tour = moteur.traiter(sess, ev)
            if tour.fin:
                break


if __name__ == "__main__":
    main()
