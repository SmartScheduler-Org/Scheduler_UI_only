#!/bin/bash
set -e

# Use this script as the container entrypoint or startup command.
# It installs requirements (optional for local dev), runs migrations,
# collects static files, and starts Django.

echo "[entrypoint] Starting entrypointscript.sh"

# Resolve app directory:
# - use /app inside containers
# - use script directory when run locally (e.g., Git Bash on Windows)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd)"
if [ -f /app/projttgs/manage.py ]; then
  APP_DIR="/app"
  DEFAULT_HOST="0.0.0.0"
  DEFAULT_ENV="production"
  DEFAULT_INSTALL_DEPS="false"
else
  APP_DIR="$SCRIPT_DIR"
  DEFAULT_HOST="127.0.0.1"
  DEFAULT_ENV="development"
  DEFAULT_INSTALL_DEPS="true"
fi

to_python_path() {
  # Convert POSIX path to Windows path when running under Git Bash/MSYS.
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$1"
  else
    printf '%s\n' "$1"
  fi
}

REQ_FILE="$(to_python_path "$APP_DIR/requirements.txt")"
MANAGE_PY="$(to_python_path "$APP_DIR/projttgs/manage.py")"
HOST="${HOST:-$DEFAULT_HOST}"
PORT="${PORT:-8000}"
DJANGO_ENV="${DJANGO_ENV:-$DEFAULT_ENV}"
INSTALL_DEPS_ON_STARTUP="${INSTALL_DEPS_ON_STARTUP:-$DEFAULT_INSTALL_DEPS}"

# optional: install dependencies if needed (typically local-only)
if [ "$INSTALL_DEPS_ON_STARTUP" = "true" ] && [ -f "$APP_DIR/requirements.txt" ]; then
  echo "[entrypoint] Installing Python dependencies..."
  pip install -r "$REQ_FILE"
fi

# run Django migrations
echo "[entrypoint] Applying migrations..."
python "$MANAGE_PY" migrate --noinput

# collect static files
echo "[entrypoint] Collecting static files..."
python "$MANAGE_PY" collectstatic --noinput

if [ "$DJANGO_ENV" = "production" ]; then
  echo "[entrypoint] Starting Gunicorn on ${HOST}:${PORT}"
  exec gunicorn --chdir "$APP_DIR/projttgs" projttgs.wsgi:application --bind "${HOST}:${PORT}" --workers "${GUNICORN_WORKERS:-3}" --timeout "${GUNICORN_TIMEOUT:-120}"
fi

echo "[entrypoint] Starting Django development server on ${HOST}:${PORT}"
exec python "$MANAGE_PY" runserver "${HOST}:${PORT}"
