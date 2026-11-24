# Notes pour la démo

La démo du mercredi 25/11 se fait avec le **simulateur** : un faux téléphone dans le navigateur, sans vrai appel.

1. Lancer l'application (`docker compose up` ou uvicorn).
2. Ouvrir la page du simulateur (`web/simulateur/`).
3. Parcourir le menu : 1 dernier prix relevé (la date du relevé est dite), 2 juger l'offre, 3 question à voix haute (ou « bientôt disponible »), 4 répéter.

Le détail du déroulé et le plan B (PC + tunnel Cloudflare si la machine en ligne n'est pas prête) sont dans le plan de réalisation.

## Touche 3 (question à voix haute) dans la console

1. Dans `.env` : `QUESTION_VOIX_ACTIVE=true` (et la clé Groq, jamais dans le dépôt).
2. `python -m app.dialogue.console`, choisir le produit, puis taper `3`.
3. Quand la console attend la voix :
   - `v data/test_touche3/wav/Q03.wav` : vraie chaîne (transcription Groq, sinon Whisper local, puis IA) ;
   - `t on me propose 125 francs le kilo de maïs blanc à Bohicon` : saute la transcription.
4. Si la couleur (maïs, haricot) ou le poids du sac n'est pas dit, le service le demande au clavier.
5. Repli : si la transcription ou l'IA échoue, ou si `QUESTION_VOIX_ACTIVE=false`, le service dit « Cette fonction arrive bientôt. » et revient au menu.
