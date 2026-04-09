#!/usr/bin/env bash

set -euo pipefail

HOST=""

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
    *)
      echo "error: unknown argument: $1" >&2
      echo "usage: $0 --host <ssh-host>" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$HOST" ]]; then
  echo "error: missing required argument --host" >&2
  echo "usage: $0 --host <ssh-host>" >&2
  exit 1
fi

ssh "$HOST" 'mkdir -p /root/RVDATA'

rsync -avh --progress --partial \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '*.pyo' \
  --exclude '*.pyd' \
  --exclude '.DS_Store' \
  --exclude '/source/' \
  /Users/zxf/Desktop/DataSet/ "$HOST":/root/RVDATA/
