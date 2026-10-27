from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from .storage import APP_DIR
from .runtime import status_path

def command(*args):
    return [sys.executable,*args] if getattr(sys,"frozen",False) else [sys.executable,str(Path(__file__).resolve().parents[1]/"app.py"),*args]

class WorkerManager:
    def __init__(self): self.processes={};self.pending={};self.closing=False
    def start(self, account):
        key=account["id"]
        process=self.processes.get(key)
        if process is not None and process.poll() is None:
            if process.stdin and process.stdin.closed:
                self.pending[key]=dict(account)
            return
        if self.closing:return
        status_path(key).unlink(missing_ok=True)
        folder=APP_DIR/"logs"
        folder.mkdir(parents=True,exist_ok=True)
        with open(folder/(key+".log"),"ab",buffering=0) as log:
            self.processes[key]=subprocess.Popen(command("--worker",key),stdin=subprocess.PIPE,stdout=log,stderr=log,
                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),env={**os.environ,"PYTHONUNBUFFERED":"1","PYTHONIOENCODING":"utf-8"})
    def stop(self, account_id):
        self.pending.pop(account_id,None)
        process=self.processes.get(account_id)
        if process and process.poll() is None and process.stdin:
            process.stdin.close()
    def poll(self):
        if self.closing:return
        for key,account in list(self.pending.items()):
            process=self.processes.get(key)
            if process is None or process.poll() is not None:
                self.pending.pop(key,None)
                self.start(account)
    def status(self, account_id):
        if account_id in self.pending:
            return {"state":"STOPPING","message":"Waiting for the previous worker to stop; the new Start choice is queued."}
        try:
            data=json.loads(status_path(account_id).read_text(encoding="utf-8"))
            process=self.processes.get(account_id)
            data["stale"]=time.time()-float(data.get("updated",0))>45
            if process is not None and process.poll() is not None and data.get("state") not in {"STOPPED","ACCESS_DISABLED"}:
                data.update(state="FAILED",message="Account worker exited; inspect local logs.")
            return data
        except (OSError,ValueError):
            return {"state":"STOPPED","message":"Automated trading is stopped."}
    def close(self):
        self.closing=True;self.pending.clear()
        for key in self.processes: self.stop(key)
        deadline=time.monotonic()+25
        for process in self.processes.values():
            if process.poll() is None:
                try: process.wait(timeout=max(.1,deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    # This worker never retries an uncertain submission after exit.
                    process.kill()
                    process.wait(timeout=10)
    def probe(self,path):
        APP_DIR.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix="azt-probe-",suffix=".json",dir=APP_DIR)
        os.close(fd)
        try:
            result=subprocess.run(command("--probe",path,name),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),timeout=20)
            if result.returncode: raise RuntimeError("MT5 detection did not complete.")
            data=json.loads(Path(name).read_text(encoding="utf-8"))
            if data.get("error"): raise RuntimeError(data["error"])
            return data
        finally: Path(name).unlink(missing_ok=True)
