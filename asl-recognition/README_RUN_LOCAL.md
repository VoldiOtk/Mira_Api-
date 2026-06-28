# Mira - Lancer le projet en local

## Prerequis

- Python 3.8+ installe et dans le PATH
- (Optionnel) Node.js 18+ pour rebuilder le dashboard admin

---

## Demarrage rapide

```
1. Double-cliquez start-backend.bat
2. Attendez le message "Application startup complete"
3. Ouvrez http://127.0.0.1:8000 dans votre navigateur
```

La premiere fois, le script cree automatiquement le venv et installe les dependances.

---

## Scripts disponibles

| Script | Description |
|---|---|
| `start-backend.bat` | Lance le backend FastAPI (cree le venv si absent, installe les deps) |
| `start-admin.bat` | Ouvre le dashboard admin dans le navigateur |
| `start-client.bat` | Ouvre l'espace client dans le navigateur |
| `start-all.bat` | Lance le backend et ouvre toutes les interfaces |
| `check-env.bat` | Verifie l'etat de l'environnement (Python, venv, ports, fichiers) |
| `install-backend.bat` | Installe uniquement les dependances Python (sans lancer le serveur) |

---

## URLs locales

| Interface | URL |
|---|---|
| Accueil Mira | http://127.0.0.1:8000 |
| Swagger / API Docs | http://127.0.0.1:8000/docs |
| Admin Dashboard | http://127.0.0.1:8000/admin |
| Espace Client | http://127.0.0.1:8000/espace-client |
| Reconnaissance live | http://127.0.0.1:8000/static/espace-client/live-reconnaissance.html |
| Prix / Offres | http://127.0.0.1:8000/prices |

---

## Configuration (.env)

Le fichier `.env` est cree automatiquement depuis `.env.example` au premier lancement.
Editez-le pour configurer :

```env
# Cle API Google Gemini (obligatoire si AI_PROVIDER=cloud)
GEMINI_API_KEY=your_google_api_key_here

# Mot de passe admin (acces /admin)
MIRA_ADMIN_PASSWORD=your_strong_admin_password

# Email admin (reset de mot de passe)
ADMIN_EMAIL=admin@example.com

# Provider IA : cloud (Gemini) | local (Ollama) | auto
AI_PROVIDER=cloud

# CORS — ajoutez vos domaines si vous deployez sur un autre port
ALLOWED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
```

---

## Architecture

Le backend FastAPI (port 8000) sert a la fois :
- L'API REST (`/api/v1/...`) et WebSocket (`/ws/video`)
- Le site Mira (pages statiques HTML depuis `frontend/`)
- L'admin dashboard React (`/admin`) depuis `frontend/dashboardadmin/dist/`
- L'espace client HTML (`/espace-client`) depuis `frontend/espace-client/`

### Admin Dashboard (React/Vite)

Le build React est pre-genere dans `frontend/dashboardadmin/dist/`.
Pour rebuilder apres modification des sources :

```bash
cd frontend/dashboardadmin
npm install
npm run build
```

Le nouveau build sera automatiquement servi par le backend.

Variables d'environnement pour le build (copier `.env.example` vers `.env`) :

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

---

## URLs hardcodees dans le frontend (a centraliser)

Les fichiers suivants contiennent des URLs hardcodees :

### frontend/espace-client/live-reconnaissance.html
- Ligne 575 : `var BASE_URL = 'http://localhost:8000';`
- Toutes les requetes API utilisent cette variable (elle est donc centralisee dans ce fichier).
- Pour la production, modifier uniquement cette ligne.

### frontend/dashboardadmin/src/pages/mira/Playground.jsx
- Ligne 4 : `const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';`
- Le composant lit `VITE_API_URL` depuis le `.env` Vite — il suffit de le definir.
- Pour la production, creer `frontend/dashboardadmin/.env` avec `VITE_API_URL=https://api.mira.com`.

---

## Configuration production

### Variables cles a changer

```env
APP_ENV=production
API_KEYS_REQUIRED=true
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000

ADMIN_FRONTEND_URL=https://admin.mira.com
CLIENT_FRONTEND_URL=https://client.mira.com
FRONTEND_ADMIN_URL=https://admin.mira.com/admin
APP_BASE_URL=https://mira.com

ALLOWED_ORIGINS=https://admin.mira.com,https://client.mira.com

SMTP_HOST=smtp.votre-hebergeur.com
SMTP_USER=no-reply@mira.com
SMTP_PASSWORD=votre_mot_de_passe_smtp
```

### Lancement production (SSH)

```bash
source venv/bin/activate
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

Ou via le script deploy fourni : `deploy/start_mira.sh`

---

## Depannage courant

**"uvicorn n'est pas reconnu"**
Les scripts utilisent `python -m uvicorn` — assurez-vous que le venv est active.
Lancez `install-backend.bat` pour reinstaller les dependances.

**Port 8000 deja utilise**
Lancez `check-env.bat` pour voir quel processus occupe le port, puis fermez-le.

**Admin affiche "Dashboard admin pas encore construit"**
Le build React est absent. Suivez les etapes dans la section Admin Dashboard ci-dessus.

**Erreur d'import au demarrage**
Verifiez que le `.env` est present et que `GEMINI_API_KEY` est rempli si `AI_PROVIDER=cloud`.
