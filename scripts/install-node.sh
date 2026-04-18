#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"

if [ -f pnpm-lock.yaml ]; then
  printf '%s\n' "[install-node] Using frozen lockfile install"
  exec env CI=true pnpm install --frozen-lockfile
fi

printf '%s\n' "[install-node] No pnpm-lock.yaml yet, running initial install to create lockfile"
exec env CI=true pnpm install
