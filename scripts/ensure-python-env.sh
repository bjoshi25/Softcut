#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"

venv_dir=${SOFTCUT_VENV_DIR:-.venv}
fingerprint_file="$venv_dir/.deps_fingerprint"

resolve_python_bin() {
  if [ -n "${SOFTCUT_PYTHON_BIN:-}" ]; then
    if [ ! -x "${SOFTCUT_PYTHON_BIN}" ]; then
      printf '%s\n' "[ensure-python-env] SOFTCUT_PYTHON_BIN is not executable: ${SOFTCUT_PYTHON_BIN}" >&2
      exit 1
    fi
    if ! "${SOFTCUT_PYTHON_BIN}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      printf '%s\n' "[ensure-python-env] SOFTCUT_PYTHON_BIN must be Python >= 3.10: ${SOFTCUT_PYTHON_BIN}" >&2
      exit 1
    fi
    printf '%s\n' "${SOFTCUT_PYTHON_BIN}"
    return
  fi

  # Prefer ML-friendly versions first for torch/whisperx compatibility.
  for candidate in python3.11 python3.10 python3.12 python3.13 python3.14 python3; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      command -v "$candidate"
      return
    fi
  done

  printf '%s\n' "[ensure-python-env] Could not find Python >= 3.10. Set SOFTCUT_PYTHON_BIN explicitly." >&2
  exit 1
}

python_bin=$(resolve_python_bin)
python_version=$("$python_bin" --version 2>&1 || true)
printf '%s\n' "[ensure-python-env] Using $python_bin ($python_version)"

if [ -d "$venv_dir" ]; then
  selected_minor=$("$python_bin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  venv_minor=$("$venv_dir/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
  if [ -n "$venv_minor" ] && [ "$selected_minor" != "$venv_minor" ]; then
    printf '%s\n' "[ensure-python-env] Recreating $venv_dir (Python $venv_minor -> $selected_minor)"
    rm -rf "$venv_dir"
  fi
fi

if [ ! -d "$venv_dir" ]; then
  "$python_bin" -m venv "$venv_dir"
fi

current_fingerprint=$(cksum pyproject.toml | awk '{print $1 ":" $2}')
install_target="."
install_extras=${SOFTCUT_INSTALL_EXTRAS:-analysis-ml,ingest}
if [ -n "$install_extras" ]; then
  install_target=".[${install_extras}]"
fi

desired_state="$current_fingerprint|$install_target"
saved_fingerprint=""
if [ -f "$fingerprint_file" ]; then
  saved_fingerprint=$(cat "$fingerprint_file")
fi

if [ "$desired_state" != "$saved_fingerprint" ]; then
  "$venv_dir/bin/python" -m pip install --upgrade pip setuptools wheel
  "$venv_dir/bin/python" -m pip install --no-build-isolation -e "$install_target"
  printf '%s\n' "$desired_state" > "$fingerprint_file"
fi
