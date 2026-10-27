from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, fields
from pathlib import Path

from .models import ClientProfile


APP_DIR = Path(os.getenv("AZT_CLIENT_HOME", str(Path.home() / ".gold_ai_client")))
PROFILE_PATH = APP_DIR / "profile.json"
PUBLIC_SERVER_URL = "https://grandpa-skier-sphere.ngrok-free.dev"


def load_profile() -> ClientProfile:
    if not PROFILE_PATH.exists():
        return ClientProfile()
    try:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        profile = ClientProfile(**{key: value for key, value in data.items() if key in {f.name for f in fields(ClientProfile)}})
        if not str(profile.server_url).startswith(("https://", "http://")):
            profile.server_url = PUBLIC_SERVER_URL
        if not isinstance(profile.accounts, list):
            profile.accounts = []
        for account in profile.accounts:
            account["desired_running"] = desired_state(account.get("id", ""), account.get("desired_running", False))
        return profile
    except (OSError, ValueError, TypeError):
        return ClientProfile()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, allow_nan=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        for attempt in range(7):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == 6:
                    raise
                import time
                time.sleep(.025 * 2 ** attempt)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def save_profile(profile: ClientProfile) -> None:
    data=asdict(profile)
    for account in data.get("accounts",[]):
        account["desired_running"] = desired_state(account.get("id", ""), account.get("desired_running", False))
    atomic_json(PROFILE_PATH, data)

def _desired_path(account_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}",str(account_id)):
        raise ValueError("Invalid configured account identifier.")
    return PROFILE_PATH.parent / "desired" / (str(account_id)+".json")

def desired_state(account_id, fallback=False):
    try:
        value=json.loads(_desired_path(account_id).read_text(encoding="utf-8"))
        return value.get("enabled") is True
    except FileNotFoundError:
        return bool(fallback)
    except (OSError,ValueError,TypeError):
        return False  # A corrupt desired-state record cannot enable execution.

def set_desired_state(account_id, enabled):
    # Independent per-account records avoid a child safety stop overwriting the
    # UI's preferences or another account's concurrent Start/Stop choice.
    atomic_json(_desired_path(account_id),{"enabled":bool(enabled)})
