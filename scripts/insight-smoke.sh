#!/usr/bin/env bash
# Browser smoke test for Insight: scaffold the sample project, serve it with
# `tuvl dev --auto-login`, and run the Playwright suite in ui/e2e against it.
# Needs a reachable Postgres (POSTGRES_* env) and a built UI (pnpm build:cli).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${TUVL_SMOKE_PORT:-8890}"
TUVL="${TUVL:-tuvl}"
WORK="$(mktemp -d)"
trap 'kill "${SERVER:-0}" 2>/dev/null || true; pkill -f "port ${PORT}" 2>/dev/null || true; rm -rf "$WORK"' EXIT

(cd "$WORK" && "$TUVL" init demo --sample --preset ollama -y >/dev/null)
# an idea, a numbered spec and their audit trail, for the Ideas / Audit / Specs pages
printf '# Smoke brief\n\nA short idea about tickets.\n' > "$WORK/brief.md"
# a collection, for the steps that search or store documents
cat > "$WORK/demo/models/collections.yaml" <<'YAML'
kind: CollectionRegistry
version: v1
metadata: { name: collections }
spec:
  collections:
    - { name: kb, description: Support articles }
YAML
(cd "$WORK/demo" && "$TUVL" import idea "$WORK/brief.md" --initials SM >/dev/null \
  && "$TUVL" create spec smoke --idea IDEA-SM-0001 >/dev/null \
  && "$TUVL" approve spec SPEC-SM-0001-01 --force >/dev/null \
  && "$TUVL" generate tasks SPEC-SM-0001-01 >/dev/null)
(cd "$WORK/demo" && "$TUVL" dev --project-dir . --port "$PORT" --auto-login --no-browser >"$WORK/dev.log" 2>&1) &
SERVER=$!

for _ in $(seq 1 60); do
  curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null || { cat "$WORK/dev.log"; exit 1; }

cd "$ROOT/ui"
TUVL_SMOKE_URL="http://127.0.0.1:${PORT}" pnpm exec playwright test "$@" || { tail -50 "$WORK/dev.log"; exit 1; }
