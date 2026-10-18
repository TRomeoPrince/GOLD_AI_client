from __future__ import annotations

import tkinter as tk
import threading
import time
from tkinter import messagebox, ttk

import MetaTrader5 as mt5

from client.api import ClientAccessRevoked, GoldAIServer
from client.executor import execute_instruction
from client.storage import PUBLIC_SERVER_URL, load_profile, save_profile



def enable_windows_dpi_awareness():
    """Render text at the display DPI instead of letting Windows stretch a bitmap."""
    import os
    if os.name != "nt":
        return
    import ctypes
    try:
        # System-aware mode works consistently with Tk's point-based fonts.
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def apply_theme(root):
    from tkinter import font
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        font.nametofont(name).configure(family="Segoe UI", size=10, weight="normal")
    root.configure(background="#F4F7F6")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background="#F4F7F6", foreground="#172D35", font="TkDefaultFont")
    style.configure("TFrame", background="#F4F7F6")
    style.configure("TLabel", background="#F4F7F6", foreground="#172D35")
    style.configure("Muted.TLabel", foreground="#60746B")
    style.configure("Title.TLabel", font=("Segoe UI", 18), foreground="#172D35")
    style.configure("Card.TFrame", background="#FFFFFF")
    style.configure("Card.TLabel", background="#FFFFFF", foreground="#172D35")
    style.configure("Section.TLabel", background="#FFFFFF", font=("Segoe UI", 10, "bold"))
    style.configure("TButton", padding=(12, 7), background="#E3ECE7", foreground="#254D3F", borderwidth=0)
    style.map("TButton", background=[("active", "#D2E5DC")], foreground=[("disabled", "#73837B")])
    style.configure("Accent.TButton", background="#176B53", foreground="#FFFFFF")
    style.map("Accent.TButton", background=[("active", "#11533F"), ("disabled", "#CBD7D0")])
    style.configure("TEntry", fieldbackground="#FFFFFF", padding=6)
    style.configure("TCheckbutton", background="#F4F7F6", padding=0)


class GoldAIClientApp(tk.Tk):
    def __init__(self):
        enable_windows_dpi_awareness()
        super().__init__()
        self.title("GOLD_AI Client")
        self.ui_scale = float(self.tk.call("tk", "scaling")) / (96 / 72)
        self.window_width = min(self._px(560), self.winfo_screenwidth() - 60)
        window_height = min(self._px(650), self.winfo_screenheight() - 100)
        self.geometry(f"{self.window_width}x{window_height}")
        self.minsize(self.window_width, min(self._px(400), window_height))
        self.maxsize(self.window_width, self.winfo_screenheight() - 80)
        self.resizable(False, True)
        self.profile = load_profile()
        self.profile.server_url = PUBLIC_SERVER_URL
        self.session_token = ""
        self._worker_stop = threading.Event()
        self._worker_thread = None
        apply_theme(self)
        self._build()
        self.after(250, self.detect_mt5)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _px(self, value):
        return max(1, round(value * self.ui_scale))

    def _build(self):
        # A narrow, scrollable page keeps every control usable on small displays.
        shell = ttk.Frame(self)
        shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(shell, background="#F4F7F6", highlightthickness=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        frame = ttk.Frame(canvas, padding=self._px(20))
        page = canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(page, width=event.width))
        self.bind("<MouseWheel>", lambda event: canvas.yview_scroll(-int(event.delta / 120), "units"))
        self.page_canvas = canvas

        ttk.Label(frame, text="GOLD_AI", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text="MT5 client", style="Muted.TLabel").pack(anchor="w", pady=(2, self._px(18)))

        form = ttk.Frame(frame, style="Card.TFrame", padding=self._px(16))
        form.pack(fill="x")
        ttk.Label(form, text="Account", style="Section.TLabel").pack(anchor="w", pady=(0, self._px(8)))
        self.pairing = self._row(form, "Pairing code", self.profile.pairing_code)
        self.mt5_login = self._row(form, "MT5 login", "" if self.profile.mt5_login is None else str(self.profile.mt5_login))
        self.mt5_server = self._row(form, "MT5 server", self.profile.mt5_server)
        self.telegram = self._row(form, "Telegram username", self.profile.telegram_username)

        self.telegram_enabled = tk.BooleanVar(value=self.profile.telegram_enabled)
        ttk.Checkbutton(frame, text="Telegram notifications (optional)", variable=self.telegram_enabled).pack(anchor="w", pady=(self._px(16), 4))
        ttk.Label(frame, text="Save, then send /start to @Princetradingbot.", style="Muted.TLabel", wraplength=self._px(460)).pack(anchor="w")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=self._px(16))
        ttk.Button(buttons, text="Detect MT5", command=self.detect_mt5).pack(side="left")
        ttk.Button(buttons, text="Save", command=self.save).pack(side="left", padx=self._px(8))
        ttk.Button(buttons, text="Connect", style="Accent.TButton", command=self.authorize).pack(side="right")

        self.status = tk.StringVar(value="Not connected")
        status_card = ttk.Frame(frame, style="Card.TFrame", padding=self._px(16))
        status_card.pack(fill="x")
        status_heading = ttk.Frame(status_card, style="Card.TFrame")
        status_heading.pack(fill="x", pady=(0, self._px(8)))
        self.status_dot = tk.Canvas(status_heading, width=self._px(12), height=self._px(12), background="#FFFFFF", highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, self._px(7)))
        self.status_dot.create_oval(2, 2, self._px(10), self._px(10), fill="#73837B", outline="", tags="dot")
        self.status_caption = tk.StringVar(value="Not connected")
        ttk.Label(status_heading, textvariable=self.status_caption, style="Section.TLabel").pack(side="left")
        ttk.Label(status_card, textvariable=self.status, style="Card.TLabel", wraplength=self._px(440), justify="left").pack(anchor="w")
        self.status.trace_add("write", self._update_status_indicator)

        ttk.Label(frame, text="Keep MT5 open with Algo Trading enabled.", style="Muted.TLabel", wraplength=self._px(460)).pack(anchor="w", pady=(self._px(14), 0))
        ttk.Label(frame, text="Broker-side SL/TP remain in place when this app closes.", style="Muted.TLabel", wraplength=self._px(460)).pack(anchor="w", pady=(4, 0))
        self.update_idletasks()

    def _row(self, parent, label, value):
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=self._px(5))
        ttk.Label(row, text=label, style="Card.TLabel", width=19).pack(side="left")
        var = tk.StringVar(value=value)
        ttk.Entry(row, textvariable=var, width=20).pack(side="left", fill="x", expand=True)
        return var

    def _update_status_indicator(self, *_args):
        # Read the existing status; never infer server access from MT5 detection.
        text = self.status.get()
        if text.startswith(("AUTHORIZED", "EXECUTED", "TEST_OK")):
            label, color = "Connected", "#176B53"
        elif text.startswith(("NOT AUTHORIZED", "ACCESS DISABLED", "REJECTED")):
            label, color = "Needs attention", "#9B2525"
        elif text.startswith("REMOTE LINK ERROR"):
            label, color = "Reconnecting", "#8A5B0A"
        elif text.startswith("MT5 DETECTED"):
            label, color = "MT5 detected", "#73837B"
        else:
            label, color = "Status", "#73837B"
        self.status_caption.set(label)
        self.status_dot.itemconfigure("dot", fill=color)

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

                if str(payload.get("kind", "")).upper() == "TEST":
                    ack_status = "TEST_OK"
                    ack_message = str(
                        payload.get("message", "Remote link test received.")
                    )
                else:
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
            except ClientAccessRevoked as exc:
                self.after(
                    0,
                    lambda err=str(exc): self.status.set(
                        f"ACCESS DISABLED\n{err}\nNo new GOLD_AI trades will be accepted."
                    ),
                )
                self.session_token = ""
                self._worker_stop.set()
                return
            except Exception as exc:
                self.after(
                    0,
                    lambda err=str(exc): self.status.set(
                        f"REMOTE LINK ERROR\n{err}\nRetrying..."
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
        self.profile.server_url = PUBLIC_SERVER_URL
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
