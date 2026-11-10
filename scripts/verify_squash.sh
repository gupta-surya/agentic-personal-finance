#!/usr/bin/env bash
# Prove the squashed baseline reproduces the pre-squash migration chain exactly.
#
# Applies the old chain (from a git ref) and the new baseline (working tree) to two
# throwaway *_test databases, dumps each schema with pg_dump, and diffs them. Empty diff
# => byte-identical schema. Run from anywhere in the repo, with Docker available.
#
#   scripts/verify_squash.sh [BEFORE_REF]   # BEFORE_REF defaults to the commit before HEAD
set -euo pipefail
exec </dev/null   # never read the terminal's input buffer (so a pasted
                  # follow-up command can't be swallowed by docker compose exec)

BEFORE="${1:-HEAD~1}"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
PY="${PYTHON:-.venv/bin/python}"
DSN_BASE="postgresql://finance:finance@127.0.0.1:5432"

docker compose up -d db >/dev/null
echo "waiting for Postgres ..."
until docker compose exec -T db pg_isready -U finance >/dev/null 2>&1; do sleep 1; done

apply_and_dump() {  # $1 = src dir to import finance_agent from, $2 = db name
  docker compose exec -T db psql -U finance -d postgres -q \
    -c "DROP DATABASE IF EXISTS $2" -c "CREATE DATABASE $2" >/dev/null
  PYTHONPATH="$1" "$PY" - "$1" "$DSN_BASE/$2" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[1])
import psycopg
from finance_agent.db.loader import apply_schema
conn = psycopg.connect(sys.argv[2])
apply_schema(conn)
conn.commit()
PYEOF
  # Strip pg_dump's volatile lines: the random \restrict/\unrestrict nonces (new in
  # pg16+, different every run) and the version banner.
  docker compose exec -T db pg_dump -U finance --schema-only --no-owner --no-privileges "$2" \
    | grep -vE '^(\\(un)?restrict |-- Dumped )'
}

WT="$(mktemp -d)"
git worktree add -f "$WT" "$BEFORE" >/dev/null 2>&1
trap 'git worktree remove --force "$WT" >/dev/null 2>&1 || true' EXIT

echo "old chain  ($BEFORE) -> squash_old_test"
apply_and_dump "$WT/src" squash_old_test > /tmp/squash_old.sql
echo "new baseline (HEAD) -> squash_new_test"
apply_and_dump "$ROOT/src" squash_new_test > /tmp/squash_new.sql

echo
if diff -u /tmp/squash_old.sql /tmp/squash_new.sql; then
  echo "SCHEMA IDENTICAL ✓  (old chain == squashed baseline)"
else
  echo "SCHEMA DIFFERS ✗  (see the diff above; the baseline needs a fix)"
  exit 1
fi
