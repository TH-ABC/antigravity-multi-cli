#!/usr/bin/env python3
"""Antigravity Multi-Account Terminal Runner.

Usage:
  # 1. Interactive terminal shell with isolated account:
  python3 run.py acc-1

  # 2. Run a specific command with this account:
  python3 run.py acc-1 agy -p "Generate a storybook cover"

  # 3. Fast launch with raw token (auto provisions if not exists):
  python3 run.py --token "1//0..." --id acc-quick
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
PROFILES_DIR = BASE_DIR / "profiles"
DATA_DIR = BASE_DIR / "data"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"
MAIN_CLI_DIR = Path.home() / ".gemini" / "antigravity-cli"

# Load environment variables from .env if present
def _load_env_file(dotenv_path: Path):
    if dotenv_path.exists():
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except Exception:
            pass

_load_env_file(BASE_DIR / ".env")

# Google OAuth Constants
GOOGLE_CLIENT_ID = os.environ.get("AGY_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("AGY_CLIENT_SECRET", "")


def load_accounts() -> dict[str, dict]:
    if ACCOUNTS_FILE.exists():
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_accounts(accounts: dict[str, dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)


def refresh_google_token(refresh_tok: str) -> dict:
    url = "https://oauth2.googleapis.com/token"
    params = urllib.parse.urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_tok.strip(),
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=params,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ensure_profile(acc_id: str, acc_data: dict) -> Path:
    prof_dir = PROFILES_DIR / acc_id
    cli_dir = prof_dir / ".gemini" / "antigravity-cli"
    cli_dir.mkdir(parents=True, exist_ok=True)
    token_file = cli_dir / "antigravity-oauth-token"

    # Check proactive refresh
    ref_tok = acc_data.get("refresh_token")
    if ref_tok and not token_file.exists():
        token_struct = {
            "token": {
                "access_token": acc_data.get("access_token", ""),
                "token_type": "Bearer",
                "refresh_token": ref_tok,
                "expiry": "2030-01-01T00:00:00Z",
            },
            "auth_method": "consumer",
            "id_token": acc_data.get("id_token", ""),
        }
        token_file.write_text(json.dumps(token_struct, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(token_file, 0o600)
        except Exception:
            pass

    # Copy template settings and installation_id
    if MAIN_CLI_DIR.exists():
        for fname in ["settings.json", "installation_id"]:
            src = MAIN_CLI_DIR / fname
            dst = cli_dir / fname
            if src.exists() and not dst.exists():
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    pass

    return prof_dir


def notify_hermes(event_type: str, account_id: str, details: dict | None = None):
    """Bridge notification to Hermes if hermes_bridge is present."""
    try:
        from hermes_bridge import send_hermes_event
        send_hermes_event(event_type=event_type, account_id=account_id, details=details or {})
    except Exception:
        pass


def run_interactive_shell(acc_id: str, profile_dir: Path, email: str, tier: str):
    """Launch an interactive zsh/bash subshell with isolated HOME."""
    user_shell = os.environ.get("SHELL", "/bin/zsh")
    env = dict(os.environ)
    env["HOME"] = str(profile_dir)
    env["AGY_ACTIVE_ACCOUNT"] = acc_id
    env["AGY_ACCOUNT_EMAIL"] = email
    env["AGY_ACCOUNT_TIER"] = tier
    env["PS1"] = f"\033[1;35m[AGY:{acc_id}]\033[0m % "

    print("\n" + "=" * 65)
    print(f"✨ KÍCH HOẠT PHIÊN LÀM VIỆC ISOLATED CHO [{acc_id.upper()}]")
    print(f"📧 Tài khoản Google: {email}")
    print(f"🏷️  Phân hạng (Tier): {tier.upper()}")
    print(f"📁 Thư mục Profile:  {profile_dir}")
    print(f"💡 Gõ 'agy' hoặc bất kỳ lệnh nào. Gõ 'exit' để thoát phiên.")
    print("=" * 65 + "\n")

    notify_hermes("TERMINAL_STARTED", acc_id, {"email": email, "tier": tier, "pid": os.getpid()})

    try:
        subprocess.run([user_shell], env=env)
    finally:
        notify_hermes("TERMINAL_EXITED", acc_id, {"email": email, "tier": tier, "pid": os.getpid()})
        print(f"\n[AGY:{acc_id}] Đã thoát phiên làm việc.\n")


def run_command(acc_id: str, profile_dir: Path, cmd: list[str]):
    """Run an isolated non-interactive command."""
    env = dict(os.environ)
    env["HOME"] = str(profile_dir)
    env["AGY_ACTIVE_ACCOUNT"] = acc_id

    cmd_display = " ".join(cmd)
    notify_hermes("COMMAND_STARTING", acc_id, {"command": cmd_display, "pid": os.getpid()})
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, env=env)
        elapsed = round(time.time() - t0, 2)
        notify_hermes(
            "COMMAND_FINISHED",
            acc_id,
            {"command": cmd_display, "returncode": proc.returncode, "elapsed_s": elapsed},
        )
        sys.exit(proc.returncode)
    except Exception as exc:
        notify_hermes("COMMAND_ERROR", acc_id, {"command": cmd_display, "error": str(exc)})
        print(f"❌ Lỗi thực thi lệnh: {exc}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Antigravity Multi-Account Terminal Runner",
        add_help=False,
    )
    parser.add_argument("account", nargs="?", default="", help="Mã tài khoản (ví dụ: acc-1, pro-01)")
    parser.add_argument("--token", default="", help="Google OAuth Refresh Token")
    parser.add_argument("--id", default="", help="Account ID khi dùng cùng --token")
    parser.add_argument("--shell", action="store_true", help="Luôn mở subshell tương tác")
    parser.add_argument("-h", "--help", action="store_true", help="Hiển thị trợ giúp")

    # Parse known args so trailing commands pass to sub-process
    args, remaining = parser.parse_known_args()

    if args.help or (not args.account and not args.token):
        accounts = load_accounts()
        print("\nCách dùng:")
        print("  python3 run.py <mã_tài_khoản>                 # Vào terminal tương tác")
        print("  python3 run.py <mã_tài_khoản> agy -p \"...\"    # Chạy 1 câu lệnh trực tiếp")
        print("  python3 run.py --token <refresh_token>        # Chạy nhanh với mã token\n")
        print("Danh sách tài khoản hiện có:")
        if accounts:
            for acc_id, data in accounts.items():
                print(f"  • {acc_id:<12} | {data.get('email', 'unknown'):<30} | {data.get('tier', 'ultra').upper()}")
        else:
            print("  (Chưa có tài khoản nào. Hãy chạy: python3 app.py để nạp tài khoản)")
        print()
        sys.exit(0)

    acc_id = args.account or args.id or "acc-default"
    accounts = load_accounts()

    if args.token:
        # Quick-provision from token
        ref_tok = args.token.strip()
        print(f"🔄 Đang xác thực và nạp token cho [{acc_id}]...")
        try:
            tokens = refresh_google_token(ref_tok)
            tokens["refresh_token"] = ref_tok
            acc_data = {
                "id": acc_id,
                "email": tokens.get("id_token", "") or f"{acc_id}@antigravity.user",
                "tier": "ultra",
                "refresh_token": ref_tok,
                "access_token": tokens.get("access_token", ""),
                "id_token": tokens.get("id_token", ""),
            }
            accounts[acc_id] = acc_data
            save_accounts(accounts)
        except Exception as e:
            print(f"❌ Token không hợp lệ hoặc lỗi kết nối Google: {e}", file=sys.stderr)
            sys.exit(1)

    if acc_id not in accounts:
        # Check if physical profile exists
        prof_dir = PROFILES_DIR / acc_id
        if not (prof_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token").exists():
            print(f"❌ Không tìm thấy tài khoản [{acc_id}]!", file=sys.stderr)
            print(f"💡 Chạy 'python3 app.py' để thêm tài khoản vào hệ thống.", file=sys.stderr)
            sys.exit(1)
        acc_data = {"id": acc_id, "email": "local-profile@antigravity", "tier": "ultra"}
    else:
        acc_data = accounts[acc_id]

    prof_dir = ensure_profile(acc_id, acc_data)

    if remaining and not args.shell:
        run_command(acc_id, prof_dir, remaining)
    else:
        run_interactive_shell(
            acc_id=acc_id,
            profile_dir=prof_dir,
            email=acc_data.get("email", "unknown"),
            tier=acc_data.get("tier", "ultra"),
        )


if __name__ == "__main__":
    main()
