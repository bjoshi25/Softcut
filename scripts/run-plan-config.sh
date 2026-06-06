#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"

printf '%s\n' "[run-plan-config] Step 1/2: Ensuring Python environment"
sh scripts/ensure-python-env.sh
printf '%s\n' "[run-plan-config] Step 2/2: Running config-driven planner"
exec "$repo_root/.venv/bin/python" -m engine.planning.run_from_config "$@"
