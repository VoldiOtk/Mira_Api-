#!/bin/bash
set -e

echo "=== Mira AI — Production Deployment ==="

# Check docker
if ! command -v docker &>/dev/null; then
  echo "[deploy] ERROR: Docker not found. Please install Docker Desktop."
  exit 1
fi

# Support both 'docker compose' (v2 plugin) and 'docker-compose' (v1 standalone)
if docker compose version &>/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose &>/dev/null; then
  COMPOSE="docker-compose"
else
  echo "[deploy] ERROR: Neither 'docker compose' nor 'docker-compose' found."
  exit 1
fi

echo "[deploy] Using: $COMPOSE"

# Generate .env if missing
if [ ! -f .env ]; then
  if [ ! -f .env.example ]; then
    echo "[deploy] ERROR: .env.example not found. Cannot generate .env."
    exit 1
  fi
  echo "[deploy] Generating .env from .env.example..."
  cp .env.example .env

  # Auto-generate secrets
  JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))" 2>/dev/null || openssl rand -hex 32)
  API_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))" 2>/dev/null || openssl rand -hex 32)

  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s|JWT_SECRET_KEY=change-me-in-production-use-openssl-rand-hex-32|JWT_SECRET_KEY=${JWT_SECRET}|" .env
    sed -i '' "s|API_KEY_SECRET=change-me-use-openssl-rand-hex-32|API_KEY_SECRET=${API_SECRET}|" .env
  else
    sed -i "s|JWT_SECRET_KEY=change-me-in-production-use-openssl-rand-hex-32|JWT_SECRET_KEY=${JWT_SECRET}|" .env
    sed -i "s|API_KEY_SECRET=change-me-use-openssl-rand-hex-32|API_KEY_SECRET=${API_SECRET}|" .env
  fi

  echo "[deploy] .env created with auto-generated secrets."
  echo "[deploy] IMPORTANT: Edit .env to set MIRA_ADMIN_PASSWORD and GEMINI_API_KEY before running in production."
else
  echo "[deploy] .env already exists, skipping generation."
fi

# Build images in parallel
echo "[deploy] Building Docker images (parallel)..."
$COMPOSE build --parallel

# Start infrastructure services first
echo "[deploy] Starting infrastructure (postgres, redis, minio)..."
$COMPOSE up -d postgres redis minio

echo "[deploy] Waiting 10s for infrastructure to initialize..."
sleep 10

# Start the full stack (minio-init, api, worker, prometheus, grafana)
echo "[deploy] Starting full stack..."
$COMPOSE up -d

echo ""
echo "=== Deployment complete ==="
echo ""
echo "  API:        http://localhost:8000"
echo "  API Docs:   http://localhost:8000/docs"
echo "  Admin UI:   http://localhost:8000/admin-dashboard"
echo "  MinIO:      http://localhost:9001  (minioadmin / minioadmin123)"
echo "  Prometheus: http://localhost:9090"
echo "  Grafana:    http://localhost:3000  (admin / admin)"
echo ""
echo "  Check logs: $COMPOSE logs -f api"
echo "  Run tests:  $COMPOSE exec api python -m pytest tests/ -v"
echo "  Stop stack: $COMPOSE down"
echo ""
