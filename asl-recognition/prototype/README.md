# VoFaLink Prototype

Prototype fonctionnel centré sur trois objectifs:

1. Reconnaissance des lettres (alphabet langue des signes)
2. Assemblage automatique des lettres en mots
3. Reconnaissance de mots/expressions simples
4. Sortie vocale neurale (Edge-TTS) pour les phrases reconnues

## Structure

- `app/`: API FastAPI + WebSocket + UI de démo
- `app/services/`: logique métier (reconnaissance, assemblage, mapping phrases)
- `data/phrases.json`: mapping configurable des expressions cibles
- `models/README.md`: conventions de modèles utilisés
- `tests/`: tests unitaires du coeur logique

## Lancement rapide

Depuis `asl-recognition/`:

```bash
python -m uvicorn prototype.app.main:app --reload --host 127.0.0.1 --port 8010
```

Puis ouvrir:

- `http://127.0.0.1:8010`

## Notes importantes

- Ce prototype réutilise les modèles existants du projet principal:
  - `model/model_hands.pth` pour les lettres
  - `model/model.pth` pour les gestes de mots
- La voix est générée via Edge-TTS (voix réelle), activable/mutable depuis l'UI.
- Le mode gestes simples applique une stabilisation temporelle (plusieurs frames)
  pour réduire les faux négatifs en conditions webcam réelles.
- Les expressions complexes (ex: "Comment ca va ?") peuvent venir:
  - soit d'un geste direct si présent dans les classes modèle
  - soit de l'assemblage de lettres en mot clé (`COMMENTCAVA`, etc.)
