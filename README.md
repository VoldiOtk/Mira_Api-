# Mira AI — AIEKTalk / GV Tech

Traduction langue des signes américaine (ASL) : reconnaissance temps réel, API REST, site web et synthèse vocale.

## Dossier principal

Tout le code est dans [`asl-recognition/`](asl-recognition/).

## Démarrage rapide (local)

**Windows** — à la racine du repo :

```powershell
.\start_api.ps1
```

**Ou manuellement :**

```bash
cd asl-recognition
python -m venv venv
# Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # puis renseigner les clés
python -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

- Site : http://127.0.0.1:8000/
- App : http://127.0.0.1:8000/app
- API : http://127.0.0.1:8000/docs
- Admin : http://127.0.0.1:8000/admin

## Déploiement PlanetHoster

- VPS / SSH : [`asl-recognition/docs/DEPLOY_PLANETHOSTER.md`](asl-recognition/docs/DEPLOY_PLANETHOSTER.md)
- Passenger N0C : [`asl-recognition/deploy/planethoster-n0c.md`](asl-recognition/deploy/planethoster-n0c.md)

## Données & modèles

Les dossiers lourds (`asl_videos`, `asl_data`, `*.pth`) sont ignorés par Git (voir `.gitignore`).

Après clonage : placer les datasets, lancer `model/process_wlasl.py`, puis `model/train.py`.

## Documentation

| Fichier | Contenu |
|---------|---------|
| `asl-recognition/docs/API.md` | API REST v1 |
| `asl-recognition/docs/PLAN_ASL_FR.md` | Plan vocabulaire WLASL |

Copier `asl-recognition/.env.example` vers `.env` — **ne jamais committer** `.env`.
