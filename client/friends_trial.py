"""Installed AZT Friends trial: local cleanup only; owner server is the trading authority.

The server starts its 14-day entitlement on first successful MT5 pairing.
This module records that returned deadline and arranges a visible per-user
Windows scheduled task to uninstall this *edition* after expiry. It never
changes the MT5 installation, existing broker positions, or the execution ledger.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading

from .storage import APP_DIR, atomic_json

TASK_NAME = "AZT Friends Trial Expiry"
EDITION_EXE = "AZT_Friends_Trial.exe"
TRIAL_DAYS = 14
LEASE_PATH = APP_DIR / "friends_trial_lease.json"
_lock = threading.Lock()
_last_schedule_attempt = None


def is_friends_edition():
    return (os.name == "nt" and bool(getattr(sys, "frozen", False))
            and Path(sys.executable).name.lower() == EDITION_EXE.lower())


def utc_datetime(raw):
    value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Trial deadline lacks a UTC offset.")
    return value.astimezone(timezone.utc)


def _read_lease(path=LEASE_PATH):
    try:
        import json
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if value.get("edition") != "AZT_FRIENDS_14":
            return None
        expires = utc_datetime(value["expires_utc"])
        started = utc_datetime(value["activated_utc"])
        if expires - started != timedelta(days=TRIAL_DAYS):
            return None
        return value
    except (FileNotFoundError, OSError, ValueError, TypeError, KeyError):
        return None


def _scripts():
    folder = Path(sys.executable).resolve().parent
    return folder / "trial_schedule.ps1", folder / "trial_auto_uninstall.ps1", folder / "unins000.exe"


def _launch_powershell(script, *args, wait=False):
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
           "RemoteSigned", "-File", str(script), *map(str, args)]
    if wait:
        result = subprocess.run(cmd, timeout=45, **kwargs)
        return result.returncode == 0
    subprocess.Popen(cmd, **kwargs)
    return True


def _register_task():
    schedule, _cleanup, uninstaller = _scripts()
    if not schedule.is_file() or not uninstaller.is_file():
        logging.warning("AZT Friends edition is not installed by its setup executable; scheduled cleanup unavailable.")
        return False
    return _launch_powershell(schedule, "-Executable", str(Path(sys.executable).resolve()), wait=True)


def observe_subscription(subscription, *, now=None, path=LEASE_PATH, registrar=None):
    """Called only after authenticated owner /overview; never trusts a PC-issued lease."""
    global _last_schedule_attempt
    if not is_friends_edition() or not isinstance(subscription, dict):
        return False
    if subscription.get("access_kind") != "DISTRIBUTOR_TRIAL":
        return False
    if subscription.get("plan_code") != "DISTRIBUTOR_TRIAL":
        return False
    try:
        started = utc_datetime(subscription["starts_utc"])
        expires = utc_datetime(subscription["expires_utc"])
    except (KeyError, ValueError, TypeError):
        return False
    if expires - started != timedelta(days=TRIAL_DAYS):
        return False

    now = now or datetime.now(timezone.utc)
    with _lock:
        existing = _read_lease(path)
        if existing:
            old_expiry = utc_datetime(existing["expires_utc"])
            if old_expiry < expires:  # Refresh cannot reset a first activation.
                expires = old_expiry
                started = utc_datetime(existing["activated_utc"])
        record = {"edition": "AZT_FRIENDS_14", "activated_utc": started.isoformat(),
                  "expires_utc": expires.isoformat(),
                  "scheduler_registered": bool(existing and existing.get("scheduler_registered"))}
        if existing != record:
            atomic_json(path, record)
        if record["scheduler_registered"]:
            return True
        # Retry no more than once every 5 minutes if Windows Task Scheduler fails.
        if _last_schedule_attempt and now - _last_schedule_attempt < timedelta(minutes=5):
            return False
        _last_schedule_attempt = now
        registered = (registrar or _register_task)()
        if registered:
            record["scheduler_registered"] = True
            atomic_json(path, record)
        return registered


def local_trial_expired(*, now=None, path=LEASE_PATH):
    if not is_friends_edition():
        return False
    record = _read_lease(path)
    return bool(record and (now or datetime.now(timezone.utc)) >= utc_datetime(record["expires_utc"]))


def run_expiry_guard():
    """Scheduled every 30 minutes. Spawns cleanup after this EXE exits."""
    if not local_trial_expired():
        return 0
    _schedule, cleanup, uninstaller = _scripts()
    if not cleanup.is_file() or not uninstaller.is_file():
        logging.error("AZT Friends trial expired but the expected uninstaller is missing.")
        return 2
    try:
        _launch_powershell(cleanup, "-Uninstaller", str(uninstaller),
                           "-ClientExecutable", str(Path(sys.executable).resolve()))
        return 0
    except OSError:
        logging.exception("Could not launch AZT Friends trial uninstaller.")
        return 2
