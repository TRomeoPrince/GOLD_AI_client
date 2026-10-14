from __future__ import annotations

import tkinter as tk
import threading
import time
from tkinter import messagebox, ttk

import MetaTrader5 as mt5

from client.api import GoldAIServer
from client.executor import execute_instruction
from client.storage import load_profile, save_profile


class GoldAIClientApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GOLD_AI Client")
        self.geometry("560x470")
        self.resizable(False, False)
        self.profile = load_profile()
        self.session_token = ""
        self._worker_stop = threading.Event()
        self._worker_thread = None
        self._build()
        self.after(250, self.detect_mt5)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build(self):
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="GOLD_AI", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="Thin execution client — strategy logic remains on the owner server.",
        ).pack(anchor="w", pady=(0, 18))

        form = ttk.Frame(frame)
        form.pack(fill="x")

        self.server = self._row(form, "Server URL", self.profile.server_url)
        self.pairing = self._row(form, "Pairing code", self.profile.pairing_code)
        self.mt5_login = self._row(
            form, "MT5 login", "" if self.profile.mt5_login is None else str(self.profile.mt5_login)
        )
        self.mt5_server = self._row(form, "MT5 server", self.profile.mt5_server)
        self.telegram = self._row(form, "Telegram @username (optional)", self.profile.telegram_username)

        self.telegram_enabled = tk.BooleanVar(value=self.profile.telegram_enabled)
        ttk.Checkbutton(
            frame,
            text="Enable Telegram trade notifications",
            variable=self.telegram_enabled,
        ).pack(anchor="w", pady=(14, 2))
        ttk.Label(
            frame,
            text="If enabled: save, then send /start to @Princetradingbot.",
        ).pack(anchor="w")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=18)
        ttk.Button(buttons, text="Detect MT5", command=self.detect_mt5).pack(side="left")
        ttk.Button(buttons, text="Save", command=self.save).pack(side="left", padx=8)
        ttk.Button(buttons, text="Connect / Authorize", command=self.authorize).pack(side="left")

        self.status = tk.StringVar(value="Not connected")
        ttk.Separator(frame).pack(fill="x", pady=8)
        ttk.Label(frame, textvariable=self.status, wraplength=500).pack(anchor="w", pady=8)

    def _row(self, parent, label, value):
        wrap = ttk.Frame(parent)
        wrap.pack(fill="x", pady=5)
        ttk.Label(wrap, text=label, width=26).pack(side="left")
        var = tk.StringVar(value=value)
        ttk.Entry(wrap, textvariable=var, width=38).pack(side="left", fill="x", expand=True)
        return var

    def detect_mt5(self):
        if not mt5.initialize():
            code, message = mt5.last_error()
            self.status.set(
                f"MT5 not detected. Open MetaTrader 5 and log in first. ({code}: {message})"
            )
            return

        account = mt5.account_info()
        if account is None:
            self.status.set("MT5 is open, but no logged-in account was detected.")
            return

        self.mt5_login.set(str(account.login))
        self.mt5_server.set(str(account.server))
        self.status.set(
            f"MT5 DETECTED • {account.login} @ {account.server}\n"
            f"Balance: {account.balance:.2f} {account.currency}"
        )

    def start_instruction_worker(self):
        if self._worker_thread and self._worker_thread.is_alive():
            return
        if not self.session_token:
            return

        self._worker_stop.clear()
        self._worker_thread = threading.Thread(
            target=self._instruction_loop,
            name="gold-ai-instruction-worker",
            daemon=True,
        )
        self._worker_thread.start()

    def _instruction_loop(self):
        api = GoldAIServer(self.profile)
        while not self._worker_stop.is_set():
            try:
                data = api.next_instruction(self.session_token)
                if not data.get("available"):
                    time.sleep(2)
                    continue

                instruction_id = int(data.get("instruction_id", 0))
                payload = data.get("payload") or {}

                result = execute_instruction(payload)
                ack_status = "EXECUTED" if result.sent else "REJECTED"
                ack_message = (
                    f"{result.message} | ticket={result.ticket or '-'} "
                    f"| volume={result.volume} "
                    f"| risk={result.planned_risk_pct:.3f}% "
                    f"| portfolio_after={result.portfolio_after_pct:.3f}%"
                )
                api.acknowledge(
                    self.session_token,
                    instruction_id,
                    ack_status,
                    ack_message,
                )

                self.after(
                    0,
                    lambda text=(
                        f"{ack_status} • {payload.get('strategy_id','REMOTE')} "
                        f"{payload.get('direction','')}\n{ack_message}"
                    ): self.status.set(text),
                )
            except Exception as exc:
                self.after(
                    0,
                    lambda err=str(exc): self.status.set(
                        f"REMOTE LINK ERROR\n{err}"
                    ),
                )
                time.sleep(3)

    def on_close(self):
        self._worker_stop.set()
        try:
            mt5.shutdown()
        except Exception:
            pass
        self.destroy()

    def save(self):
        self.profile.server_url = self.server.get().strip()
        self.profile.pairing_code = self.pairing.get().strip()
        self.profile.mt5_server = self.mt5_server.get().strip()
        self.profile.telegram_username = self.telegram.get().strip().lstrip("@")
        self.profile.telegram_enabled = bool(self.telegram_enabled.get())
        raw_login = self.mt5_login.get().strip()
        self.profile.mt5_login = int(raw_login) if raw_login.isdigit() else None
        save_profile(self.profile)
        self.status.set("Settings saved.")

    def authorize(self):
        self.save()
        result = GoldAIServer(self.profile).authorize()
        if result.allowed:
            self.session_token = result.session_token
            if result.display_name:
                self.profile.display_name = result.display_name
                save_profile(self.profile)
            self.status.set(
                f"AUTHORIZED • {result.display_name or 'Client'} • {result.status}\n"
                f"MT5: {self.profile.mt5_login} @ {self.profile.mt5_server}\n"
                f"{result.message}\nListening for GOLD_AI instructions..."
            )
            self.start_instruction_worker()
        else:
            self.status.set(f"NOT AUTHORIZED • {result.status}\n{result.message}")
            messagebox.showwarning("GOLD_AI", self.status.get())


if __name__ == "__main__":
    GoldAIClientApp().mainloop()
