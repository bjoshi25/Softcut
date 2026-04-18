#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"

printf '%s\n' "[run-analysis-config] Step 1/2: Ensuring Python environment"
sh scripts/ensure-python-env.sh
printf '%s\n' "[run-analysis-config] Step 2/2: Running config-driven analysis"
exec "$repo_root/.venv/bin/python" -m engine.analysis.run_from_config "$@"
