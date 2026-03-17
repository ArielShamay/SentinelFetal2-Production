#!/usr/bin/env bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
while [ -L "$SCRIPT_PATH" ]; do
  SCRIPT_DIR="$(cd -P "$(dirname "$SCRIPT_PATH")" && pwd)"
  LINK_TARGET="$(readlink "$SCRIPT_PATH")"
  case "$LINK_TARGET" in
    /*) SCRIPT_PATH="$LINK_TARGET" ;;
    *) SCRIPT_PATH="$SCRIPT_DIR/$LINK_TARGET" ;;
  esac
done

REPO_ROOT="$(cd -P "$(dirname "$SCRIPT_PATH")" && pwd)"
LOCAL_JUST="${REPO_ROOT}/.tools/just"
JUSTFILE_PATH="${REPO_ROOT}/justfile"

if [ ! -x "$LOCAL_JUST" ]; then
  printf 'error: %s is missing. Run: ./setup just\n' "$LOCAL_JUST" >&2
  exit 1
fi

if [ ! -f "$JUSTFILE_PATH" ]; then
  printf 'error: %s is missing.\n' "$JUSTFILE_PATH" >&2
  exit 1
fi

exec "$LOCAL_JUST" --justfile "$JUSTFILE_PATH" --working-directory "$REPO_ROOT" "$@"
