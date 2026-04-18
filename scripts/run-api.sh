#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"

sh scripts/ensure-python-env.sh
exec "$repo_root/.venv/bin/python" -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload
