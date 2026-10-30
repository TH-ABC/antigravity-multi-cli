#!/usr/bin/env python3
"""Antigravity Multi-Account Manager & CLI Launcher Web App.

Zero-dependency local server using Python standard library:
- Web dashboard to authenticate Google accounts via OAuth PKCE
- Auto-generates and provisions isolated ~/.gemini profiles
- Launches terminal sessions isolated per account
- Bridges events to Hermes & Zalo Bot
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Paths & Directories
BASE_DIR = Path(__file__).resolve().parent
PROFILES_DIR = BASE_DIR / "profiles"
DATA_DIR = BASE_DIR / "data"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

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

# Main machine installation reference for templates
MAIN_CLI_DIR = Path.home() / ".gemini" / "antigravity-cli"

# Google Antigravity OAuth App Credentials
GOOGLE_CLIENT_ID = os.environ.get("AGY_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("AGY_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = "https://antigravity.google/oauth-callback"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
    "https://www.googleapis.com/auth/aicode",
    "openid",
]

PORT = 7890


# ── Database Helpers ──────────────────────────────────────────────────────────

def load_accounts() -> dict[str, dict]:
    """Load accounts from JSON file."""
    if ACCOUNTS_FILE.exists():
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_accounts(accounts: dict[str, dict]) -> None:
    """Save accounts to JSON file."""
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)


def extract_email_from_jwt(id_token: str) -> str:
    """Decode JWT payload without verifying signature to extract email."""
    try:
        parts = id_token.split(".")
        if len(parts) >= 2:
            payload = parts[1]
            padded = payload + "=" * ((4 - len(payload) % 4) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode("utf-8"))
            return data.get("email", "")
    except Exception:
        pass
    return ""


def provision_profile(acc_id: str, tokens: dict) -> Path:
    """Create an isolated ~/.gemini profile directory structure."""
    prof_dir = PROFILES_DIR / acc_id
    cli_dir = prof_dir / ".gemini" / "antigravity-cli"
    cli_dir.mkdir(parents=True, exist_ok=True)

    # 1. Write antigravity-oauth-token
    token_struct = {
        "token": {
            "access_token": tokens.get("access_token", ""),
            "token_type": tokens.get("token_type", "Bearer"),
            "refresh_token": tokens.get("refresh_token", ""),
            "expiry": "2030-01-01T00:00:00Z",
        },
        "auth_method": "consumer",
        "id_token": tokens.get("id_token", ""),
    }
    token_file = cli_dir / "antigravity-oauth-token"
    token_file.write_text(json.dumps(token_struct, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(token_file, 0o600)
    except Exception:
        pass

    # 2. Copy settings.json & installation_id if available on host
    if MAIN_CLI_DIR.exists():
        for fname in ["settings.json", "installation_id"]:
            src = MAIN_CLI_DIR / fname
            dst = cli_dir / fname
            if src.exists() and not dst.exists():
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    pass
    else:
        # Default fallback settings
        settings_file = cli_dir / "settings.json"
        if not settings_file.exists():
            settings_file.write_text(
                json.dumps({"model": "Gemini 3.8 Flash (Medium)"}, indent=2),
                encoding="utf-8",
            )

    return prof_dir


def exchange_code_for_token(code: str, code_verifier: str) -> dict:
    """Exchange authorization code via Google OAuth endpoint."""
    url = "https://oauth2.googleapis.com/token"
    params = urllib.parse.urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code.strip(),
        "code_verifier": code_verifier.strip(),
        "redirect_uri": GOOGLE_REDIRECT_URI,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=params,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def refresh_token(refresh_tok: str) -> dict:
    """Refresh Google OAuth access token."""
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


def open_terminal_for_account(acc_id: str) -> bool:
    """Open a new macOS Terminal or iTerm2 window set up for this account."""
    runner_script = BASE_DIR / "run.py"
    cmd_str = f"python3 '{runner_script}' '{acc_id}' --shell"

    if platform.system() == "Darwin":
        # AppleScript for macOS Terminal
        scpt = f'''
        tell application "Terminal"
            activate
            do script "{cmd_str}"
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", scpt], check=True)
            return True
        except Exception:
            return False
    return False


# ── HTTP Request Handler ──────────────────────────────────────────────────────

class AppHandler(BaseHTTPRequestHandler):
    def _send_json(self, data: dict | list, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = 200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self._send_html(INDEX_HTML)
            return

        if path == "/api/status":
            accounts = load_accounts()
            items = []
            for acc_id, acc in accounts.items():
                prof_dir = PROFILES_DIR / acc_id
                items.append({
                    "id": acc_id,
                    "email": acc.get("email", ""),
                    "tier": acc.get("tier", "ultra"),
                    "created_at": acc.get("created_at", ""),
                    "has_token": bool(acc.get("refresh_token")),
                    "profile_dir": str(prof_dir),
                    "active": acc.get("active", True),
                })
            self._send_json({"ok": True, "accounts": items, "count": len(items)})
            return

        self._send_json({"error": "Not Found"}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        length = int(self.headers.get("Content-Length", 0))
        body_raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            data = json.loads(body_raw)
        except Exception:
            data = {}

        # 1. Generate PKCE codes & Google Auth URL
        if path == "/api/pkce":
            raw_bytes = os.urandom(32)
            verifier = base64.urlsafe_b64encode(raw_bytes).decode("utf-8").rstrip("=")
            digest = hashlib.sha256(verifier.encode("utf-8")).digest()
            challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")

            auth_params = urllib.parse.urlencode({
                "client_id": GOOGLE_CLIENT_ID,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "response_type": "code",
                "access_type": "offline",
                "prompt": "select_account consent",
                "scope": " ".join(GOOGLE_SCOPES),
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": os.urandom(8).hex(),
            })
            auth_url = f"https://accounts.google.com/o/oauth2/auth?{auth_params}"

            self._send_json({
                "ok": True,
                "verifier": verifier,
                "challenge": challenge,
                "auth_url": auth_url,
            })
            return

        # 2. Add / Provision Account
        if path == "/api/accounts/add":
            code = data.get("code", "").strip()
            verifier = data.get("verifier", "").strip()
            refresh_tok = data.get("refresh_token", "").strip()
            tier = data.get("tier", "ultra").lower()
            acc_id = data.get("id", "").strip().lower()

            if not acc_id:
                existing = load_accounts()
                count = sum(1 for k in existing if k.startswith(tier)) + 1
                acc_id = f"{tier}-{count}"
            acc_id = re.sub(r"[^a-z0-9_-]", "-", acc_id).strip("-")

            tokens = {}
            if code and verifier:
                try:
                    tokens = exchange_code_for_token(code, verifier)
                except urllib.error.HTTPError as e:
                    err_msg = e.read().decode("utf-8")
                    self._send_json({"ok": False, "error": f"Lỗi đổi mã Google: {err_msg}"}, 400)
                    return
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
                    return
            elif refresh_tok:
                try:
                    tokens = refresh_token(refresh_tok)
                    tokens["refresh_token"] = refresh_tok
                except Exception as e:
                    self._send_json({"ok": False, "error": f"Token không hợp lệ: {e}"}, 400)
                    return
            else:
                self._send_json({"ok": False, "error": "Cần cung cấp mã ủy quyền hoặc refresh_token"}, 400)
                return

            email = extract_email_from_jwt(tokens.get("id_token", ""))
            if not email and tokens.get("access_token"):
                # Call userinfo
                try:
                    req = urllib.request.Request(
                        "https://www.googleapis.com/oauth2/v1/userinfo",
                        headers={"Authorization": f"Bearer {tokens['access_token']}"},
                    )
                    with urllib.request.urlopen(req, timeout=10) as r:
                        uinfo = json.loads(r.read().decode("utf-8"))
                        email = uinfo.get("email", "")
                except Exception:
                    pass

            if not email:
                email = f"{acc_id}@antigravity.user"

            # Provision the physical profile directory
            prof_dir = provision_profile(acc_id, tokens)

            # Save metadata
            accounts = load_accounts()
            accounts[acc_id] = {
                "id": acc_id,
                "email": email,
                "tier": tier,
                "refresh_token": tokens.get("refresh_token", ""),
                "access_token": tokens.get("access_token", ""),
                "id_token": tokens.get("id_token", ""),
                "profile_dir": str(prof_dir),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "active": True,
            }
            save_accounts(accounts)

            self._send_json({
                "ok": True,
                "message": f"Khởi tạo thành công tài khoản [{acc_id}] ({email})!",
                "account": {
                    "id": acc_id,
                    "email": email,
                    "tier": tier,
                    "profile_dir": str(prof_dir),
                },
            })
            return

        # 3. Check health of an account
        if path == "/api/accounts/check":
            acc_id = data.get("id", "")
            accounts = load_accounts()
            if acc_id not in accounts:
                self._send_json({"ok": False, "error": "Không tìm thấy tài khoản"}, 404)
                return

            acc = accounts[acc_id]
            ref_tok = acc.get("refresh_token")
            if not ref_tok:
                self._send_json({"ok": False, "error": "Chưa có refresh_token"}, 400)
                return

            try:
                ref_res = refresh_token(ref_tok)
                acc["access_token"] = ref_res.get("access_token", acc.get("access_token"))
                if "id_token" in ref_res:
                    acc["id_token"] = ref_res["id_token"]
                save_accounts(accounts)
                # Re-provision token file
                provision_profile(acc_id, acc)
                self._send_json({
                    "ok": True,
                    "email": acc.get("email"),
                    "message": "Kết nối Google OAuth thành công! Token đã làm mới.",
                })
            except Exception as e:
                self._send_json({"ok": False, "error": f"Lỗi xác thực: {e}"}, 400)
            return

        # 4. Open Terminal for account
        if path == "/api/accounts/open-terminal":
            acc_id = data.get("id", "")
            accounts = load_accounts()
            if acc_id not in accounts:
                self._send_json({"ok": False, "error": "Không tìm thấy tài khoản"}, 404)
                return

            success = open_terminal_for_account(acc_id)
            if success:
                self._send_json({"ok": True, "message": f"Đã mở cửa sổ Terminal cho [{acc_id}]!"})
            else:
                self._send_json({"ok": False, "error": "Không thể kích hoạt Terminal tự động. Vui lòng mở thủ công."}, 500)
            return

        # 5. Test CLI command for account
        if path == "/api/accounts/test-cli":
            acc_id = data.get("id", "")
            accounts = load_accounts()
            if acc_id not in accounts:
                self._send_json({"ok": False, "error": "Không tìm thấy tài khoản"}, 404)
                return

            prof_dir = PROFILES_DIR / acc_id
            env = dict(os.environ, HOME=str(prof_dir))
            try:
                proc = subprocess.run(
                    ["agy", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=env,
                )
                output = proc.stdout.strip() or proc.stderr.strip()
                self._send_json({"ok": True, "output": output})
            except FileNotFoundError:
                self._send_json({"ok": False, "error": "Không tìm thấy lệnh 'agy' trên hệ thống"}, 500)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # 6. Delete account
        if path == "/api/accounts/delete":
            acc_id = data.get("id", "")
            accounts = load_accounts()
            if acc_id in accounts:
                del accounts[acc_id]
                save_accounts(accounts)
                prof_dir = PROFILES_DIR / acc_id
                if prof_dir.exists():
                    try:
                        shutil.rmtree(prof_dir)
                    except Exception:
                        pass
                self._send_json({"ok": True, "message": f"Đã xoá tài khoản [{acc_id}]."})
            else:
                self._send_json({"ok": False, "error": "Không tìm thấy tài khoản"}, 404)
            return

        self._send_json({"error": "Not Found"}, 404)


# ── Modern Single Page Web UI ────────────────────────────────────────────────

INDEX_HTML = """<!DOCTYPE html>
<html lang="vi" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Antigravity Multi-Account Hub</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            brand: { 50: '#eef2ff', 500: '#6366f1', 600: '#4f46e5', 700: '#4338ca', 900: '#1e1b4b' }
          }
        }
      }
    }
  </script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col font-sans antialiased">
  <!-- Top Navigation -->
  <header class="border-b border-slate-800 bg-slate-900/60 backdrop-blur sticky top-0 z-50 px-6 py-4 flex items-center justify-between">
    <div class="flex items-center space-x-3">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
        <i class="fa-solid fa-atom text-white text-xl"></i>
      </div>
      <div>
        <h1 class="text-lg font-bold tracking-tight bg-gradient-to-r from-white via-indigo-200 to-indigo-400 bg-clip-text text-transparent">
          Antigravity Multi-CLI Hub
        </h1>
        <p class="text-xs text-slate-400">Trình quản lý Cookie / Token & Launcher đa Terminal</p>
      </div>
    </div>
    <div class="flex items-center space-x-3">
      <button onclick="loadAccounts()" class="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm flex items-center space-x-2 transition border border-slate-700">
        <i class="fa-solid fa-rotate"></i>
        <span>Làm mới</span>
      </button>
      <button onclick="openAddModal()" class="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold flex items-center space-x-2 shadow-lg shadow-indigo-600/30 transition">
        <i class="fa-solid fa-plus"></i>
        <span>Thêm Tài Khoản</span>
      </button>
    </div>
  </header>

  <!-- Main Content Container -->
  <main class="flex-1 max-w-6xl w-full mx-auto px-6 py-8 space-y-8">
    <!-- Quick Guide Banner -->
    <div class="bg-gradient-to-r from-indigo-950/60 to-purple-950/40 border border-indigo-900/50 rounded-2xl p-6 shadow-xl relative overflow-hidden">
      <div class="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div class="space-y-1">
          <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <i class="fa-solid fa-bolt mr-1.5"></i> Profile Isolation Active
          </span>
          <h2 class="text-xl font-bold text-white">Chạy Độc Lập Mỗi Terminal Một Tài Khoản</h2>
          <p class="text-sm text-slate-300 max-w-2xl leading-relaxed">
            Mỗi tài khoản được nạp vào sẽ sinh riêng một thư mục <code class="bg-slate-900/80 px-2 py-0.5 rounded text-indigo-300 font-mono text-xs">profiles/&lt;mã_acc&gt;</code>. Khi mở Terminal chỉ cần truyền mã tài khoản, các phiên không bao giờ đá nhau.
          </p>
        </div>
        <div class="flex items-center gap-3">
          <button onclick="openUsageModal()" class="px-4 py-2.5 rounded-xl bg-slate-800/80 hover:bg-slate-700 text-slate-200 text-sm font-medium border border-slate-700 transition flex items-center space-x-2">
            <i class="fa-solid fa-terminal text-indigo-400"></i>
            <span>Xem lệnh Terminal</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Accounts Grid -->
    <div>
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-base font-semibold text-slate-200 flex items-center space-x-2">
          <span>Danh sách Tài Khoản CLI</span>
          <span id="accountCount" class="text-xs bg-slate-800 text-slate-400 px-2.5 py-0.5 rounded-full border border-slate-700">0</span>
        </h3>
      </div>

      <div id="accountsList" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        <!-- Rendered by JS -->
      </div>

      <!-- Empty State -->
      <div id="emptyState" class="hidden text-center py-16 border border-dashed border-slate-800 rounded-2xl bg-slate-900/30">
        <div class="w-16 h-16 mx-auto mb-4 rounded-2xl bg-slate-800/60 flex items-center justify-center text-slate-500">
          <i class="fa-regular fa-folder-open text-2xl"></i>
        </div>
        <h4 class="text-base font-semibold text-slate-300">Chưa có tài khoản Antigravity nào</h4>
        <p class="text-sm text-slate-500 mt-1 max-w-sm mx-auto">Bấm nút "Thêm Tài Khoản" phía trên để đăng nhập Google OAuth và cấp quyền cho CLI.</p>
        <button onclick="openAddModal()" class="mt-4 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition">
          <i class="fa-solid fa-plus mr-1"></i> Thêm Tài Khoản Ngay
        </button>
      </div>
    </div>
  </main>

  <!-- Add Account Modal -->
  <div id="addModal" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
    <div class="bg-slate-900 border border-slate-800 w-full max-w-lg rounded-2xl shadow-2xl p-6 space-y-6">
      <div class="flex items-center justify-between border-b border-slate-800 pb-4">
        <div class="flex items-center space-x-2">
          <i class="fa-brands fa-google text-indigo-400 text-lg"></i>
          <h3 class="font-bold text-white text-base">Thêm Tài Khoản Google / Antigravity</h3>
        </div>
        <button onclick="closeAddModal()" class="text-slate-400 hover:text-white"><i class="fa-solid fa-xmark text-lg"></i></button>
      </div>

      <!-- Step 1: Open Google OAuth -->
      <div id="step1" class="space-y-4">
        <div class="p-4 rounded-xl bg-indigo-950/40 border border-indigo-900/50 space-y-2">
          <div class="text-xs font-semibold uppercase tracking-wider text-indigo-400">Bước 1: Ủy Quyền Google</div>
          <p class="text-sm text-slate-300">Nhấn nút bên dưới để mở cửa sổ đăng nhập Google. Chọn tài khoản của bạn và bấm <b>Cho phép</b>.</p>
        </div>
        <div class="space-y-3">
          <div>
            <label class="block text-xs font-semibold text-slate-300 mb-1">Mã Tài Khoản / Alias (Viết liền, không dấu)</label>
            <input id="inputAccId" type="text" placeholder="ví dụ: acc-1, pro-01, ultra-2..." class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
          </div>
          <div>
            <label class="block text-xs font-semibold text-slate-300 mb-1">Phân hạng (Tier)</label>
            <select id="inputTier" class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
              <option value="ultra">Ultra (Ưu tiên tạo ảnh cao cấp / Bìa / Mockup)</option>
              <option value="pro">Pro (Chuẩn / Trang truyện & Task thường)</option>
            </select>
          </div>
        </div>
        <button onclick="handleStartOAuth()" class="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-sm flex items-center justify-center space-x-2 shadow-lg shadow-indigo-600/30 transition">
          <i class="fa-solid fa-arrow-up-right-from-square"></i>
          <span>Mở Đăng Nhập Google (OAuth PKCE)</span>
        </button>
      </div>

      <!-- Step 2: Paste Code -->
      <div id="step2" class="space-y-4 hidden">
        <div class="p-4 rounded-xl bg-purple-950/40 border border-purple-900/50 space-y-2">
          <div class="text-xs font-semibold uppercase tracking-wider text-purple-400">Bước 2: Dán Mã Ủy Quyền</div>
          <p class="text-sm text-slate-300">Sau khi đăng nhập và bấm Allow, Google sẽ hiện trang có mã xác thực. Hãy sao chép và dán vào đây.</p>
        </div>
        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1">Mã xác thực từ Google (Authorization Code / Token)</label>
          <div class="flex gap-2">
            <input id="inputAuthCode" type="text" placeholder="Dán mã 4/0A..." class="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-purple-500">
            <button onclick="handlePasteClipboard()" class="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-medium border border-slate-700">
              <i class="fa-regular fa-clipboard mr-1"></i> Dán
            </button>
          </div>
        </div>
        <div class="flex space-x-3">
          <button onclick="backToStep1()" class="w-1/3 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-semibold transition">
            Quay lại
          </button>
          <button id="btnSubmitAdd" onclick="handleSubmitAccount()" class="w-2/3 py-2.5 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white text-sm font-semibold shadow-lg shadow-purple-600/30 transition flex items-center justify-center space-x-2">
            <span>Khởi Tạo Profile & CLI</span>
            <i class="fa-solid fa-circle-check"></i>
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Usage Modal -->
  <div id="usageModal" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
    <div class="bg-slate-900 border border-slate-800 w-full max-w-2xl rounded-2xl shadow-2xl p-6 space-y-5">
      <div class="flex items-center justify-between border-b border-slate-800 pb-3">
        <h3 class="font-bold text-white text-base flex items-center space-x-2">
          <i class="fa-solid fa-terminal text-indigo-400"></i>
          <span>Hướng Dẫn Lệnh Terminal Đa Tài Khoản</span>
        </h3>
        <button onclick="closeUsageModal()" class="text-slate-400 hover:text-white"><i class="fa-solid fa-xmark text-lg"></i></button>
      </div>

      <div class="space-y-4 text-sm text-slate-300">
        <div>
          <h4 class="font-semibold text-white mb-1.5 flex items-center space-x-2">
            <span class="w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-400 text-xs flex items-center justify-center font-bold">1</span>
            <span>Mở Terminal tương tác vào thẳng tài khoản:</span>
          </h4>
          <pre class="bg-slate-950 p-3 rounded-lg border border-slate-800 font-mono text-xs text-indigo-300 select-all">python3 run.py acc-1</pre>
          <p class="text-xs text-slate-400 mt-1">Terminal này lập tức nhận diện <code class="text-indigo-300 font-mono">acc-1</code>. Bạn chỉ cần gõ <code class="text-indigo-300 font-mono">agy</code> hoặc bất kỳ câu lệnh nào.</p>
        </div>

        <div>
          <h4 class="font-semibold text-white mb-1.5 flex items-center space-x-2">
            <span class="w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-400 text-xs flex items-center justify-center font-bold">2</span>
            <span>Mở Terminal thứ hai vào tài khoản khác:</span>
          </h4>
          <pre class="bg-slate-950 p-3 rounded-lg border border-slate-800 font-mono text-xs text-indigo-300 select-all">python3 run.py acc-2</pre>
          <p class="text-xs text-slate-400 mt-1">Chạy song song hoàn toàn độc lập, không đá phiên, không ảnh hưởng token của nhau.</p>
        </div>

        <div>
          <h4 class="font-semibold text-white mb-1.5 flex items-center space-x-2">
            <span class="w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-400 text-xs flex items-center justify-center font-bold">3</span>
            <span>Chạy một câu lệnh AGY trực tiếp không cần mở subshell:</span>
          </h4>
          <pre class="bg-slate-950 p-3 rounded-lg border border-slate-800 font-mono text-xs text-indigo-300 select-all">python3 run.py acc-1 agy -p "Vẽ bức tranh chú mèo phi hành gia" --output-format json</pre>
        </div>
      </div>

      <div class="pt-2 text-right">
        <button onclick="closeUsageModal()" class="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-white text-sm font-medium">Đóng</button>
      </div>
    </div>
  </div>

  <!-- Notification Toast -->
  <div id="toast" class="fixed bottom-6 right-6 z-50 transform translate-y-24 opacity-0 transition-all duration-300 bg-slate-900 border border-slate-700 shadow-2xl rounded-xl p-4 flex items-center space-x-3 max-w-md">
    <div id="toastIcon" class="text-lg"></div>
    <div id="toastMessage" class="text-sm font-medium text-slate-200"></div>
  </div>

  <script>
    let currentVerifier = '';

    function showToast(msg, type = 'info') {
      const toast = document.getElementById('toast');
      const toastMessage = document.getElementById('toastMessage');
      const toastIcon = document.getElementById('toastIcon');

      toastMessage.innerText = msg;
      if (type === 'success') {
        toastIcon.innerHTML = '<i class="fa-solid fa-circle-check text-emerald-400"></i>';
      } else if (type === 'error') {
        toastIcon.innerHTML = '<i class="fa-solid fa-triangle-exclamation text-rose-400"></i>';
      } else {
        toastIcon.innerHTML = '<i class="fa-solid fa-circle-info text-indigo-400"></i>';
      }

      toast.classList.remove('translate-y-24', 'opacity-0');
      setTimeout(() => {
        toast.classList.add('translate-y-24', 'opacity-0');
      }, 4000);
    }

    async function loadAccounts() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        const list = document.getElementById('accountsList');
        const empty = document.getElementById('emptyState');
        const count = document.getElementById('accountCount');

        list.innerHTML = '';
        count.innerText = data.count || 0;

        if (!data.accounts || data.accounts.length === 0) {
          empty.classList.remove('hidden');
          return;
        }
        empty.classList.add('hidden');

        data.accounts.forEach(acc => {
          const card = document.createElement('div');
          card.className = 'bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-lg hover:border-slate-700 transition flex flex-col justify-between space-y-4';
          card.innerHTML = `
            <div>
              <div class="flex items-start justify-between">
                <div class="flex items-center space-x-2.5">
                  <div class="w-9 h-9 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 flex items-center justify-center font-bold font-mono text-sm">
                    ${acc.id.substring(0, 2).toUpperCase()}
                  </div>
                  <div>
                    <div class="font-bold text-white text-sm flex items-center space-x-1.5">
                      <span>${acc.id}</span>
                      <span class="text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-wider ${acc.tier === 'ultra' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-blue-500/10 text-blue-400 border border-blue-500/20'}">
                        ${acc.tier}
                      </span>
                    </div>
                    <div class="text-xs text-slate-400 truncate max-w-[200px]" title="${acc.email}">${acc.email}</div>
                  </div>
                </div>
                <button onclick="handleDeleteAccount('${acc.id}')" class="text-slate-500 hover:text-rose-400 text-sm p-1.5 transition" title="Xoá tài khoản">
                  <i class="fa-regular fa-trash-can"></i>
                </button>
              </div>

              <div class="mt-4 p-2.5 bg-slate-950 rounded-lg border border-slate-800/80 space-y-1">
                <div class="text-[11px] text-slate-400 flex justify-between">
                  <span>Trạng thái:</span>
                  <span class="text-emerald-400 font-medium"><i class="fa-solid fa-circle text-[8px] mr-1"></i>Đã khởi tạo CLI</span>
                </div>
                <div class="text-[11px] text-slate-400 flex justify-between">
                  <span>Lệnh chạy:</span>
                  <code class="text-indigo-300 font-mono text-[10px] select-all">python3 run.py ${acc.id}</code>
                </div>
              </div>
            </div>

            <div class="grid grid-cols-2 gap-2 pt-2 border-t border-slate-800">
              <button onclick="handleOpenTerminal('${acc.id}')" class="py-2 px-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold flex items-center justify-center space-x-1.5 shadow-md shadow-indigo-600/20 transition">
                <i class="fa-solid fa-terminal"></i>
                <span>Mở Terminal</span>
              </button>
              <button onclick="handleCheckAccount('${acc.id}')" class="py-2 px-3 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium border border-slate-700 flex items-center justify-center space-x-1.5 transition">
                <i class="fa-solid fa-shield-halved text-indigo-400"></i>
                <span>Kiểm tra</span>
              </button>
            </div>
          `;
          list.appendChild(card);
        });
      } catch (e) {
        showToast('Không tải được danh sách tài khoản: ' + e, 'error');
      }
    }

    function openAddModal() {
      document.getElementById('addModal').classList.remove('hidden');
      document.getElementById('step1').classList.remove('hidden');
      document.getElementById('step2').classList.add('hidden');
      document.getElementById('inputAuthCode').value = '';
    }

    function closeAddModal() {
      document.getElementById('addModal').classList.add('hidden');
    }

    function openUsageModal() {
      document.getElementById('usageModal').classList.remove('hidden');
    }

    function closeUsageModal() {
      document.getElementById('usageModal').classList.add('hidden');
    }

    async function handleStartOAuth() {
      try {
        const res = await fetch('/api/pkce', { method: 'POST' });
        const data = await res.json();
        currentVerifier = data.verifier;
        window.open(data.auth_url, '_blank', 'width=600,height=750');
        document.getElementById('step1').classList.add('hidden');
        document.getElementById('step2').classList.remove('hidden');
        showToast('Đã mở cửa sổ Google OAuth. Vui lòng cấp quyền!', 'info');
      } catch (e) {
        showToast('Lỗi tạo URL OAuth: ' + e, 'error');
      }
    }

    function backToStep1() {
      document.getElementById('step2').classList.add('hidden');
      document.getElementById('step1').classList.remove('hidden');
    }

    async function handlePasteClipboard() {
      try {
        const text = await navigator.clipboard.readText();
        if (text) {
          document.getElementById('inputAuthCode').value = text.trim();
          showToast('Đã dán mã từ Clipboard!', 'success');
        }
      } catch {
        showToast('Vui lòng bấm Ctrl+V hoặc Cmd+V để dán.', 'info');
      }
    }

    async function handleSubmitAccount() {
      const code = document.getElementById('inputAuthCode').value.trim();
      const id = document.getElementById('inputAccId').value.trim();
      const tier = document.getElementById('inputTier').value;

      if (!code) {
        showToast('Vui lòng dán mã ủy quyền Google!', 'error');
        return;
      }

      const btn = document.getElementById('btnSubmitAdd');
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-1"></i> Đang khởi tạo...';

      try {
        const res = await fetch('/api/accounts/add', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            code: code,
            verifier: currentVerifier,
            id: id,
            tier: tier
          })
        });
        const data = await res.json();
        if (data.ok) {
          showToast(data.message, 'success');
          closeAddModal();
          loadAccounts();
        } else {
          showToast(data.error || 'Có lỗi xảy ra', 'error');
        }
      } catch (e) {
        showToast('Lỗi gửi request: ' + e, 'error');
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>Khởi Tạo Profile & CLI</span> <i class="fa-solid fa-circle-check"></i>';
      }
    }

    async function handleOpenTerminal(accId) {
      try {
        showToast('Đang mở Terminal cho [' + accId + ']...', 'info');
        const res = await fetch('/api/accounts/open-terminal', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: accId })
        });
        const data = await res.json();
        if (data.ok) {
          showToast(data.message, 'success');
        } else {
          showToast(data.error, 'error');
        }
      } catch (e) {
        showToast('Lỗi gọi mở terminal: ' + e, 'error');
      }
    }

    async function handleCheckAccount(accId) {
      try {
        showToast('Đang kiểm tra kết nối Google...', 'info');
        const res = await fetch('/api/accounts/check', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: accId })
        });
        const data = await res.json();
        if (data.ok) {
          showToast(data.message, 'success');
        } else {
          showToast(data.error, 'error');
        }
      } catch (e) {
        showToast('Lỗi kiểm tra: ' + e, 'error');
      }
    }

    async function handleDeleteAccount(accId) {
      if (!confirm('Bạn có chắc chắn muốn xoá tài khoản [' + accId + '] khỏi danh sách?')) return;
      try {
        const res = await fetch('/api/accounts/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: accId })
        });
        const data = await res.json();
        if (data.ok) {
          showToast(data.message, 'success');
          loadAccounts();
        } else {
          showToast(data.error, 'error');
        }
      } catch (e) {
        showToast('Lỗi xoá: ' + e, 'error');
      }
    }

    // Auto load on init
    loadAccounts();
  </script>
</body>
</html>
"""


# ── Server Runner ─────────────────────────────────────────────────────────────

def run_server(port: int = PORT) -> None:
    server_address = ("", port)
    httpd = ThreadingHTTPServer(server_address, AppHandler)
    url = f"http://localhost:{port}"
    print(f"\n=======================================================")
    print(f"🚀 Antigravity Multi-CLI Hub is running at: {url}")
    print(f"📁 Profiles directory: {PROFILES_DIR}")
    print(f"💡 Press Ctrl+C to stop the server.")
    print(f"=======================================================\n")

    # Auto-open browser
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[Antigravity Multi-CLI Hub] Shutting down...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
