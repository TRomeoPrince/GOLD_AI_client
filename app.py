from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from client.api import GoldAIServer
from client.storage import load_profile, save_profile


class GoldAIClientApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GOLD_AI Client")
        self.geometry("560x470")
        self.resizable(False, False)
        self.profile = load_profile()
        self._build()

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

        self.server = self._row(form, "Server", self.profile.server_url)
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
            text="If enabled: save, then send /start to the GOLD_AI Telegram bot.",
        ).pack(anchor="w")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=18)
        ttk.Button(buttons, text="Save", command=self.save).pack(side="left")
        ttk.Button(buttons, text="Connect / Authorize", command=self.authorize).pack(side="left", padx=8)

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
            if result.display_name:
                self.profile.display_name = result.display_name
                save_profile(self.profile)
            self.status.set(
                f"AUTHORIZED • {result.display_name or 'Client'} • {result.status}\n{result.message}"
            )
        else:
            self.status.set(f"NOT AUTHORIZED • {result.status}\n{result.message}")
            messagebox.showwarning("GOLD_AI", self.status.get())


if __name__ == "__main__":
    GoldAIClientApp().mainloop()
