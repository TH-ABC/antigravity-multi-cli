#!/usr/bin/env bash
# Quick wrapper to run CLI for any account
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/run.py" "$@"
