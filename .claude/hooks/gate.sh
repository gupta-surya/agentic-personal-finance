#!/usr/bin/env bash
# Stop hook: the quality gate at the end of every agent turn.
# ruff + mypy + pytest must pass. On failure, print the problems to stderr and
# exit 2, which sends Claude back to keep working instead of finishing on red.
#
# Lint and types run on every Python file git would let you commit: tracked
# files plus untracked ones that aren't gitignored. New agent files are checked;
# anything in the gitignored scratch/ folder is never touched or blocking.
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
[ -d .venv/bin ] && PATH="$PWD/.venv/bin:$PATH"

problems=""

pyfiles() { git ls-files -z --cached --others --exclude-standard -- '*.py'; }

if command -v ruff >/dev/null 2>&1; then
  if ! out=$(pyfiles | xargs -0 ruff check 2>&1); then
    problems+="--- ruff ---"$'\n'"$out"$'\n\n'
  fi
fi

if command -v mypy >/dev/null 2>&1; then
  if ! out=$(pyfiles | xargs -0 mypy 2>&1); then
    problems+="--- mypy ---"$'\n'"$out"$'\n\n'
  fi
fi

if command -v pytest >/dev/null 2>&1; then
  out=$(pytest -q 2>&1)
  code=$?
  # pytest exit 5 = "no tests collected" — treat as pass.
  if [ "$code" -ne 0 ] && [ "$code" -ne 5 ]; then
    problems+="--- pytest ---"$'\n'"$out"$'\n\n'
  fi
fi

if [ -n "$problems" ]; then
  printf 'Quality gate failed — fix these before finishing:\n\n%s' "$problems" >&2
  exit 2
fi
exit 0
