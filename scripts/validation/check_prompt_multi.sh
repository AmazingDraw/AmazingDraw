#!/usr/bin/env bash
# Dist shim: run compiled check_prompt_body from card_engine_core/native.
set -euo pipefail

_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_native=""
_dir="$_here"
while [ -n "$_dir" ] && [ "$_dir" != "/" ]; do
  if [ -d "$_dir/card_engine_core/native" ]; then
    _native="$_dir/card_engine_core/native"
    break
  fi
  _dir="$(dirname "$_dir")"
done
if [ -z "$_native" ]; then
  echo "card_engine_core/native not found" >&2
  exit 1
fi

export PYTHONPATH="${_native}${PYTHONPATH:+:$PYTHONPATH}"
export CHECK_PROMPT_SCRIPT_DIR="$_here"

exec python3 - "$_native" "$@" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from check_prompt_body import run_embedded
raise SystemExit(run_embedded("multi", sys.argv[2:]))
PY
