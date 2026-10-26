#!/usr/bin/env bash
# PostToolUse(Edit|Write): format ONLY the file the agent just edited.
# Never touches any other file — including your own uncommitted work.
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
[ -d .venv/bin ] && PATH="$PWD/.venv/bin:$PATH"
command -v ruff >/dev/null 2>&1 || exit 0

# Claude Code passes the tool call as JSON on stdin; pull out the edited path.
file=$(python3 -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))' 2>/dev/null)

case "$file" in
  *.py)
    ruff format "$file" >/dev/null 2>&1
    # F401 stays unfixed: auto-removing an import added before its first use deletes
    # it mid-edit. gate.sh still fails the turn on unused imports.
    ruff check --fix --unfixable F401 "$file" >/dev/null 2>&1
    ;;
esac
exit 0
