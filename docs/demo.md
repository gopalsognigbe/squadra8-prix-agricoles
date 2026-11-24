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
4. L'appelant peut dire la ville ou le marché : Abomey ↔ Houndjro, Covè ↔ Azogotchébou, Bohicon ↔ Bohicon (variantes tolérées : abomé, kove, houndjoro…). L'annonce dit toujours le nom complet, par exemple « Houndjro (Abomey) ».
5. Le montant de l'offre peut être dit en chiffres ou en lettres (« quinze mille », « 15 000 », « vingt-cinq mille cinq cents »). Il est lu par l'IA et par une règle de secours ; s'ils ne sont pas d'accord, ou s'il manque, le service le fait taper.
6. Si la couleur (maïs, haricot) ou le poids du sac n'est pas dit, le service le demande au clavier.
   Si le montant est dit sans unité (« quinze mille pour le soja »), le service demande : 1 le kilo, 2 un sac de 100 kilos, 3 un autre sac.
7. Repli : si la transcription ou l'IA échoue, ou si `QUESTION_VOIX_ACTIVE=false`, le service dit « Cette fonction arrive bientôt. » et revient au menu.

## Test G8 et quota gratuit Groq

Ajouter `--pause 1.5` au script `data.scripts.test_touche3_audios` pour ne pas enchaîner 60 appels Groq en quelques secondes (erreurs 429). Au téléphone, une question n'appelle Groq qu'une fois pour la transcription et une fois pour l'intention ; un 429 est réessayé une seule fois si l'attente tient dans `IA_DELAI_MAX_S`, sinon on passe au repli.
