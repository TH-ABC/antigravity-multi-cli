#!/usr/bin/env bash
# Quick launcher for Antigravity Multi-CLI Hub Web App
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "🚀 Đang khởi động Antigravity Multi-CLI Hub..."
python3 "$SCRIPT_DIR/app.py"
