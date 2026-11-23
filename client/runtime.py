"""One hidden process owns one MT5 terminal. Network recovery never replays orders."""
from __future__ import annotations
import ctypes
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import sys
import threading
import time
import MetaTrader5 as mt5
from .api import ClientAccessRevoked, SessionExpired, GoldAIServer, for_account
from .clock import BrokerClock, _clocks
from .executor import execute_instruction
from .ledger import Ledger
from .storage import APP_DIR, atomic_json, load_profile, set_desired_state
from .symbols import resolve_symbol

class SafetyStop(RuntimeError): pass
class MT5Disconnected(RuntimeError): pass
class SkipInstruction(ValueError): pass

def utc_now(): return datetime.now(timezone.utc).isoformat()

def epoch(value):
    if isinstance(value, (int,float)):
        result=float(value)
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None: raise ValueError("Signal timestamp must include UTC offset.")
        result=dt.timestamp()
    if not math.isfinite(result):raise ValueError("Signal timestamp must be finite.")
    return result

def validate_signal(payload, *, now=None):
    now = time.time() if now is None else now
    if not math.isfinite(float(now)):raise ValueError("Current UTC timestamp must be finite.")
    age = now - epoch(payload["setup_time"])
    if age < -60 or age > 20 * 60:
        raise ValueError("Signal outside its permitted age (20 minutes / 60 seconds future).")


def validate_risk_policy(data):
    """Accept only the current, complete owner risk-policy response."""
    if not isinstance(data, dict):
        raise ValueError("Risk policy response must be an object.")
    policy = {}
    for field in ("news_lock", "daily_profit_target_enabled"):
        value = data.get(field)
        if type(value) is not bool:
            raise ValueError(f"Risk policy has an invalid {field}.")
        policy[field] = value
    for field in ("risk_per_trade_pct", "max_open_risk_pct", "max_daily_loss_pct",
                  "max_single_risk_pct", "daily_profit_target_pct"):
        value = data.get(field)
        allow_zero = field == "daily_profit_target_pct" and not policy["daily_profit_target_enabled"]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
            raise ValueError(f"Risk policy has an invalid {field}.")
        policy[field] = float(value)
    return policy

def account_key(account): return f"{account['mt5_server']}|{int(account['mt5_login'])}"
def status_path(account_id): return APP_DIR / "runtime" / (str(account_id) + ".json")
def account_lock_path(account):
    # Preserve the legacy owner lock namespace so personal/hosted/client routes
    # on this Windows machine cannot execute the same broker account together.
    root=Path(os.getenv("LOCALAPPDATA",str(Path.home())))/"GOLD_AI"/"personal_locks"
    return root/(hashlib.sha256(account_key(account).encode()).hexdigest()+".lock")

def connection_account(account, *, trading=False):
    info, terminal = mt5.account_info(), mt5.terminal_info()
    if info is None or terminal is None or not getattr(terminal,"connected",False):
        raise MT5Disconnected("MT5 is disconnected; reconnecting automatically.")
    if int(info.login) != int(account["mt5_login"]) or str(info.server) != str(account["mt5_server"]):
        raise SafetyStop("MT5 account changed. Select the intended account before starting again.")
    if trading and (not getattr(terminal,"trade_allowed",False) or getattr(terminal,"tradeapi_disabled",False)
                    or not getattr(info,"trade_allowed",False) or not getattr(info,"trade_expert",False)):
        raise SafetyStop("Enable Algo Trading and Python API trading on the selected MT5 account.")
    return info

def snapshot(account, clock):
    connection_account(account)
    from .telemetry import capture_mt5
    return capture_mt5(mt5, clock_offset_seconds=clock.offset_seconds)


class ClientRuntime:
    def __init__(self, profile, account, stop, *, api=None, ledger=None, report=None):
        self.profile,self.account,self.stop=profile,account,stop
        self.api=api or GoldAIServer(for_account(profile,account))
        self.ledger=ledger or Ledger(APP_DIR/"execution_ledger.db")
        self.report=report or self.write_status
        self.token=""
        self.since=time.time()
        self.clock=None
        self.key=account_key(account)
        self.failures=0
        self.last_telemetry=0
        self.last_alert=0
        self.had_failure=False

    def write_status(self, **values):
        try: atomic_json(status_path(self.account["id"]), {"updated":time.time(),"desired":True,**values})
        except OSError as exc: logging.warning("Runtime status unavailable (%s)",type(exc).__name__)

    def reset_cutoff(self): self.since=time.time()

    def flush_acks(self):
        for row in self.ledger.pending_acks(self.key):
            state="ERROR_REVIEW" if row["state"]=="SUBMITTING" else row["state"]
            if row["state"]=="SUBMITTING":
                self.ledger.finish(self.key,row["signal_key"],state,row["message"])
            try:
                self.api.acknowledge(self.token,row["instruction_id"],state,row["message"])
            except ValueError as exc:
                # Non-retriable HTTP 4xx, such as an old server's 404. Do not
                # hold this account hostage or ever resubmit its execution.
                if self.ledger.fail_ack(self.key,row["signal_key"],str(exc)):
                    self.report(state="ACK_REVIEW",server_state="CONNECTED",
                                message=f"ACK dead-lettered after repeated rejection: {exc}")
                continue
            self.ledger.acknowledge(self.key,row["signal_key"])

    def process(self,data):
        payload=data.get("payload") or {}
        instruction_id=int(data["instruction_id"])
        key=str(data.get("signal_key") or f"instruction:{instruction_id}")
        if not self.ledger.claim(self.key,key,instruction_id):
            self.flush_acks()
            return
        try:
            if epoch(data.get("created_utc",payload.get("setup_time",0))) < self.since:
                raise ValueError("Backlog instruction skipped after start/reconnect.")
            if str(payload.get("kind","")).upper()=="TEST":
                state,message="TEST_OK",str(payload.get("message","AZT link test received."))
            else:
                validate_signal(payload)
                connection_account(self.account,trading=True)
                policy=validate_risk_policy(self.api.risk_policy(self.token))
                if policy["news_lock"]: raise ValueError("News Lock blocks new entries.")
                def guard():
                    if self.stop.is_set(): raise SafetyStop("Trading was stopped before submission.")
                    connection_account(self.account,trading=True)
                    validate_signal(payload)
                    latest=validate_risk_policy(self.api.risk_policy(self.token))
                    if latest["news_lock"]: raise SkipInstruction("News Lock enabled before submission.")
                    if latest != policy:
                        raise SkipInstruction("Risk policy changed; instruction skipped before submission.")
                    # Stop/account changes can arrive while the final HTTP check
                    # is in flight. Recheck after it, immediately before IPC send.
                    if self.stop.is_set(): raise SafetyStop("Trading was stopped before submission.")
                    connection_account(self.account,trading=True)
                    validate_signal(payload)
                result=execute_instruction(payload,policy["risk_per_trade_pct"],
                    min(40,policy["max_open_risk_pct"]),min(10,policy["max_daily_loss_pct"]),
                    policy["daily_profit_target_enabled"],policy["daily_profit_target_pct"],
                    max_single_risk_pct=min(2,policy["max_single_risk_pct"]),before_send=guard,
                    include_all_positions=True,strict_history=True)
                state="EXECUTED" if result.sent else "REJECTED"
                message=f"{result.message}; ticket={result.ticket}; volume={result.volume}; risk={result.planned_risk_pct:.3f}%"
        except (ValueError,ClientAccessRevoked) as exc:
            state,message="SKIPPED",str(exc)
        except SafetyStop as exc:
            self.ledger.finish(self.key,key,"ERROR_REVIEW",str(exc))
            raise
        except Exception as exc:
            # Includes ambiguous IPC/submission errors. Persist before any ACK retry.
            state,message="ERROR_REVIEW",str(exc)
        self.ledger.finish(self.key,key,state,message)
        self.report(state="CONNECTED",server_state="CONNECTED",mt5_state="CONNECTED",message=f"{state}: {message}")
        self.flush_acks()

    def run(self):
        try:
            while not self.stop.is_set():
                try:
                    if self.clock is None:
                        mt5.shutdown()
                        _clocks.clear()
                        path=str(self.account.get("terminal_path","")).strip()
                        if not path or not Path(path).is_file(): raise SafetyStop("Select the installed MT5 terminal for this account.")
                        if not mt5.initialize(path,timeout=10000): raise MT5Disconnected("Could not attach selected MT5 terminal.")
                        connection_account(self.account)
                        self.clock=BrokerClock.detect(mt5,resolve_symbol(mt5,"GOLD"))
                        self.reset_cutoff()
                    new_session = not self.token or self.had_failure
                    if new_session:
                        authorization=self.api.authorize()
                        self.token=authorization.session_token
                        if authorization.allowed is not True: raise ClientAccessRevoked(authorization.message)
                        if not self.token: raise ClientAccessRevoked("Server returned no authorized session.")
                    connection_account(self.account)
                    self.flush_acks()
                    if self.stop.is_set():
                        break
                    if new_session:
                        # Only fetch after authorization and ACK recovery confirm
                        # connectivity. The owner reserves an available delivery,
                        # so a received response must reach the normal claim path.
                        self.reset_cutoff()
                    data=self.api.next_instruction(self.token,datetime.fromtimestamp(self.since,timezone.utc).isoformat())
                    if self.had_failure:
                        self.report(state="RECOVERED",server_state="RECOVERED",mt5_state="CONNECTED",message="Connection recovered. Old queued trades will not be executed.")
                        self.had_failure=False
                    self.failures=0
                    if data.get("available"): self.process(data)
                    if time.time()-self.last_telemetry>=15:
                        self.api.telemetry(self.token,snapshot(self.account,self.clock))
                        self.last_telemetry=time.time()
                    reason = str(data.get("blocked_reason") or "")
                    if reason:
                        self.report(state="NEWS_BLOCKED",server_state="CONNECTED",mt5_state="CONNECTED",message=reason)
                    else:
                        self.report(state="CONNECTED",server_state="CONNECTED",mt5_state="CONNECTED",message="Waiting for fresh AZT signals.")
                    self.stop.wait(0.25)
                except (ClientAccessRevoked,SafetyStop) as exc:
                    set_desired_state(self.account["id"],False)
                    self.report(state="ACCESS_DISABLED",server_state="CONNECTED",mt5_state="BLOCKED",desired=False,message=str(exc))
                    return
                except Exception as exc:
                    if isinstance(exc,SessionExpired):
                        self.token=""
                    self.failures+=1
                    self.had_failure=True
                    self.reset_cutoff()
                    if isinstance(exc,MT5Disconnected): self.clock=None
                    threshold=max(1,int(self.profile.retries_before_alert))
                    state="DEGRADED" if self.failures>=threshold else "RECONNECTING"
                    delay=min(max(1,float(self.profile.retry_interval))*2**min(self.failures-1,5),max(1,float(self.profile.retry_cap)))
                    alert=""
                    if self.failures>=threshold and time.time()-self.last_alert>=self.profile.alert_cooldown:
                        alert="Connection needs attention; retries remain enabled. "
                        self.last_alert=time.time()
                    self.report(state=state,server_state=state,mt5_state="RECONNECTING" if self.clock is None else "CONNECTED",
                                message=alert+str(exc)[:500]+f" Retry in {delay:g}s.",retry_in=delay)
                    self.stop.wait(delay)
        finally:
            mt5.shutdown()
            if self.stop.is_set(): self.report(state="STOPPED",desired=False,message="Trading stopped. Broker positions remain open.")

def watch_parent(stop):
    if os.name=="nt":
        import msvcrt
        kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel.PeekNamedPipe.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong),ctypes.c_void_p]
        handle=msvcrt.get_osfhandle(sys.stdin.fileno())
        available=ctypes.c_ulong()
        while not stop.wait(.2):
            if not kernel.PeekNamedPipe(handle,None,0,None,ctypes.byref(available),None) or available.value:
                stop.set();return
    else:
        sys.stdin.buffer.read(1);stop.set()

def worker(account_id):
    APP_DIR.mkdir(parents=True,exist_ok=True)
    log=APP_DIR/"logs"/(account_id+".log")
    log.parent.mkdir(exist_ok=True)
    if getattr(sys,"frozen",False):
        import msvcrt
        kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel.GetStdHandle.restype=ctypes.c_void_p
        sys.stdin=os.fdopen(msvcrt.open_osfhandle(kernel.GetStdHandle(-10),os.O_RDONLY),"r")
        sys.stdout=sys.stderr=open(log,"a",encoding="utf-8",buffering=1)
    stop=threading.Event()
    threading.Thread(target=watch_parent,args=(stop,),daemon=True).start()
    profile=load_profile()
    account=next((row for row in profile.accounts if row["id"]==account_id),None)
    if not account: raise ValueError("Configured account not found.")
    if not account.get("desired_running"):
        atomic_json(status_path(account_id),{"updated":time.time(),"desired":False,"state":"STOPPED","message":"Automated trading is disabled for this account."})
        return
    # The OS lock is shared across client installations to prevent two execution routes.
    import msvcrt
    lock_path=account_lock_path(account)
    lock_path.parent.mkdir(parents=True,exist_ok=True)
    with open(lock_path,"a+b") as lock:
        lock.seek(0)
        try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            set_desired_state(account_id,False)
            atomic_json(status_path(account_id),{"updated":time.time(),"desired":False,"state":"ACCESS_DISABLED","message":"Another AZT client is already executing this MT5 account."})
            return
        ClientRuntime(profile,account,stop).run()

def probe(terminal_path, destination):
    try:
        if not mt5.initialize(terminal_path,timeout=10000): raise RuntimeError("Open and log in to the selected MT5 terminal.")
        info,terminal=mt5.account_info(),mt5.terminal_info()
        if info is None or terminal is None: raise RuntimeError("No logged-in account detected.")
        result={"mt5_login":int(info.login),"mt5_server":str(info.server),"terminal_path":terminal_path,"balance":float(info.balance),"currency":str(info.currency)}
    except Exception as exc: result={"error":str(exc)}
    finally: mt5.shutdown()
    atomic_json(Path(destination),result)
