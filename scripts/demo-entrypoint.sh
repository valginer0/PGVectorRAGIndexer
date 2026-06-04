#!/bin/bash
# =============================================================================
# Demo entrypoint — seeds the database if empty, then starts the API server.
# Used by docker-compose.demo.yml.
# =============================================================================

set -e

echo "🔍 Demo entrypoint: checking if database needs seeding..."

# Wait briefly for DB to be fully ready (healthcheck passed, but migrations may lag)
sleep 2

# Run seed script (idempotent — skips already-seeded documents)
python scripts/seed_demo.py || echo "⚠️  Seeding failed (DB may not have tables yet — run migrations first)"

echo "🚀 Starting API server..."
exec uvicorn api:app --host 0.0.0.0 --port 10000
