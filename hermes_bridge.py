#!/usr/bin/env python3
"""Hermes & Zalo Bot Event Bridge for Antigravity Multi-CLI.

Acts as the telemetry and event notification layer between:
  Terminal Runner (per-account session) ---> Hermes Agent ---> Zalo Bot

Capabilities:
  1. Identifies Terminal sessions by Account ID, PID, Hostname, and Session ID.
  2. Dispatches events (TERMINAL_STARTED, COMMAND_FINISHED, ERROR_429, etc.)
  3. Sends messages to Hermes Gateway (HTTP webhook / WebSocket) or direct Zalo Bot.
"""

from __future__ import annotations

import json
import os
import platform
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOGS_FILE = DATA_DIR / "events.log"
CONFIG_FILE = BASE_DIR / "hermes_config.json"

DEFAULT_CONFIG = {
    "hermes_enabled": False,
    "hermes_endpoint": "http://127.0.0.1:8080/api/hermes/events",
    "hermes_auth_token": "hermes-secret-key",
    "zalo_direct_webhook": "",
    "log_events": True,
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return {**DEFAULT_CONFIG, **cfg}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def get_device_identity() -> dict:
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
    }


def send_hermes_event(event_type: str, account_id: str, details: dict | None = None) -> bool:
    """Send a structured event message to Hermes or local event log."""
    config = load_config()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload = {
        "source": "antigravity-multi-cli",
        "event_type": event_type,
        "account_id": account_id,
        "timestamp": now_iso,
        "device": get_device_identity(),
        "details": details or {},
    }

    # 1. Log locally
    if config.get("log_events", True):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(LOGS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # 2. Forward to Hermes Gateway if enabled
    delivered = False
    if config.get("hermes_enabled") and config.get("hermes_endpoint"):
        endpoint = config["hermes_endpoint"]
        try:
            req_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "X-Hermes-Token": config.get("hermes_auth_token", ""),
            }
            req = urllib.request.Request(endpoint, data=req_data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status in (200, 201, 202):
                    delivered = True
        except Exception:
            # Hermes might not be running yet, silent fallback
            pass

    # 3. Direct Zalo Bot Webhook (if configured)
    zalo_url = config.get("zalo_direct_webhook")
    if zalo_url:
        try:
            zalo_msg = (
                f"🤖 [Antigravity CLI] {event_type}\n"
                f"👤 Tài khoản: {account_id}\n"
                f"⏰ Thời gian: {now_iso}\n"
                f"📄 Chi tiết: {json.dumps(details or {}, ensure_ascii=False)}"
            )
            z_payload = json.dumps({"text": zalo_msg, "event": payload}).encode("utf-8")
            req = urllib.request.Request(
                zalo_url,
                data=z_payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=4):
                delivered = True
        except Exception:
            pass

    return delivered


if __name__ == "__main__":
    # Test script execution
    print("Testing Hermes Bridge...")
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        print(f"✅ Created default config at: {CONFIG_FILE}")

    res = send_hermes_event("TEST_PING", "demo-account", {"message": "Test ping from hermes_bridge.py"})
    print(f"Logged event. Check {LOGS_FILE}")
