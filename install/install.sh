#!/bin/sh
# Bootstrap installer for the finance CLI (macOS / Linux).
# Read this script before running it. It installs uv (if missing), installs the
# finance tool, then starts guided setup. Nothing here contacts your bank; that
# happens inside `finance setup`, which you control.
set -eu

REPO="${FINANCE_REPO:-https://github.com/gupta-surya/agentic-personal-finance.git}"

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv (https://astral.sh/uv) ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "Installing the finance tool ..."
uv tool install "git+${REPO}"

echo "Starting guided setup ..."
finance setup
