#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat >&2 <<'EOF'
usage:
  ./rsync_host.sh --only_host <ssh-host> [--remote_path <path>]
  ./rsync_host.sh --host <ssh-host> [--remote_path <path>]
  ./rsync_host.sh <host[:port]> <user> [password] [--remote_path <path>]
EOF
}

HOST=""
PORT=""
USER_NAME=""
PASSWORD=""
REMOTE_PATH="/root/RVDATA"
USE_SSHPASS=0
ONLY_HOST=0

if [[ $# -gt 0 && "$1" != --* ]]; then
  if [[ $# -lt 2 ]]; then
    usage
    exit 1
  fi
  host_port="$1"
  USER_NAME="$2"
  PASSWORD="${3:-}"
  shift $#

  if [[ "$host_port" == *:* ]]; then
    HOST="${host_port%%:*}"
    PORT="${host_port##*:}"
  else
    HOST="$host_port"
  fi
else
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --host)
        if [[ $# -lt 2 ]]; then
          echo "error: --host requires a value" >&2
          exit 1
        fi
        HOST="$2"
        shift 2
        ;;
      --only_host)
        if [[ $# -lt 2 ]]; then
          echo "error: --only_host requires a value" >&2
          exit 1
        fi
        HOST="$2"
        ONLY_HOST=1
        shift 2
        ;;
      --port)
        if [[ $# -lt 2 ]]; then
          echo "error: --port requires a value" >&2
          exit 1
        fi
        PORT="$2"
        shift 2
        ;;
      --user)
        if [[ $# -lt 2 ]]; then
          echo "error: --user requires a value" >&2
          exit 1
        fi
        USER_NAME="$2"
        shift 2
        ;;
      --password)
        if [[ $# -lt 2 ]]; then
          echo "error: --password requires a value" >&2
          exit 1
        fi
        PASSWORD="$2"
        shift 2
        ;;
      --remote_path)
        if [[ $# -lt 2 ]]; then
          echo "error: --remote_path requires a value" >&2
          exit 1
        fi
        REMOTE_PATH="$2"
        shift 2
        ;;
      *)
        echo "error: unknown argument: $1" >&2
        usage
        exit 1
        ;;
    esac
  done
fi

if [[ -z "$HOST" ]]; then
  echo "error: missing host" >&2
  usage
  exit 1
fi

if [[ "$ONLY_HOST" -eq 1 ]]; then
  ssh "$HOST" "mkdir -p '$REMOTE_PATH'"

  rsync -avh --progress --partial \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '*.pyo' \
    --exclude '*.pyd' \
    --exclude '.DS_Store' \
    --exclude '/source/' \
    --include '/data/' \
    --include '/data/seed*' \
    --exclude '/data/*' \
    "${SCRIPT_DIR}/" "${HOST}":"${REMOTE_PATH}/"
  exit 0
fi

REMOTE_HOST="$HOST"
if [[ -n "$USER_NAME" ]]; then
  REMOTE_HOST="${USER_NAME}@${HOST}"
fi

SSH_PORT_ARG=""
RSYNC_SSH_CMD="ssh"
if [[ -n "$PORT" ]]; then
  SSH_PORT_ARG="-p $PORT"
  RSYNC_SSH_CMD="ssh -p $PORT"
fi

if [[ -n "$PASSWORD" ]]; then
  if ! command -v sshpass >/dev/null 2>&1; then
    echo "error: password mode requires sshpass to be installed" >&2
    exit 1
  fi
  USE_SSHPASS=1
fi

if [[ "$USE_SSHPASS" -eq 1 ]]; then
  if [[ -n "$SSH_PORT_ARG" ]]; then
    sshpass -p "$PASSWORD" ssh -p "$PORT" "$REMOTE_HOST" "mkdir -p '$REMOTE_PATH'"
  else
    sshpass -p "$PASSWORD" ssh "$REMOTE_HOST" "mkdir -p '$REMOTE_PATH'"
  fi

  sshpass -p "$PASSWORD" rsync -avh --progress --partial \
    -e "$RSYNC_SSH_CMD" \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '*.pyo' \
    --exclude '*.pyd' \
    --exclude '.DS_Store' \
    --exclude '/source/' \
    --include '/data/' \
    --include '/data/seed*' \
    --exclude '/data/*' \
    "${SCRIPT_DIR}/" "${REMOTE_HOST}":"${REMOTE_PATH}/"
else
  if [[ -n "$SSH_PORT_ARG" ]]; then
    ssh -p "$PORT" "$REMOTE_HOST" "mkdir -p '$REMOTE_PATH'"
  else
    ssh "$REMOTE_HOST" "mkdir -p '$REMOTE_PATH'"
  fi

  rsync -avh --progress --partial \
    -e "$RSYNC_SSH_CMD" \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '*.pyo' \
    --exclude '*.pyd' \
    --exclude '.DS_Store' \
    --exclude '/source/' \
    --include '/data/' \
    --include '/data/seed*' \
    --exclude '/data/*' \
    "${SCRIPT_DIR}/" "${REMOTE_HOST}":"${REMOTE_PATH}/"
fi
