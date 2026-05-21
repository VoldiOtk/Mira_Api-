# VoFaLink / AIEKTalk

Projet de reconnaissance de la langue des signes (ASL) avec API temps réel, traduction et synthèse vocale.

## Dossier principal

Tout le code applicatif se trouve dans [`asl-recognition/`](asl-recognition/).

## Démarrage rapide

```bash
cd asl-recognition
python -m venv venv
# Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # puis renseigner les clés
python -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

## Données & modèles

Les dossiers lourds (`asl_videos`, `asl_images`, `asl_data`, `*.pth`) sont **ignorés par Git** (voir `.gitignore`).

Après clonage, préparer localement :

1. Placer les datasets sous `asl-recognition/data/knowledge/`
2. `python model/process_wlasl.py` et `python model/process_alphabet.py`
3. `python model/train.py` et `python model/train_alphabet.py`

## Configuration

Copier `asl-recognition/.env.example` vers `asl-recognition/.env` (jamais committer `.env`).
