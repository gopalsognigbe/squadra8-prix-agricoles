# Squadra 8 – Prix agricoles

Service téléphonique qui donne aux producteurs du Zou les prix agricoles (maïs, soja, haricot) sur quelques marchés. Le producteur appelle et raccroche tout de suite (c'est gratuit pour lui) : le service le rappelle automatiquement. Il choisit ensuite avec les touches du téléphone, ou pose une question à voix haute.

**Règle du projet : « l'IA comprend, la base répond ».** L'intelligence artificielle (le programme qui comprend une phrase) ne donne jamais un prix elle-même. Elle comprend seulement ce que la personne veut : un prix, juger une offre, ou autre chose. C'est ensuite la base de données qui fournit le prix, s'il a été validé par une personne. Si la base n'a pas de prix validé, le service le dit clairement.

## Lancer le projet en local

Deux façons : avec Docker (le plus simple, la base de données est incluse) ou avec Python seul.

### 1. Préparer le fichier des secrets

Copier le modèle, puis remplir les clés en privé (jamais dans Git) :

```bash
cp .env.example .env
```

### 2. Avec Docker (recommandé)

Docker lance l'application et PostgreSQL 16 ensemble.

```bash
docker compose up --build
# Dans un second terminal, après démarrage :
docker compose exec app alembic upgrade head
docker compose exec app python -m app.db.seed
```

L'interface d'administration est disponible sur `/admin/`. Avant la première connexion, renseigner dans `.env` : `ADMIN_EMAIL`, `ADMIN_PASSWORD_INITIAL` et `ADMIN_SESSION_SECRET` (une valeur longue et aléatoire). Le compte initial est créé par le seed uniquement si cet e-mail n'existe pas. L'API admin est documentée dans `/docs`. Les prix importés restent en attente jusqu'à validation humaine. Tant que `SOURCE_PRIX=fao` (défaut), les routes publiques lisent le CSV FAO (plan B). Avec `SOURCE_PRIX=base`, elles ne renvoient que les observations validées, au détail au kilo, âgées de 60 jours maximum, avec la date de relevé (jamais « prix du jour »).

Ouvrir ensuite dans le navigateur : [http://localhost:8000/health](http://localhost:8000/health). Tu dois voir `{"ok": true}`. L'adresse [http://localhost:8000/sante](http://localhost:8000/sante) répond aussi `{"statut": "ok"}`.

### 3. Avec Python (sans Docker)

Il te faut Python 3.11. PostgreSQL 16 est nécessaire pour l'application complète ; les tests automatiques, eux, n'en ont pas besoin.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Même vérification : ouvrir `/health` ou `/sante` comme ci-dessus.

Les programmes de voix (Whisper pour transcrire, Piper pour parler) sont optionnels et lourds. Ils s'installent à part : `pip install -r requirements-voix.txt` (Guillaume). Sur la machine de démo (Mac), après installation :

```bash
pip install -r requirements-voix.txt
python -m piper.download_voices fr_FR-siwis-medium --download-dir models/piper
python -m app.voix.generer_clips
python -m app.voix.dire "Maïs blanc à Bohicon : cent trente-sept francs."
```

Les clips et le modèle **ne vont pas dans Git** (`models/`, `voix/clips/` sont ignorés). Il faut les régénérer sur la machine qui fera la démo, après chaque changement de phrase. Sur macOS, `dire` affiche le chemin du `.wav` : on peut l'écouter avec `afplay` sur ce chemin.

## Comment on travaille sur le code

- La branche **main** est protégée : personne n'écrit dessus directement. C'est la version principale, celle qui doit toujours marcher.
- Une **branche** par tâche, nommée `feat/<id>-<sujet>` (exemple : `feat/P2-import-fao`), ou `fix/…`, `docs/…`.
- Pour faire entrer son travail dans main, on ouvre une **pull request** (demande de fusion). Un autre développeur relit et **approuve** (1 approbation). La CI (vérifications automatiques : style du code avec ruff, tests avec pytest) doit être verte.
- Celui qui ouvre la demande la fusionne après l'approbation (squash : tous les petits changements deviennent un seul). Messages de commit courts, au présent : `feat: …`, `fix: …`, `test: …`, `docs: …`.

## Qui s'occupe de quoi

| Dossier ou fichier | Responsable | Rôle |
|---|---|---|
| `app/main.py`, `app/config.py` | Gopal | Démarrage de l'application et lecture du `.env` |
| `app/ia/intention.py`, `app/ia/regles.py`, `app/ia/anomalies.py` | Gopal | L'IA comprend l'intention ; les règles prennent le relais si besoin ; signalement des prix bizarres |
| `app/services/calculs.py`, `app/api/prix.py`, `app/api/ia.py` | Gopal | Calcul de l'offre (écart en francs) et routes associées |
| `app/dialogue/`, `app/voix/` | Guillaume | Moteur de dialogue (ce qu'on dit à chaque étape) et voix de synthèse (Piper) |
| `app/ia/transcription.py`, `app/api/sim.py`, `app/api/twilio.py` | Guillaume | Transcription de la voix (Whisper), routes du simulateur, bonus Twilio |
| `app/db/`, `data/`, `app/services/prix_service.py`, `app/api/admin.py`, `web/admin/` | Precious | Base de données, import des prix FAO, lecture des prix validés, page admin |
| `web/simulateur/`, `app/services/anti_abus.py`, `app/services/numeros.py` | 4e développeur (à confirmer) | Faux téléphone pour la démo, limites d'usage, chiffrement des numéros |
| `tests/` | chacun | Un fichier de test par module |
| `docs/` | Gopal | Documents du projet (DAT, plan, architecture, notes de démo) |

## Liens

- Plan de réalisation : [docs/Plan_realisation_Squadra8.docx](docs/Plan_realisation_Squadra8.docx)
- Document d'architecture technique (DAT) : [docs/DAT_v3_Squadra8.docx](docs/DAT_v3_Squadra8.docx)
- Schéma d'architecture : [docs/architecture.mmd](docs/architecture.mmd)
- Notes pour la démo : [docs/demo.md](docs/demo.md)

Licence : MIT (fichier `LICENSE` déjà présent dans le dépôt GitHub).
