#!/usr/bin/env bash
# Push changes to GitHub using token from .env
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
  # Read GITHUB_TOKEN and GITHUB_REPO from .env
  GITHUB_TOKEN="$(grep -E '^GITHUB_TOKEN=' "$ENV_FILE" | cut -d '=' -f2- | tr -d '\"'\''')"
  GITHUB_REPO="$(grep -E '^GITHUB_REPO=' "$ENV_FILE" | cut -d '=' -f2- | tr -d '\"'\''')"
fi

GITHUB_REPO="${GITHUB_REPO:-https://github.com/TH-ABC/antigravity-multi-cli.git}"

if [ -n "$GITHUB_TOKEN" ]; then
  # Strip protocol and existing credentials
  REPO_CLEAN="$(echo "$GITHUB_REPO" | sed -E 's|^https?://([^@]+@)?||')"
  git remote set-url origin "https://${GITHUB_TOKEN}@${REPO_CLEAN}"
  echo "🔑 Đã cấu hình remote URL với GITHUB_TOKEN từ .env"
fi

BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"
echo "🚀 Đang push lên origin/$BRANCH..."
git push origin "$BRANCH"
echo "✅ Đã push thành công!"
