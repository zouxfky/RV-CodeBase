#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage:
  ./rsync_host.sh --host <ssh-host>
  ./rsync_host.sh <host[:port]> <user> [password]
EOF
}

HOST=""
PORT=""
USER_NAME=""
PASSWORD=""

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

REMOTE_HOST="$HOST"
if [[ -n "$USER_NAME" ]]; then
  REMOTE_HOST="${USER_NAME}@${HOST}"
fi

SSH_ARGS=()
if [[ -n "$PORT" ]]; then
  SSH_ARGS+=(-p "$PORT")
fi

if [[ -n "$PASSWORD" ]]; then
  if ! command -v sshpass >/dev/null 2>&1; then
    echo "error: password mode requires sshpass to be installed" >&2
    exit 1
  fi
  SSHPASS_CMD=(sshpass -p "$PASSWORD")
else
  SSHPASS_CMD=()
fi

"${SSHPASS_CMD[@]}" ssh "${SSH_ARGS[@]}" "$REMOTE_HOST" 'mkdir -p /root/RVDATA'

"${SSHPASS_CMD[@]}" rsync -avh --progress --partial \
  -e "ssh ${PORT:+-p $PORT}" \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '*.pyo' \
  --exclude '*.pyd' \
  --exclude '.DS_Store' \
  --exclude '/source/' \
  /Users/zxf/Desktop/DataSet/ "${REMOTE_HOST}":/root/RVDATA/
