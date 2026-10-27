"""Crash-safe execution claims. An uncertain submission is never re-executed."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time

class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS executions(account TEXT, signal_key TEXT, instruction_id INTEGER, state TEXT, message TEXT, acked INTEGER DEFAULT 0, updated REAL, PRIMARY KEY(account,signal_key))")

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally: con.close()

    def claim(self, account, key, instruction_id):
        with self.connect() as con:
            return con.execute("INSERT OR IGNORE INTO executions(account,signal_key,instruction_id,state,message,updated) VALUES(?,?,?,'SUBMITTING','Submission outcome requires review if interrupted',?)", (account,key,instruction_id,time.time())).rowcount == 1

    def finish(self, account, key, state, message):
        with self.connect() as con:
            con.execute("UPDATE executions SET state=?,message=?,updated=? WHERE account=? AND signal_key=?", (state,message,time.time(),account,key))

    def pending_acks(self, account):
        with self.connect() as con:
            return [dict(row) for row in con.execute("SELECT * FROM executions WHERE account=? AND acked=0", (account,))]

    def acknowledge(self, account, key):
        with self.connect() as con:
            con.execute("UPDATE executions SET acked=1,updated=? WHERE account=? AND signal_key=?", (time.time(),account,key))
