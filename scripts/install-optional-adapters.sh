#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"

printf '%s\n' "[install-adapters] Step 1/3: Ensuring Python environment"
if [ ! -x "$repo_root/.venv/bin/python" ]; then
  python_bin_fallback=${SOFTCUT_PYTHON_BIN:-python3}
  "$python_bin_fallback" -m venv "$repo_root/.venv"
fi

pip_bin="$repo_root/.venv/bin/pip"
python_bin="$repo_root/.venv/bin/python"
"$python_bin" -m pip install --upgrade pip setuptools wheel

tf_package_default="tensorflow>=2.16,<2.18"
if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  tf_package_default="tensorflow-macos>=2.16,<2.18"
fi
tf_package=${SOFTCUT_TF_PACKAGE:-$tf_package_default}
opennsfw2_package=${SOFTCUT_OPENNSFW2_PACKAGE:-opennsfw2>=0.10,<1}
transnet_package=${SOFTCUT_TRANSNETV2_PACKAGE:-transnetv2-pytorch>=1.0.5,<2}

printf '%s\n' "[install-adapters] Step 2/3: Installing adapter dependencies"
"$pip_bin" install "$opennsfw2_package"
"$pip_bin" install "$tf_package"
"$pip_bin" install "$transnet_package"

printf '%s\n' "[install-adapters] Step 3/3: Verifying imports"
"$python_bin" - <<'PY'
modules = ("opennsfw2", "transnetv2", "transnetv2_pytorch")
available = {}
for module_name in modules:
    try:
        module = __import__(module_name)
        version = getattr(module, "__version__", None)
        print(f"{module_name}: available" + (f" ({version})" if version else ""))
        available[module_name] = True
    except Exception as exc:
        print(f"{module_name}: unavailable ({exc})")
        available[module_name] = False

if not available.get("opennsfw2", False):
    raise SystemExit(1)
if not (available.get("transnetv2", False) or available.get("transnetv2_pytorch", False)):
    raise SystemExit(1)
PY

printf '%s\n' "[install-adapters] Done."
