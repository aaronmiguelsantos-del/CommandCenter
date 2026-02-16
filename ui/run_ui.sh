#!/usr/bin/env bash
set -euo pipefail

# Run from repo root no matter where invoked from
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -d ".venv" ]]; then
  echo "ERROR: .venv not found. Create your repo venv first."
  exit 1
fi

source .venv/bin/activate

python -c "import streamlit" >/dev/null 2>&1 || {
  echo "Installing UI deps..."
  pip install -r ui/requirements-ui.txt
}

exec streamlit run ui/app.py
