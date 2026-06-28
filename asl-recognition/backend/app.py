from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from backend.limiter import limiter
import os
import sys
import uuid
from dotenv import load_dotenv

# Ensure UTF-8 stdout/stderr — Windows consoles default to cp1252, which crashes
# the app on startup prints containing arrows ("→") or accented characters.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
import json
import asyncio
import time
import mimetypes

mimetypes.add_type('text/css', '.css')
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('image/svg+xml', '.svg')

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.gemini_client import GeminiTranslator
from utils.ollama_client import OllamaTranslator
from utils.sign_resolver import (
    FingerspellBuffer,
    should_speak_instantly,
    speech_text_for_label,
)
from utils.text_to_sign import text_to_sign_service
from tts.speech import TTSEngine
from backend.routes_v1 import router as api_v1_router
from backend.routes_admin import router as admin_router, access_router
from backend.deps.auth import require_api_key, API_KEYS_REQUIRED
from backend.services import api_access_store
from backend.services.recognition_engine import (
    predict_frame,
    decode_image_b64,
    find_translation,
    normalize_lang,
)

TTS_VOICES = {
    "fr": os.getenv("TTS_VOICE_FR", "fr-FR-DeniseNeural"),
    "en": os.getenv("TTS_VOICE_EN", "en-US-JennyNeural"),
}
tts = TTSEngine(voice=TTS_VOICES["fr"])
AI_PROVIDER = os.getenv("AI_PROVIDER", "local").strip().lower()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e2b").strip()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")


class TranslatorRouter:
    def __init__(self):
        self.provider = AI_PROVIDER
        self.local_translator = OllamaTranslator(
            model_name=OLLAMA_MODEL,
            base_url=OLLAMA_BASE_URL,
        )
        self.cloud_translator = GeminiTranslator()

    async def prepare(self):
        if self.provider in {"local", "auto"}:
            await self.local_translator.check_and_start()

    async def translate_asl(self, sign_sequence, lang="fr"):
        lang = normalize_lang(lang)
        if self.provider == "local":
            return await self.local_translator.translate_asl(sign_sequence, lang=lang)
        if self.provider == "cloud":
            return await self.cloud_translator.translate_asl(sign_sequence, lang=lang)

        local_sentence = await self.local_translator.translate_asl(sign_sequence, lang=lang)
        if "(Ollama hors-ligne)" not in local_sentence:
            return local_sentence
        return await self.cloud_translator.translate_asl(sign_sequence, lang=lang)


ai_translator = TranslatorRouter()

app = FastAPI(
    title="Mira — API de reconnaissance des langues des signes",
    description=(
        "API officielle **Mira**, produit technologique de **GV TECH** — reconnaissance progressive des langues des signes.\n\n"
        "### Authentification\n"
        "Les routes protégées exigent le header **`X-API-Key`** (clé fournie après validation).\n"
        "Demande d'accès : [POST /api/v1/access/request](/api/v1/access/request) ou page [/access](/access).\n\n"
        "### Endpoints principaux\n"
        "| Méthode | Route | Description |\n"
        "|---------|-------|-------------|\n"
        "| POST | `/api/v1/recognize` | Image → sign language prediction + traduction FR/EN |\n"
        "| POST | `/api/v1/text-to-sign` | Texte → vidéo/image du signe |\n"
        "| GET | `/api/v1/health` | État du service |\n"
        "| WS | `/ws/video` | Flux webcam temps réel (sign language demo) |\n"
    ),
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

# Rate limiter — must be attached before middleware / routers that use it
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# SaaS routers (auth, API key management, usage, inference, datasets, models, training)
from backend.routers.auth_router import router as saas_auth_router  # noqa: E402
from backend.routers.inference_router import router as saas_inference_router  # noqa: E402
from backend.routers.keys_router import router as saas_keys_router  # noqa: E402
from backend.routers.usage_router import router as saas_usage_router  # noqa: E402
from backend.routers.datasets_router import router as saas_datasets_router  # noqa: E402
from backend.routers.models_router import admin_router as saas_models_admin_router, public_router as saas_models_public_router, feedback_admin_router as saas_feedback_admin_router  # noqa: E402
from backend.routers.training_router import router as saas_training_router  # noqa: E402
from backend.routers.stripe_router import router as saas_stripe_router  # noqa: E402
from backend.routers.dashboard_router import router as saas_dashboard_router  # noqa: E402
from backend.routers.billing_router import (  # noqa: E402
    plans_router as saas_plans_router,
    subscription_router as saas_subscription_router,
    admin_plans_router as saas_admin_plans_router,
)
from backend.routers.admin_clients_router import router as saas_admin_clients_router  # noqa: E402
from backend.routers.client_router import router as saas_client_router  # noqa: E402
from backend.metrics import router as metrics_router  # noqa: E402
from backend.routers.notifications_router import router as saas_notifications_router  # noqa: E402
from backend.routers.messages_router import admin_router as saas_messages_admin_router, client_router as saas_messages_client_router  # noqa: E402
from backend.routers.invoice_router import router as saas_invoice_router  # noqa: E402
from backend.routers.knowledge_router import router as saas_knowledge_router  # noqa: E402
from backend.routers.admin_errors_router import router as saas_admin_errors_router  # noqa: E402
from backend.routers.public_v1_router import router as public_v1_router  # noqa: E402
from backend.routers.admin_router import router as saas_admin_v1_router  # noqa: E402

# Inference router first — takes priority over legacy api_v1_router on /recognize
app.include_router(saas_admin_v1_router)
app.include_router(saas_knowledge_router)
app.include_router(public_v1_router)
app.include_router(saas_inference_router)
app.include_router(api_v1_router, include_in_schema=False)
app.include_router(access_router, include_in_schema=False)
app.include_router(admin_router, include_in_schema=False)

app.include_router(saas_auth_router)
app.include_router(saas_keys_router)
app.include_router(saas_usage_router)
app.include_router(saas_datasets_router)
app.include_router(saas_models_admin_router)
app.include_router(saas_models_public_router)
app.include_router(saas_feedback_admin_router)
app.include_router(saas_admin_errors_router)
app.include_router(saas_training_router)
app.include_router(saas_stripe_router)
app.include_router(saas_dashboard_router)
app.include_router(saas_plans_router)
app.include_router(saas_subscription_router)
app.include_router(saas_admin_plans_router)
app.include_router(saas_admin_clients_router)
app.include_router(saas_client_router)
app.include_router(metrics_router)
app.include_router(saas_notifications_router)
app.include_router(saas_messages_admin_router)
app.include_router(saas_messages_client_router)
app.include_router(saas_invoice_router)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})[
        "ApiKeyAuth"
    ] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "Clé API Mira (fournie après approbation admin)",
    }
    public_paths = {
        "/api/v1/health",
        "/api/v1/access/request",
    }
    for path, methods in schema.get("paths", {}).items():
        if path.startswith("/api/admin"):
            continue
        if path in public_paths:
            continue
        if path.startswith("/api/v1") and path != "/api/v1/access/request":
            for method in methods.values():
                if isinstance(method, dict):
                    method.setdefault("security", [{"ApiKeyAuth": []}])
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


class ApiAccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/v1"):
            if path.endswith("/access/request") or path == "/api/v1/health":
                return response
            org = getattr(request.state, "api_org", None)
            log_kwargs = dict(
                path=path,
                method=request.method,
                status_code=response.status_code,
                org_id=org.get("id") if org else None,
                org_name=org.get("organization_name") if org else None,
                client_ip=request.client.host if request.client else None,
                detail="",
            )
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: api_access_store.log_request(**log_kwargs))
        return response


app.add_middleware(ApiAccessLogMiddleware)

# CORS — origins are read from ALLOWED_ORIGINS env var (comma-separated)
_raw_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:5173,http://localhost:8000,http://127.0.0.1:8000,http://127.0.0.1:8001,http://localhost:8001,http://127.0.0.1:8002,http://localhost:8002",
)
_ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Don't add HSTS in dev (only in production with HTTPS)
        return response


app.add_middleware(SecurityHeadersMiddleware)

# Servir le frontend directement via FastAPI (comme avant !)
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "knowledge")
SIGN_VIDEOS_DIR = os.path.join(KNOWLEDGE_DIR, "asl_videos", "videos")
SIGN_LETTERS_DIR = os.path.join(KNOWLEDGE_DIR, "asl_images", "asl_alphabet_train")

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

if os.path.isdir(SIGN_VIDEOS_DIR):
    app.mount("/media/signs/videos", StaticFiles(directory=SIGN_VIDEOS_DIR), name="sign_videos")
if os.path.isdir(SIGN_LETTERS_DIR):
    app.mount("/media/signs/letters", StaticFiles(directory=SIGN_LETTERS_DIR), name="sign_letters")


def _frontend_html_response(filename: str):
    path = os.path.join(FRONTEND_DIR, filename)
    if not os.path.exists(path):
        return HTMLResponse(content="<h1>Page coming soon</h1>", status_code=404)
    with open(path, encoding="utf-8") as f:
        html = f.read()
    if "<base " not in html:
        html = html.replace("<head>", '<head>\n        <base href="/static/" />', 1)
    return HTMLResponse(content=html)


@app.get("/api/text-to-sign", include_in_schema=False, dependencies=[Depends(require_api_key)])
async def api_text_to_sign(text: str, lang: str = "fr"):
    return text_to_sign_service.lookup(text, lang=lang)


@app.get("/api/text-to-sign/search", include_in_schema=False, dependencies=[Depends(require_api_key)])
async def api_text_to_sign_search(q: str = "", lang: str = "fr", limit: int = 25):
    return {
        "lang": normalize_lang(lang),
        "query": q,
        "results": text_to_sign_service.search(q, lang=lang, limit=min(limit, 50)),
        "vocabulary": text_to_sign_service.vocabulary_stats(),
    }


@app.get("/api/text-to-sign/vocabulary", include_in_schema=False, dependencies=[Depends(require_api_key)])
async def api_text_to_sign_vocabulary():
    return text_to_sign_service.vocabulary_stats()


@app.get("/api/text-to-sign/suggestions", include_in_schema=False, dependencies=[Depends(require_api_key)])
async def api_text_to_sign_suggestions(lang: str = "fr", limit: int = 16):
    return {
        "lang": normalize_lang(lang),
        "vocabulary": text_to_sign_service.vocabulary_stats(),
        "suggestions": text_to_sign_service.list_suggestions(lang=lang, limit=min(limit, 50)),
    }

def _build_docs_page() -> str:
    html = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Documentation API Swagger — Mira</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
(function(){
  SwaggerUIBundle({
    url: "/openapi.json",
    dom_id: "#swagger-ui",
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
    layout: "BaseLayout",
    docExpansion: "list",
    defaultModelsExpandDepth: 0,
    displayRequestDuration: true,
    filter: true,
    tryItOutEnabled: false,
    deepLinking: true,
    persistAuthorization: true,
  });
})();
</script>
</body>
</html>"""
    return html


@app.get("/api/docs", include_in_schema=False)
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return HTMLResponse(content=_build_docs_page())

@app.get("/")
@app.get("/index.html")
async def serve_frontend():
    return _frontend_html_response("index.html")


@app.get("/prices")
@app.get("/prices.html")
async def serve_prices():
    return _frontend_html_response("prices.html")


_PUBLIC_PAGES = ["about", "services", "contact", "faq", "blog", "404"]


def _make_page_route(page_name: str):
    async def _serve_public_page():
        return _frontend_html_response(f"{page_name}.html")

    return _serve_public_page


for _page in _PUBLIC_PAGES:
    _route = _make_page_route(_page)
    app.add_api_route(f"/{_page}", _route, include_in_schema=False)
    app.add_api_route(f"/{_page}.html", _route, include_in_schema=False)


_ADMIN_DIST = os.path.join(FRONTEND_DIR, "dashboardadmin", "dist")


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
async def serve_admin_index():
    """Serve the React admin SPA entry point."""
    from fastapi.responses import FileResponse
    index = os.path.join(_ADMIN_DIST, "index.html")
    if os.path.isfile(index):
        return FileResponse(index)
    return HTMLResponse(content="<h1>Admin introuvable</h1>", status_code=404)


@app.get("/admin/{full_path:path}", include_in_schema=False)
async def serve_admin(full_path: str = ""):
    from fastapi.responses import FileResponse
    # Serve static assets (JS/CSS/images) directly from dist
    candidate = os.path.normpath(os.path.join(_ADMIN_DIST, full_path))
    if full_path and candidate.startswith(_ADMIN_DIST) and os.path.isfile(candidate):
        return FileResponse(candidate)
    # All other paths → SPA index.html (React Router handles routing)
    index = os.path.join(_ADMIN_DIST, "index.html")
    if os.path.isfile(index):
        return FileResponse(index)
    return HTMLResponse(content="<h1>404 – Page admin introuvable</h1>", status_code=404)


@app.get("/sitemap.xml", include_in_schema=False)
async def serve_sitemap():
    from fastapi.responses import Response
    path = os.path.join(FRONTEND_DIR, "sitemap.xml")
    with open(path, encoding="utf-8") as f:
        return Response(content=f.read(), media_type="application/xml")


@app.get("/robots.txt", include_in_schema=False)
async def serve_robots():
    from fastapi.responses import PlainTextResponse
    path = os.path.join(FRONTEND_DIR, "robots.txt")
    with open(path, encoding="utf-8") as f:
        return PlainTextResponse(content=f.read())


def _monthly_quota_reset():
    """Reset quota_used to 0 on all API keys — runs on the 1st of each month."""
    from backend.database.session import SessionLocal
    from backend.database.models import ApiKey
    try:
        db = SessionLocal()
        updated = db.query(ApiKey).update({"quota_used": 0})
        db.commit()
        db.close()
        print(f"[Scheduler] Monthly quota reset: {updated} keys reset to 0.")
    except Exception as _e:
        print(f"[Scheduler] Quota reset failed: {_e}")


@app.on_event("startup")
async def startup_event():
    from backend.database.session import init_db
    init_db()

    # Lightweight SQLite migrations: add columns that may be missing
    try:
        from backend.database.session import engine
        from sqlalchemy import text
        with engine.connect() as _conn:
            _migrations = [
                # Existing migrations
                "ALTER TABLE api_keys ADD COLUMN last_four VARCHAR(8)",
                # New columns — added with migrations so existing DBs stay compatible
                "ALTER TABLE api_keys ADD COLUMN name VARCHAR(128)",
                "ALTER TABLE clients ADD COLUMN organization VARCHAR(255)",
                "ALTER TABLE clients ADD COLUMN stripe_customer_id VARCHAR(255)",
                # Audit log table (created by init_db if missing, migration for safety)
                (
                    "CREATE TABLE IF NOT EXISTS audit_logs ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "actor_type VARCHAR(32) NOT NULL, "
                    "actor_id INTEGER, "
                    "action VARCHAR(128) NOT NULL, "
                    "target_type VARCHAR(64), "
                    "target_id INTEGER, "
                    "details JSON, "
                    "ip_address VARCHAR(64), "
                    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL"
                    ")"
                ),
                (
                    "CREATE TABLE IF NOT EXISTS invoices ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "invoice_number VARCHAR(64) UNIQUE NOT NULL, "
                    "client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL, "
                    "client_name VARCHAR(255) NOT NULL, "
                    "client_email VARCHAR(255) NOT NULL, "
                    "issue_date DATE, "
                    "due_date DATE, "
                    "status VARCHAR(32) NOT NULL DEFAULT 'pending', "
                    "vat_rate FLOAT NOT NULL DEFAULT 20.0, "
                    "notes TEXT, "
                    "items JSON, "
                    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
                    "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                    ")"
                ),
                # Knowledge Base table
                (
                    "CREATE TABLE IF NOT EXISTS knowledge_bases ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "name VARCHAR(255) NOT NULL, "
                    "slug VARCHAR(64) UNIQUE, "
                    "language_name VARCHAR(128), "
                    "language_code VARCHAR(16), "
                    "country_or_region VARCHAR(128), "
                    "description TEXT, "
                    "root_path VARCHAR(512) NOT NULL, "
                    "is_legacy BOOLEAN DEFAULT 0, "
                    "status VARCHAR(32) DEFAULT 'detected', "
                    "version VARCHAR(64), "
                    "labels_file_path VARCHAR(512), "
                    "metadata_file_path VARCHAR(512), "
                    "total_files INTEGER, "
                    "total_images INTEGER, "
                    "total_videos INTEGER, "
                    "total_classes INTEGER, "
                    "total_size BIGINT, "
                    "scan_report JSON, "
                    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
                    "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
                    "last_scanned_at DATETIME, "
                    "created_by VARCHAR(128)"
                    ")"
                ),
                # Add knowledge_base_id to training_jobs
                "ALTER TABLE training_jobs ADD COLUMN knowledge_base_id INTEGER REFERENCES knowledge_bases(id)",
                "ALTER TABLE training_jobs ADD COLUMN progress FLOAT",
                "ALTER TABLE training_jobs ADD COLUMN metrics JSON",
                "ALTER TABLE training_jobs ADD COLUMN error_message TEXT",
                "ALTER TABLE training_jobs ADD COLUMN target_model_name VARCHAR(255)",
                "ALTER TABLE training_jobs ADD COLUMN target_model_version VARCHAR(64)",
                # training_jobs dataset_id: make nullable — SQLite requires table recreation
                # Add columns to sign_language_models
                "ALTER TABLE sign_language_models ADD COLUMN name VARCHAR(255)",
                "ALTER TABLE sign_language_models ADD COLUMN slug VARCHAR(64)",
                "ALTER TABLE sign_language_models ADD COLUMN is_published BOOLEAN DEFAULT 0",
                "ALTER TABLE sign_language_models ADD COLUMN published_at DATETIME",
                "ALTER TABLE sign_language_models ADD COLUMN knowledge_base_id INTEGER REFERENCES knowledge_bases(id)",
                "ALTER TABLE sign_language_models ADD COLUMN training_job_id INTEGER",
                "ALTER TABLE sign_language_models ADD COLUMN artifact_path VARCHAR(512)",
                # Admin auth tables (password reset flow)
                (
                    "CREATE TABLE IF NOT EXISTS admin_settings ("
                    "key TEXT PRIMARY KEY, "
                    "value TEXT NOT NULL"
                    ")"
                ),
                (
                    "CREATE TABLE IF NOT EXISTS admin_password_resets ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "token_hash TEXT NOT NULL UNIQUE, "
                    "used INTEGER NOT NULL DEFAULT 0, "
                    "created_at TEXT NOT NULL, "
                    "expires_at TEXT NOT NULL"
                    ")"
                ),
                # Feedback loop: client corrections to improve future training data
                (
                    "CREATE TABLE IF NOT EXISTS recognition_feedbacks ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL, "
                    "api_key_id INTEGER REFERENCES api_keys(id) ON DELETE SET NULL, "
                    "model_id INTEGER REFERENCES sign_language_models(id) ON DELETE SET NULL, "
                    "session_id VARCHAR(64), "
                    "predicted_label VARCHAR(128), "
                    "correct_label VARCHAR(128), "
                    "confidence FLOAT, "
                    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL"
                    ")"
                ),
                # Feature 1: Model visibility levels
                "ALTER TABLE sign_language_models ADD COLUMN visibility VARCHAR(32) DEFAULT 'public'",
                # Feature 3: Human review queue — review_status on feedback
                "ALTER TABLE recognition_feedbacks ADD COLUMN review_status VARCHAR(32) DEFAULT 'pending'",
                # Feature 1: Model access table for client_specific visibility
                (
                    "CREATE TABLE IF NOT EXISTS model_access ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "model_id INTEGER NOT NULL REFERENCES sign_language_models(id) ON DELETE CASCADE, "
                    "client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE, "
                    "granted_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL"
                    ")"
                ),
            ]
            for _col_sql in _migrations:
                try:
                    _conn.execute(text(_col_sql))
                    _conn.commit()
                except Exception:
                    pass  # column/table already exists

            # Make training_jobs.dataset_id nullable (SQLite requires table recreation)
            try:
                _ti = _conn.execute(text("PRAGMA table_info(training_jobs)")).fetchall()
                _ds_col = next((c for c in _ti if c[1] == "dataset_id"), None)
                if _ds_col and _ds_col[3]:  # notnull == 1
                    # Recreate table without NOT NULL on dataset_id
                    _conn.execute(text(
                        "CREATE TABLE IF NOT EXISTS training_jobs_new ("
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                        "model_id INTEGER REFERENCES sign_language_models(id) ON DELETE SET NULL, "
                        "dataset_id INTEGER REFERENCES datasets(id) ON DELETE RESTRICT, "
                        "knowledge_base_id INTEGER REFERENCES knowledge_bases(id) ON DELETE SET NULL, "
                        "language_code VARCHAR(16) NOT NULL, "
                        "status VARCHAR(32) NOT NULL DEFAULT 'queued', "
                        "celery_task_id VARCHAR(255), "
                        "params JSON, "
                        "progress FLOAT, "
                        "metrics JSON, "
                        "log_output TEXT, "
                        "error_message TEXT, "
                        "target_model_name VARCHAR(255), "
                        "target_model_version VARCHAR(64), "
                        "started_at DATETIME, "
                        "finished_at DATETIME, "
                        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL"
                        ")"
                    ))
                    _conn.execute(text(
                        "INSERT INTO training_jobs_new "
                        "(id, model_id, dataset_id, knowledge_base_id, language_code, status, "
                        "celery_task_id, params, progress, metrics, log_output, error_message, "
                        "target_model_name, target_model_version, started_at, finished_at, created_at) "
                        "SELECT id, model_id, dataset_id, knowledge_base_id, language_code, status, "
                        "celery_task_id, params, progress, metrics, log_output, error_message, "
                        "target_model_name, target_model_version, started_at, finished_at, created_at "
                        "FROM training_jobs"
                    ))
                    _conn.execute(text("DROP TABLE training_jobs"))
                    _conn.execute(text("ALTER TABLE training_jobs_new RENAME TO training_jobs"))
                    _conn.commit()
                    print("[DB] training_jobs.dataset_id migrated to nullable")
            except Exception as _ds_e:
                print(f"[DB] training_jobs dataset_id migration skipped: {_ds_e}")
    except Exception as _me:
        print(f"[DB] Migration check failed: {_me}")
    try:
        from backend.storage.s3_client import ensure_buckets
        ensure_buckets()
    except Exception as _e:
        print(f"[S3] Bucket init skipped (MinIO not available in dev mode): {_e}")
    # Auto-detect ASL Knowledge Base from data/knowledge/
    try:
        from backend.database.session import SessionLocal as _SL
        from backend.services.knowledge_scanner import sync_knowledge_bases as _sync_kb
        _db_kb = _SL()
        try:
            _created = _sync_kb(_db_kb)
            if _created:
                print(f"[KB] {len(_created)} knowledge base(s) détectée(s) automatiquement.")
        except Exception as _kb_e:
            print(f"[KB] Scan initial échoué (non bloquant): {_kb_e}")
        finally:
            _db_kb.close()
    except Exception as _kb_top:
        print(f"[KB] Initialisation knowledge scanner échouée: {_kb_top}")

    await ai_translator.prepare()
    if AI_PROVIDER == "cloud":
        print(f"[AI] Provider: cloud (Google Gemini, modèle {os.getenv('GEMINI_MODEL', 'gemini-3.1-flash-lite')})")
    else:
        print(f"[AI] Provider actif: {AI_PROVIDER}")
    print(f"[Signs] Texte→signe: {text_to_sign_service.vocabulary_stats()['with_video']} signes WLASL (base complète)")
    if API_KEYS_REQUIRED:
        print("[API] Clés API obligatoires (header X-API-Key) — admin: /admin")
    else:
        print("[API] Mode ouvert (API_KEYS_REQUIRED=false)")

    # Monthly quota auto-reset scheduler (1st of each month at 00:05 UTC)
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        _scheduler = AsyncIOScheduler()
        _scheduler.add_job(
            _monthly_quota_reset,
            trigger="cron",
            day=1,
            hour=0,
            minute=5,
            id="monthly_quota_reset",
            replace_existing=True,
        )
        _scheduler.start()
        print("[Scheduler] Monthly quota reset scheduled (1st of each month, 00:05 UTC).")
    except Exception as _e:
        print(f"[Scheduler] Could not start scheduler: {_e}")

# ──────────── PARAMÈTRES WEBSOCKET / PHRASE ────────────
STABLE_WORD_THRESHOLD = float(os.getenv("STABLE_WORD_THRESHOLD", "0.82"))
TOP2_MARGIN_THRESHOLD = float(os.getenv("TOP2_MARGIN_THRESHOLD", "0.12"))
BUFFER_SILENCE_SECONDS = float(os.getenv("BUFFER_SILENCE_SECONDS", "3.5"))
MIN_WORD_COOLDOWN_SECONDS = float(os.getenv("MIN_WORD_COOLDOWN_SECONDS", "1.0"))
WORD_SPEECH_COOLDOWN_SECONDS = float(os.getenv("WORD_SPEECH_COOLDOWN_SECONDS", "2.5"))
INSTANT_SPEAK_CONFIDENCE = float(os.getenv("INSTANT_SPEAK_CONFIDENCE", "0.55"))


async def send_word_speech(websocket, asl_label, lang, confidence=0.0):
    """Synthèse vocale immédiate d'un mot ASL dans la langue de sortie."""
    trans = find_translation(asl_label, lang=lang)
    spoken = speech_text_for_label(asl_label, lang, trans["text"])
    if not spoken:
        return

    voice = TTS_VOICES.get(lang, TTS_VOICES["fr"])
    audio_b64 = await tts.generate_audio_b64(spoken, voice=voice)
    if not audio_b64:
        return

    await websocket.send_json({
        "label": asl_label,
        "translation": trans["text"],
        "spoken_text": spoken,
        "audio_b64": audio_b64,
        "speech_kind": "word",
        "lang": lang,
        "confidence": confidence,
    })


def try_queue_word_speech(websocket, asl_label, lang, confidence, last_spoken_at):
    """Lance TTS mot en arrière-plan si le cooldown est respecté."""
    now = time.time()
    if now - last_spoken_at < WORD_SPEECH_COOLDOWN_SECONDS:
        return last_spoken_at, False

    async def _run():
        try:
            await send_word_speech(websocket, asl_label, lang, confidence)
        except Exception as exc:
            print(f"[TTS] Erreur voix mot: {exc}")

    asyncio.create_task(_run())
    return now, True


@app.websocket("/ws/video")
async def websocket_endpoint(websocket: WebSocket):
    # API key is read from Sec-WebSocket-Protocol to keep it out of URLs and logs.
    # Client: new WebSocket(url, ["mira-api", apiKey])
    protocol_header = websocket.headers.get("sec-websocket-protocol", "")
    parts = [p.strip() for p in protocol_header.split(",") if p.strip()]
    api_key = parts[1] if len(parts) > 1 else ""
    await websocket.accept(subprotocol="mira-api")
    if API_KEYS_REQUIRED:
        _ws_auth_ok = bool(api_access_store.find_by_api_key(api_key))
        if not _ws_auth_ok:
            # Fallback: check SaaS API key store in the database
            try:
                from backend.database.session import SessionLocal as _SL
                from backend.auth.api_key import verify_api_key as _verify, key_prefix_from_full as _kpfull
                from backend.database.models import ApiKey as _ApiKey
                _db = _SL()
                try:
                    _prefix = _kpfull(api_key)
                    _candidates = (
                        _db.query(_ApiKey)
                        .filter(_ApiKey.key_prefix == _prefix, _ApiKey.is_active.is_(True))
                        .all()
                    )
                    for _cand in _candidates:
                        if _verify(api_key, _cand.key_hash):
                            _ws_auth_ok = True
                            break
                finally:
                    _db.close()
            except Exception as _ws_e:
                print(f"[WS] SaaS key lookup failed: {_ws_e}")
        if not _ws_auth_ok:
            await websocket.close(code=4403)
            return
    print("[WS] Nouvelle connexion WebSocket.")

    ws_session_id = str(uuid.uuid4())
    sentence_buffer = []
    last_word_time = time.time()
    last_added_time = 0.0
    last_added_word = ""
    last_spoken_word = ""
    last_spoken_at = 0.0
    output_lang = "fr"
    current_mode = "holistic"
    spell_buffer = FingerspellBuffer()

    try:
        while True:
            data_str = await websocket.receive_text()
            data = json.loads(data_str)

            output_lang = normalize_lang(data.get("lang", output_lang))
            mode = data.get("mode", "holistic")
            if mode != current_mode:
                current_mode = mode
                ws_session_id = str(uuid.uuid4())
                spell_buffer.reset()
                last_added_word = ""
                last_spoken_word = ""

            frame = decode_image_b64(data.get("image", ""))
            if frame is None:
                continue

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: predict_frame(
                    frame,
                    lang=output_lang,
                    mode=mode,
                    session_id=ws_session_id,
                ),
            )

            stable_label = result.get("label") or ""
            basic_text = result.get("translation") or ""
            confidence = result.get("confidence", 0.0)
            top2_margin = result.get("margin", 0.0)
            is_stable = result.get("stable", False)
            virtual_hello = stable_label == "hello" and confidence >= 0.88
            now = time.time()

            if mode == "hands" and result.get("label") and len(str(result["label"])) == 1:
                spelled = spell_buffer.push(result["label"], now)
                if spelled == "hello":
                    stable_label = "hello"
                    is_stable = True
                    basic_text = find_translation("hello", output_lang)["text"]

            if (
                is_stable
                and stable_label
                and stable_label != last_added_word
                and confidence >= STABLE_WORD_THRESHOLD
                and top2_margin >= TOP2_MARGIN_THRESHOLD
                and (now - last_added_time) >= MIN_WORD_COOLDOWN_SECONDS
                and stable_label.lower() not in ("space", "del", "nothing")
            ):
                sentence_buffer.append(stable_label)
                last_added_word = stable_label
                last_word_time = now
                last_added_time = now

            speak_label = ""
            if virtual_hello and stable_label == "hello" and last_spoken_word != "hello":
                speak_label = "hello"
            elif (
                is_stable
                and stable_label
                and should_speak_instantly(stable_label)
                and stable_label != last_spoken_word
                and confidence >= INSTANT_SPEAK_CONFIDENCE
            ):
                speak_label = stable_label

            if speak_label:
                last_spoken_at, did_speak = try_queue_word_speech(
                    websocket, speak_label, output_lang, confidence, last_spoken_at
                )
                if did_speak:
                    last_spoken_word = speak_label

            if sentence_buffer and (time.time() - last_word_time > BUFFER_SILENCE_SECONDS):
                full_raw_sequence = " ".join(sentence_buffer)
                sentence_buffer.clear()
                last_added_word = ""

                async def generate_and_send_sentence(raw_sequence, lang=output_lang):
                    try:
                        final_sentence = await ai_translator.translate_asl(raw_sequence, lang=lang)
                        voice = TTS_VOICES.get(lang, TTS_VOICES["fr"])
                        audio_b64 = await tts.generate_audio_b64(final_sentence, voice=voice)
                        await websocket.send_json({
                            "sentence": final_sentence,
                            "audio_b64": audio_b64,
                            "lang": lang,
                        })
                    except Exception as e:
                        print(f"[ERR] Phrase IA: {e}")

                asyncio.create_task(generate_and_send_sentence(full_raw_sequence))

            preview_label = result.get("preview_label") or ""
            preview_text = result.get("preview_translation") or ""
            display_label = stable_label if is_stable else preview_label
            display_text = basic_text if is_stable else preview_text

            payload = {
                "buffer_text": " ".join(sentence_buffer),
                "lang": output_lang,
                "image": result.get("image"),
                "session_id": result.get("session_id"),
                "preview_label": preview_label or None,
                "preview_translation": preview_text or None,
                "confidence": confidence,
                "margin": top2_margin,
                "stable": is_stable,
                "sequence_len": result.get("sequence_len"),
                "sequence_required": result.get("sequence_required"),
            }
            if display_label:
                payload["label"] = display_label
                payload["translation"] = display_text
                payload["fr"] = display_text
                payload["virtual_hello"] = virtual_hello
            await websocket.send_json(payload)

    except WebSocketDisconnect:
        print("[WS] Client déconnecté.")
    except Exception as e:
        import traceback
        print(f"[ERR] Erreur Backend: {e}")
        traceback.print_exc()
