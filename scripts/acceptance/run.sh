#!/usr/bin/env bash
# P3 exit criterion (implementation plan P3.9): a coding agent given only a spec,
# the tuvl skills and `tuvl serve mcp` builds a fresh project until
# `tuvl list tasks --strict` is green. Records the transcript and the CI gate.
#
#   scripts/acceptance/run.sh <spec.md> [out-dir]
#
# Needs: the `claude` CLI, GEMINI_API_KEY (analysis + agent models), this
# checkout's virtualenv (the agent uses this tuvl, not the PyPI release).
set -euo pipefail

SPEC="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
NAME="$(basename "$SPEC" .md)"
OUT="${2:-$(mktemp -d -t tuvl-acceptance)}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
: "${GEMINI_API_KEY:?set GEMINI_API_KEY}"
: "${ACCEPTANCE_TIMEOUT:=5400}"             # seconds of wall clock for the agent

export PATH="$REPO/.venv/bin:$PATH"           # `tuvl` = this checkout
mkdir -p "$OUT" && cd "$OUT"
tuvl init project --preset gemini -y > init.log 2>&1
cd project
mkdir -p specs && cp "$SPEC" "specs/$NAME.md"
cat > .mcp.json <<JSON
{ "mcpServers": { "tuvl": { "command": "$REPO/.venv/bin/tuvl", "args": ["mcp", "--allow-write", "-d", "$PWD"] } } }
JSON

PROMPT="Build the tuvl project described in specs/$NAME.md, in this directory.
Follow AGENTS.md and the skills in .agents/skills (start with tuvl-task-loop; use tuvl-plan to analyse the spec).
Use the tuvl MCP tools or \`tuvl ... --json\` to read the project state; never guess it.
You are done when \`tuvl list tasks --strict\` exits 0. Do not edit generated files or task statuses.
The analysis model and agent models are configured (llms/); GEMINI_API_KEY is set."

started=$(date +%s)
budget=()
[ -n "${MAX_BUDGET_USD:-}" ] && budget=(--max-budget-usd "$MAX_BUDGET_USD")
perl -e 'alarm shift; exec @ARGV' "$ACCEPTANCE_TIMEOUT" \
  claude -p "$PROMPT" --mcp-config .mcp.json --strict-mcp-config --permission-mode bypassPermissions \
  "${budget[@]}" --output-format stream-json --verbose > ../transcript.jsonl 2> ../claude.err || true
elapsed=$(( $(date +%s) - started ))

{
  echo "spec: $NAME  elapsed: ${elapsed}s"
  for cmd in "lint project --strict" "generate code --check" "verify lock" "run tests" "list tasks --strict"; do
    if tuvl $cmd > /dev/null 2>&1; then echo "PASS tuvl $cmd"; else echo "FAIL tuvl $cmd"; fi
  done
  tuvl list tasks --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print('tasks:', [(t['id'], t['status']) for p in d['plans'] for t in p['tasks'] if not t['obsolete']])" || true
} | tee ../result.txt
grep -q "FAIL" ../result.txt && exit 1 || exit 0
