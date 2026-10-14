from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import ClientProfile


APP_DIR = Path.home() / ".gold_ai_client"
PROFILE_PATH = APP_DIR / "profile.json"


def load_profile() -> ClientProfile:
    if not PROFILE_PATH.exists():
        return ClientProfile()
    try:
        return ClientProfile(**json.loads(PROFILE_PATH.read_text(encoding="utf-8")))
    except Exception:
        return ClientProfile()


def save_profile(profile: ClientProfile) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(
        json.dumps(asdict(profile), indent=2),
        encoding="utf-8",
    )
