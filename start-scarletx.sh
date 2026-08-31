#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

python_ok() {
  local candidate="$1"
  [[ -n "$candidate" ]] || return 1
  command -v "$candidate" >/dev/null 2>&1 || [[ -x "$candidate" ]] || return 1
  "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
}

find_python() {
  local candidates=()
  [[ -n "${PYTHON:-}" ]] && candidates+=("$PYTHON")
  if command -v brew >/dev/null 2>&1; then
    for formula in python@3.13 python@3.12 python@3.11 python; do
      local prefix
      prefix="$(brew --prefix "$formula" 2>/dev/null || true)"
      [[ -n "$prefix" ]] && candidates+=("$prefix/bin/python3.13" "$prefix/bin/python3.12" "$prefix/bin/python3.11" "$prefix/bin/python3")
    done
  fi
  candidates+=(python3.13 python3.12 python3.11 python3)
  local candidate
  for candidate in "${candidates[@]}"; do
    if python_ok "$candidate"; then
      command -v "$candidate" 2>/dev/null || printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [[ -z "$PYTHON_BIN" && "$(uname -s)" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
  echo "Installing Python 3.12 for ScarletX..."
  brew install python@3.12
  PYTHON_BIN="$(find_python || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ScarletX requires Python 3.11 or newer." >&2
  echo "On macOS with Homebrew: brew install python@3.12" >&2
  exit 1
fi

mkdir -p data backups downloads/incomplete downloads/complete downloads/failed /tmp

# Local macOS convenience install. The application itself never invokes a package
# manager; system tools belong to the launcher on macOS and to the Docker image on Linux.
if [[ "$(uname -s)" == "Darwin" && "${SCARLETX_SKIP_TOOL_INSTALL:-0}" != "1" ]]; then
  if command -v brew >/dev/null 2>&1; then
    if ! command -v par2 >/dev/null 2>&1 && ! command -v par2repair >/dev/null 2>&1; then
      echo "Installing PAR2 support..."
      brew install par2
    fi
    if ! command -v 7z >/dev/null 2>&1 && ! command -v 7zz >/dev/null 2>&1; then
      echo "Installing 7-Zip support..."
      brew install sevenzip
    fi
    if ! command -v unrar >/dev/null 2>&1; then
      echo "Installing UnRAR support..."
      brew install --cask rar >/dev/null 2>&1 || brew install unar >/dev/null 2>&1 || true
    fi
    if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
      echo "Installing FFmpeg media-library support..."
      brew install ffmpeg
    fi
  else
    echo "Homebrew was not found. ScarletX can still start, but PAR2/UnRAR/7-Zip/FFmpeg tools were not auto-installed." >&2
  fi
fi

if [[ ! -f data/scarletx.db && -f data/scenecore.db ]]; then
  cp -p data/scenecore.db data/scarletx.db
  echo "Copied data/scenecore.db to data/scarletx.db for migration; original preserved."
fi

# A venv can become stale when a Homebrew Python is upgraded or a folder is copied.
# Validate the interpreter link and recreate automatically instead of failing on
# .venv/bin/python3.x not found.
if [[ -e .venv && ! -x .venv/bin/python ]]; then
  echo "Recreating stale ScarletX virtual environment..."
  rm -rf .venv
fi
if [[ -x .venv/bin/python ]]; then
  if ! .venv/bin/python - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
  then
    echo "Recreating ScarletX virtual environment for current Python..."
    rm -rf .venv
  fi
fi
if [[ ! -x .venv/bin/python ]]; then
  "$PYTHON_BIN" -m venv .venv
fi
. .venv/bin/activate

if ! python - <<'PYDEPS' >/dev/null 2>&1
import fastapi, httpx, sqlalchemy, uvicorn, PIL, watchdog, orjson
PYDEPS
then
  echo "Installing ScarletX Python dependencies..."
  python -m pip install --disable-pip-version-check -r requirements.txt
fi

# SABCTools is an optional SIMD yEnc/positional-I/O accelerator. Keep startup
# functional even on a platform where a compatible wheel/toolchain is unavailable.
if [[ "${SCARLETX_SKIP_ACCEL_INSTALL:-0}" != "1" ]] && ! python -c 'import sabctools' >/dev/null 2>&1; then
  echo "Installing optional ScarletX SIMD download acceleration..."
  if ! python -m pip install --disable-pip-version-check -r requirements-performance.txt; then
    echo "SABCTools acceleration unavailable; ScarletX will use its built-in yEnc decoder." >&2
  fi
fi

export SCARLETX_DATABASE_URL="${SCARLETX_DATABASE_URL:-sqlite:///$APP_DIR/data/scarletx.db}"
export SCARLETX_GENERATED_DIR="${SCARLETX_GENERATED_DIR:-$APP_DIR/data/generated}"
export SCARLETX_CACHE_DIR="${SCARLETX_CACHE_DIR:-$APP_DIR/data/cache}"
# Requested dev default scene root. Override SCARLETX_DEFAULT_MEDIA_ROOT for a real library.
export SCARLETX_DEFAULT_MEDIA_ROOT="${SCARLETX_DEFAULT_MEDIA_ROOT:-/tmp}"
export PYTHONUNBUFFERED=1
HOST="${SCARLETX_HOST:-127.0.0.1}"

if [[ -n "${SCARLETX_PORT:-}" ]]; then
  PORT="$SCARLETX_PORT"
else
  PORT="$(python - <<'PYPORT'
import socket
for port in range(8690, 8700):
    s=socket.socket()
    try:
        s.bind(('127.0.0.1', port))
    except OSError:
        s.close(); continue
    s.close(); print(port); break
else:
    raise SystemExit('No free ScarletX port found in 8690-8699')
PYPORT
)"
fi

URL="http://$HOST:$PORT"
echo ""
echo "ScarletX 0.3.7"
echo "Root folder: ${SCARLETX_DEFAULT_MEDIA_ROOT}"
echo "Opening: $URL"
echo "Press Ctrl+C to stop ScarletX."
echo ""

if [[ "${SCARLETX_NO_BROWSER:-0}" != "1" ]]; then
  (
    for _ in $(seq 1 120); do
      HEALTH="$(curl -fsS "$URL/api/health" 2>/dev/null || true)"
      if printf '%s' "$HEALTH" | grep -q '"app":"ScarletX"' && printf '%s' "$HEALTH" | grep -q '"version":"0.3.7"'; then
        if command -v open >/dev/null 2>&1; then
          open "$URL" >/dev/null 2>&1 || true
        elif command -v xdg-open >/dev/null 2>&1; then
          xdg-open "$URL" >/dev/null 2>&1 || true
        fi
        exit 0
      fi
      sleep 0.5
    done
  ) &
fi

exec python -m uvicorn scarletx.main:app --host "$HOST" --port "$PORT"
