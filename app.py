"""AGORA ZION TRADER customer workspace and isolated MT5 worker entry point."""
from __future__ import annotations
import base64
from datetime import datetime
import json
import math
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from uuid import uuid4
from PIL import Image, ImageEnhance, ImageOps, ImageTk
from client.api import GoldAIServer, for_account
from client.manager import WorkerManager
from client.storage import APP_DIR, PUBLIC_SERVER_URL, load_profile, save_profile, set_desired_state
from client.timezones import CHOICES, display_time, remaining_text, valid_zone
from client.friends_trial import is_friends_edition, observe_subscription, local_trial_expired, run_expiry_guard

BG="#08131f"; PANEL="#101f2c"; PANEL2="#172a38"; GOLD="#e8bd67"; TEXT="#edf3ee"; MUTED="#9eaea9"; GREEN="#6ed6ac"; RED="#fa8586"

def asset(name): return Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent))/"assets"/name

class ScrollPage(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent,style="Page.TFrame")
        self.canvas=tk.Canvas(self,bg=BG,highlightthickness=0)
        bar=ttk.Scrollbar(self,orient="vertical",command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right",fill="y"); self.canvas.pack(side="left",fill="both",expand=True)
        self.body=ttk.Frame(self.canvas,style="Page.TFrame",padding=20)
        self.window=self.canvas.create_window((0,0),window=self.body,anchor="nw")
        self.body.bind("<Configure>",lambda _event:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",lambda event:self.canvas.itemconfigure(self.window,width=event.width))
        self.canvas.bind("<Enter>",lambda _event:self.canvas.bind_all("<MouseWheel>",self.wheel))
        self.canvas.bind("<Leave>",lambda _event:self.canvas.unbind_all("<MouseWheel>"))
    def wheel(self,event): self.canvas.yview_scroll(int(-event.delta/120),"units")

def table(parent,columns,height=9):
    frame=ttk.Frame(parent,style="Panel.TFrame")
    frame.pack(fill="both",expand=True,pady=8)
    frame.columnconfigure(0,weight=1);frame.rowconfigure(0,weight=1)
    tree=ttk.Treeview(frame,columns=[item[0] for item in columns],show="headings",height=height)
    for key,label,width in columns:
        tree.heading(key,text=label);tree.column(key,width=width,minwidth=70,stretch=True)
    vertical=ttk.Scrollbar(frame,orient="vertical",command=tree.yview)
    horizontal=ttk.Scrollbar(frame,orient="horizontal",command=tree.xview)
    tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
    tree.grid(row=0,column=0,sticky="nsew");vertical.grid(row=0,column=1,sticky="ns");horizontal.grid(row=1,column=0,sticky="ew")
    tree.tag_configure("profit",foreground=GREEN);tree.tag_configure("loss",foreground=RED)
    return tree

class GoldAIClientApp(tk.Tk):
    def __init__(self,*,smoke=False):
        super().__init__()
        self.title("AGORA ZION TRADER • Friends Trial (14 days)" if is_friends_edition() else "AGORA ZION TRADER • Client")
        self.geometry("1280x800")
        self.minsize(min(1000,self.winfo_screenwidth()-80),min(700,self.winfo_screenheight()-100))
        self.resizable(True,True)
        self.configure(bg=BG)
        try:self.state("zoomed")
        except tk.TclError:pass
        self.smoke=smoke;self.profile=load_profile();self.manager=WorkerManager()
        self.session_token="";self.busy=False;self.closing=False;self.callbacks=queue.Queue()
        self.selected_id="";self.overview_data={};self.trades_data={};self.messages_data=[];self.plans_data=[];self.methods_data=[]
        self.proof_data="";self.proof_label=tk.StringVar(value="No screenshot selected")
        self.status=tk.StringVar(value="Welcome to AZT. Connect your account to begin.")
        self.metrics={};self.page_name=tk.StringVar(value="Dashboard")
        self._build()
        self.protocol("WM_DELETE_WINDOW",self.on_close)
        self.after(100,self._callbacks)
        self.after(500,self._runtime_tick)
        self.after(15000,self._periodic)
        if not smoke:
            for account in self.profile.accounts:
                if account.get("desired_running"):
                    self.manager.start(account)
            if self.profile.pairing_code and self.profile.accounts:self.after(600,self.connect)

    def _styles(self):
        s=ttk.Style(self);s.theme_use("clam")
        s.configure(".",background=PANEL,foreground=TEXT,font=("Segoe UI",10),borderwidth=0)
        s.configure("Page.TFrame",background=BG);s.configure("Panel.TFrame",background=PANEL)
        s.configure("Panel.TLabel",background=PANEL,foreground=TEXT)
        s.configure("Muted.TLabel",background=PANEL,foreground=MUTED)
        s.configure("Title.TLabel",background=BG,foreground=TEXT,font=("Segoe UI",25,"bold"))
        s.configure("Section.TLabel",background=PANEL,foreground=GOLD,font=("Segoe UI",13,"bold"))
        s.configure("Metric.TLabel",background=PANEL,foreground=TEXT,font=("Segoe UI",18,"bold"))
        s.configure("TButton",background=PANEL2,foreground=TEXT,padding=(14,9),borderwidth=0)
        s.map("TButton",background=[("active","#284354"),("disabled",PANEL)])
        s.configure("Gold.TButton",background=GOLD,foreground=BG,font=("Segoe UI",10,"bold"))
        s.map("Gold.TButton",background=[("active","#ffda90")])
        s.configure("Stop.TButton",background="#492b35",foreground=RED)
        s.configure("TEntry",fieldbackground="#0a1824",foreground=TEXT,insertcolor=TEXT,padding=7)
        s.configure("TCombobox",fieldbackground="#0a1824",foreground=TEXT,arrowcolor=GOLD,padding=5)
        s.map("TCombobox",fieldbackground=[("readonly","#0a1824")],foreground=[("readonly",TEXT)])
        s.configure("Treeview",background=PANEL,fieldbackground=PANEL,foreground=TEXT,rowheight=32,borderwidth=0)
        s.map("Treeview",background=[("selected","#35534e")],foreground=[("selected",TEXT)])
        s.configure("Treeview.Heading",background=PANEL2,foreground=GOLD,padding=8)
        s.configure("TNotebook",background=PANEL);s.configure("TNotebook.Tab",padding=(16,9),background=PANEL2,foreground=TEXT)
        s.map("TNotebook.Tab",background=[("selected","#35534e")])

    def _build(self):
        self._styles()
        self.background=tk.Canvas(self,bg=BG,highlightthickness=0)
        self.background.place(x=0,y=0,relwidth=1,relheight=1)
        self.original_bg=Image.open(asset("BACKGROUND.jpg")).convert("RGB")
        self.bind("<Configure>",self._background_resize)
        self.columnconfigure(1,weight=1);self.rowconfigure(0,weight=1)
        sidebar=tk.Frame(self,bg="#0b1924",width=180,padx=18,pady=26)
        sidebar.grid(row=0,column=0,rowspan=2,sticky="nsew");sidebar.grid_propagate(False)
        tk.Label(sidebar,text="AZT",bg="#0b1924",fg=GOLD,font=("Segoe UI",30,"bold")).pack(anchor="w")
        tk.Label(sidebar,text="AGORA ZION\nTRADER",bg="#0b1924",fg=TEXT,font=("Segoe UI",11,"bold"),justify="left").pack(anchor="w",pady=(0,32))
        self.nav_buttons={}
        for name in ("Dashboard","Trades","Journal","Referrals","Payments"):
            button=tk.Button(sidebar,text=name,command=lambda page=name:self.show(page),anchor="w",relief="flat",bd=0,padx=12,pady=12,
                bg="#0b1924",fg=MUTED,activebackground=PANEL2,activeforeground=GOLD,font=("Segoe UI",11))
            button.pack(fill="x",pady=4);self.nav_buttons[name]=button
        tk.Label(sidebar,text="YOUR ACCOUNT\nYOUR CONTROL",bg="#0b1924",fg=MUTED,justify="left",font=("Segoe UI",8)).pack(side="bottom",anchor="w",pady=20)
        workspace=ttk.Frame(self,style="Page.TFrame");workspace.grid(row=0,column=1,sticky="nsew",padx=16,pady=(18,0))
        workspace.rowconfigure(1,weight=1);workspace.columnconfigure(0,weight=1)
        header=ttk.Frame(workspace,style="Page.TFrame",padding=(10,0,10,16));header.grid(row=0,column=0,sticky="ew")
        ttk.Label(header,textvariable=self.page_name,style="Title.TLabel").pack(side="left")
        ttk.Button(header,text="Refresh / Connect",command=self.connect).pack(side="right")
        self.pages={}
        container=ttk.Frame(workspace,style="Page.TFrame");container.grid(row=1,column=0,sticky="nsew");container.rowconfigure(0,weight=1);container.columnconfigure(0,weight=1)
        for name in self.nav_buttons:
            page=ScrollPage(container);page.grid(row=0,column=0,sticky="nsew");self.pages[name]=page
        self._dashboard(self.pages["Dashboard"].body)
        self._trades(self.pages["Trades"].body)
        self._journal(self.pages["Journal"].body)
        self._referrals(self.pages["Referrals"].body)
        self._payments(self.pages["Payments"].body)
        footer=ttk.Frame(self,style="Panel.TFrame",padding=(20,10));footer.grid(row=1,column=1,sticky="ew",padx=16,pady=12)
        footer.columnconfigure(0,weight=1)
        self.footer_status=ttk.Label(footer,textvariable=self.status,style="Muted.TLabel",wraplength=560)
        self.footer_status.grid(row=0,column=0,sticky="w")
        self.start_button=ttk.Button(footer,text="Start Automated Trading",style="Gold.TButton",command=self.start)
        self.start_button.grid(row=0,column=1,padx=(14,8))
        self.stop_button=ttk.Button(footer,text="Stop",style="Stop.TButton",command=self.stop)
        self.stop_button.grid(row=0,column=2)
        footer.bind("<Configure>",lambda e:self.footer_status.configure(wraplength=max(210,e.width-340)))
        self._load_account_choices();self.show("Dashboard")

    def _background_resize(self,event):
        if event.widget is not self:return
        width,height=max(1,event.width),max(1,event.height)
        image=ImageOps.fit(self.original_bg,(width,height),Image.Resampling.LANCZOS)
        image=ImageEnhance.Brightness(image).enhance(.35)
        self.bg_image=ImageTk.PhotoImage(image)
        self.background.delete("all");self.background.create_image(0,0,image=self.bg_image,anchor="nw")

    def panel(self,parent,title):
        panel=ttk.Frame(parent,style="Panel.TFrame",padding=18);panel.pack(fill="x",pady=(0,14))
        ttk.Label(panel,text=title,style="Section.TLabel").pack(anchor="w",pady=(0,10))
        return panel

    def row(self,parent,label,value="",*,secret=False):
        row=ttk.Frame(parent,style="Panel.TFrame");row.pack(fill="x",pady=5)
        ttk.Label(row,text=label,width=20,style="Muted.TLabel").pack(side="left")
        variable=tk.StringVar(value=value)
        ttk.Entry(row,textvariable=variable,show="•" if secret else "").pack(side="left",fill="x",expand=True)
        return variable

    def _dashboard(self,parent):
        hero=self.panel(parent,"YOUR TRADING WORKSPACE")
        banner=tk.Canvas(hero,height=145,bg=PANEL,highlightthickness=0)
        banner.pack(fill="x",pady=(0,14))
        def draw_banner(event):
            image=ImageOps.fit(self.original_bg,(max(1,event.width),145),Image.Resampling.LANCZOS,centering=(.5,.43))
            banner.image=ImageTk.PhotoImage(ImageEnhance.Brightness(image).enhance(.65))
            banner.delete("all");banner.create_image(0,0,image=banner.image,anchor="nw")
            banner.create_text(20,95,text="AGORA ZION TRADER",fill=TEXT,font=("Segoe UI",20,"bold"),anchor="w")
            banner.create_text(20,125,text="DISCIPLINE  •  PRECISION  •  CONTROL",fill=GOLD,font=("Segoe UI",9,"bold"),anchor="w")
        banner.bind("<Configure>",draw_banner)
        ttk.Label(hero,text="Stay connected. See every decision.",font=("Segoe UI",20,"bold"),style="Panel.TLabel").pack(anchor="w")
        ttk.Label(hero,text="AZT manages execution on your selected MT5 terminals. Your broker keeps open positions and SL/TP.",style="Muted.TLabel",wraplength=760).pack(anchor="w",pady=(8,0))
        metrics=ttk.Frame(parent,style="Page.TFrame");metrics.pack(fill="x",pady=(0,14))
        self.metric_cards=[]
        for name in ("AZT server","Subscription","MT5 account","Today PnL","Open positions","Automated trading"):
            frame=ttk.Frame(metrics,style="Panel.TFrame",padding=16)
            ttk.Label(frame,text=name.upper(),style="Muted.TLabel",font=("Segoe UI",8,"bold")).pack(anchor="w")
            var=tk.StringVar(value="—");ttk.Label(frame,textvariable=var,style="Metric.TLabel",wraplength=210).pack(anchor="w",pady=(8,0))
            self.metrics[name]=var;self.metric_cards.append(frame)
        def reflow(event):
            count=max(1,min(3,int(event.width)//215))
            for i,frame in enumerate(self.metric_cards):frame.grid(row=i//count,column=i%count,sticky="nsew",padx=5,pady=5)
            for i in range(3):metrics.columnconfigure(i,weight=1 if i<count else 0,minsize=0)
        metrics.bind("<Configure>",reflow)
        account=self.panel(parent,"MT5 ACCOUNTS & CONNECTION")
        top=ttk.Frame(account,style="Panel.TFrame");top.pack(fill="x",pady=(0,8))
        self.account_choice=tk.StringVar();self.account_combo=ttk.Combobox(top,textvariable=self.account_choice,state="readonly")
        self.account_combo.pack(side="left",fill="x",expand=True);self.account_combo.bind("<<ComboboxSelected>>",self._select_account)
        ttk.Button(top,text="Add account",command=self.add_account).pack(side="left",padx=8)
        ttk.Button(top,text="Remove",command=self.remove_account).pack(side="left")
        self.account_limit=tk.StringVar(value="Account allowance is verified by your AZT subscription.")
        ttk.Label(account,textvariable=self.account_limit,style="Muted.TLabel",wraplength=740).pack(anchor="w",pady=6)
        self.alias=self.row(account,"Account name")
        self.login=self.row(account,"MT5 login",str(self.profile.mt5_login or ""))
        self.server=self.row(account,"MT5 broker server",self.profile.mt5_server)
        pathrow=ttk.Frame(account,style="Panel.TFrame");pathrow.pack(fill="x",pady=5)
        ttk.Label(pathrow,text="MT5 terminal",width=20,style="Muted.TLabel").pack(side="left")
        self.terminal=tk.StringVar();ttk.Entry(pathrow,textvariable=self.terminal).pack(side="left",fill="x",expand=True)
        ttk.Button(pathrow,text="Browse / Detect",command=self.detect_mt5).pack(side="left",padx=(8,0))
        self.pairing=self.row(account,"Pairing code",self.profile.pairing_code,secret=True)
        self.telegram=self.row(account,"Telegram (optional)",self.profile.telegram_username)
        self.url=self.row(account,"AZT server URL",self.profile.server_url)
        zone=ttk.Frame(account,style="Panel.TFrame");zone.pack(fill="x",pady=5)
        ttk.Label(zone,text="Display timezone",width=20,style="Muted.TLabel").pack(side="left")
        self.zone=tk.StringVar(value=self.profile.display_timezone)
        ttk.Combobox(zone,textvariable=self.zone,values=CHOICES).pack(side="left",fill="x",expand=True)
        ttk.Label(account,text="Each account needs its own MT5 installation/terminal. Never change the logged-in account while trading is enabled.",style="Muted.TLabel",wraplength=740).pack(anchor="w",pady=8)
        self.expiry=tk.StringVar(value="Connect to view your subscription timer.")
        ttk.Label(account,textvariable=self.expiry,foreground=GOLD,style="Panel.TLabel").pack(anchor="w",pady=5)
        ttk.Button(account,text="Save account & preferences",command=self.save).pack(anchor="w",pady=8)
        reconnect=self.panel(parent,"AUTOMATIC RECOVERY")
        self.retry=self.row(reconnect,"First retry (seconds)",str(self.profile.retry_interval))
        self.retry_cap=self.row(reconnect,"Maximum retry",str(self.profile.retry_cap))
        self.retry_alert=self.row(reconnect,"Failures before alert",str(self.profile.retries_before_alert))
        self.alert_cooldown=self.row(reconnect,"Alert cooldown",str(self.profile.alert_cooldown))
        ttk.Label(reconnect,text="Network interruptions keep your Start choice enabled. Recovery skips old queued instructions and retains duplicate protection.",style="Muted.TLabel",wraplength=740).pack(anchor="w",pady=6)
        notifications=self.panel(parent,"MESSAGES & NOTIFICATIONS")
        self.message_tree=table(notifications,[("read","Status",90),("subject","Message",340),("time","Received",190)],5)
        self.message_tree.bind("<<TreeviewSelect>>",self._message_select)
        self.message_body=tk.Text(notifications,height=4,bg=PANEL2,fg=TEXT,wrap="word",relief="flat",font=("Segoe UI",10));self.message_body.pack(fill="x",pady=6)
        ttk.Button(notifications,text="Mark selected as read",command=self.mark_read).pack(anchor="w")
        recent=self.panel(parent,"RECENT TRADES")
        self.recent=table(recent,[("symbol","Market",110),("side","Side",70),("pnl","PnL",100),("time","Closed",190)],4)
        ttk.Button(recent,text="View all trades",command=lambda:self.show("Trades")).pack(anchor="w")

    def _trades(self,parent):
        panel=self.panel(parent,"POSITIONS & HISTORY")
        ttk.Label(panel,text="Prices and PnL are broker snapshots. Timestamps use your display timezone.",style="Muted.TLabel",wraplength=730).pack(anchor="w")
        book=ttk.Notebook(panel);book.pack(fill="both",expand=True,pady=12)
        opened=ttk.Frame(book,style="Panel.TFrame",padding=8);history=ttk.Frame(book,style="Panel.TFrame",padding=8)
        book.add(opened,text="Open / Floating");book.add(history,text="Trade history")
        self.positions=table(opened,[("account","Account",100),("ticket","Ticket",95),("symbol","Market",95),("direction","Side",70),("strategy","Strategy",120),
            ("entry","Entry",90),("current","Current",90),("sl","SL",90),("tp","TP",90),("pnl","Floating PnL",100),("time","Opened",185)],15)
        self.history=table(history,[("account","Account",100),("ticket","Ticket",95),("symbol","Market",95),("direction","Side",70),("strategy","Strategy",120),
            ("entry","Entry",90),("exit","Exit",90),("pnl","Closed PnL",100),("result","Result",90),("time","Closed",185)],15)

    def _journal(self,parent):
        panel=self.panel(parent,"DAILY JOURNAL")
        row=ttk.Frame(panel,style="Panel.TFrame");row.pack(fill="x")
        self.journal_date=tk.StringVar(value=datetime.now().date().isoformat())
        ttk.Label(row,text="Date in your display timezone",style="Muted.TLabel").pack(side="left")
        ttk.Entry(row,textvariable=self.journal_date,width=14).pack(side="left",padx=10)
        ttk.Button(row,text="Load journal",command=self.load_journal).pack(side="left")
        self.journal_text=tk.Text(panel,height=25,bg=PANEL,fg=TEXT,wrap="word",relief="flat",font=("Segoe UI",12),padx=12,pady=15)
        self.journal_text.pack(fill="both",expand=True,pady=12)
        self.journal_text.insert("1.0","Connect your account to view trades, wins, losses, PnL, risk and strategies for the selected date.")

    def _referrals(self,parent):
        panel=self.panel(parent,"GROW WITH AZT")
        self.referral_summary=tk.StringVar(value="Connect to view your referral code and rewards.")
        ttk.Label(panel,textvariable=self.referral_summary,style="Panel.TLabel",wraplength=730,font=("Segoe UI",12)).pack(anchor="w",pady=8)
        self.referral_code=tk.StringVar();self.referral_link=tk.StringVar()
        for label,variable in (("Your code",self.referral_code),("Your link",self.referral_link)):
            row=ttk.Frame(panel,style="Panel.TFrame");row.pack(fill="x",pady=6)
            ttk.Label(row,text=label,width=14,style="Muted.TLabel").pack(side="left")
            ttk.Entry(row,textvariable=variable,state="readonly").pack(side="left",fill="x",expand=True)
            ttk.Button(row,text="Copy",command=lambda var=variable:self.copy(var.get())).pack(side="left",padx=8)
        self.referral_from=self.row(panel,"Referred by code")
        ttk.Button(panel,text="Record my referrer",command=self.link_referral).pack(anchor="w",pady=8)
        self.reward_tree=table(panel,[("when","Date",180),("status","Status",100),("amount","Reward",110),("source","Reference",240)],7)
        promo=self.panel(parent,"GIVEAWAY / PROMO ACCESS")
        self.promo=self.row(promo,"Promo code")
        ttk.Button(promo,text="Redeem code",style="Gold.TButton",command=self.redeem).pack(anchor="w",pady=8)
        ttk.Label(promo,text="Access duration and MT5 account allowance are defined by the code. Repeated redemptions cannot bypass its limits.",style="Muted.TLabel",wraplength=730).pack(anchor="w",pady=6)

    def _payments(self,parent):
        panel=self.panel(parent,"SUBSCRIPTION & PAYMENTS")
        ttk.Label(panel,text="Select a plan and one payment method. Your subscription activates after payment approval.",style="Muted.TLabel",wraplength=730).pack(anchor="w",pady=6)
        self.plan_choice=tk.StringVar();self.method_choice=tk.StringVar();self.amount_due=tk.StringVar(value="Connect to view available plans.")
        for title,var,attr,callback in (("Plan",self.plan_choice,"plan_combo",self._payment_details),("Payment method",self.method_choice,"method_combo",self._payment_details)):
            row=ttk.Frame(panel,style="Panel.TFrame");row.pack(fill="x",pady=8)
            ttk.Label(row,text=title,width=20,style="Muted.TLabel").pack(side="left")
            combo=ttk.Combobox(row,textvariable=var,state="readonly");combo.pack(side="left",fill="x",expand=True);combo.bind("<<ComboboxSelected>>",callback);setattr(self,attr,combo)
        ttk.Label(panel,textvariable=self.amount_due,style="Section.TLabel",wraplength=730).pack(anchor="w",pady=10)
        self.method_details=tk.StringVar(value="Select one method to see its receiving details.")
        ttk.Label(panel,textvariable=self.method_details,style="Panel.TLabel",wraplength=730,font=("Segoe UI",12)).pack(anchor="w",pady=10)
        ttk.Button(panel,text="Copy selected receiving details",command=self.copy_payment).pack(anchor="w",pady=5)
        ttk.Label(panel,text="Send only using the exact network shown. Payments sent using the wrong network may not be recoverable.",foreground=GOLD,background=PANEL,wraplength=730).pack(anchor="w",pady=12)
        self.hash=self.row(panel,"Transaction hash")
        proof=ttk.Frame(panel,style="Panel.TFrame");proof.pack(fill="x",pady=8)
        ttk.Button(proof,text="Attach payment screenshot",command=self.attach_proof).pack(side="left")
        ttk.Label(proof,textvariable=self.proof_label,style="Muted.TLabel",wraplength=420).pack(side="left",padx=12)
        ttk.Button(panel,text="Submit for verification",style="Gold.TButton",command=self.submit_payment).pack(anchor="w",pady=12)
        ttk.Label(panel,text="MTN and Binance UID payments use manual screenshot review. Crypto submissions use transaction hashes; no automated blockchain verification is claimed.",style="Muted.TLabel",wraplength=730).pack(anchor="w",pady=8)
        self.payment_tree=table(panel,[("id","ID",70),("plan","Plan",100),("method","Method",130),("amount","Amount",115),("status","Status",120),("time","Submitted",180)],8)

    def show(self,name):
        self.page_name.set(name);self.pages[name].tkraise()
        for key,button in self.nav_buttons.items():button.configure(bg=PANEL2 if key==name else "#0b1924",fg=GOLD if key==name else MUTED)
        if self.session_token:
            if name=="Journal":self.load_journal()
            elif name in {"Trades","Referrals","Payments"}:self.refresh_data()

    def account(self): return next((row for row in self.profile.accounts if row["id"]==self.selected_id),None)

    def _load_account_choices(self):
        self.account_combo["values"]=[f"{row.get('alias') or row['mt5_login']} • {row['mt5_server']}" for row in self.profile.accounts]
        if self.profile.accounts:
            index=next((i for i,row in enumerate(self.profile.accounts) if row["id"]==self.selected_id),0)
            self.account_combo.current(index);self._select_account()

    def _select_account(self,_event=None):
        index=self.account_combo.current()
        if index<0:return
        row=self.profile.accounts[index]
        if self.selected_id!=row["id"]:self.session_token="";self.overview_data={}
        self.selected_id=row["id"]
        self.alias.set(row.get("alias",""));self.login.set(str(row.get("mt5_login","")));self.server.set(row.get("mt5_server",""));self.terminal.set(row.get("terminal_path",""))

    def add_account(self):
        self.selected_id="";self.account_choice.set("New account")
        for var in (self.alias,self.login,self.server,self.terminal):var.set("")
        self.session_token="";self.status.set("Choose an MT5 terminal, detect its account, then Save.")

    def remove_account(self):
        account=self.account()
        if not account:return
        if account.get("desired_running"):messagebox.showwarning("AZT","Stop this account before removing its local configuration.",parent=self);return
        if not messagebox.askyesno("Remove local account","Remove this terminal from this Client app? Server history and subscription records remain.",parent=self):return
        self.profile.accounts=[row for row in self.profile.accounts if row["id"]!=account["id"]]
        save_profile(self.profile);self.selected_id="";self.session_token="";self._load_account_choices()

    def save(self,*,quiet=False):
        try:
            login=int(self.login.get().strip());server=self.server.get().strip();terminal=self.terminal.get().strip()
            if login<=0 or not server:raise ValueError("Detect or enter the MT5 login and broker server.")
            if not Path(terminal).is_file():raise ValueError("Select the installed MT5 terminal executable.")
            zone=valid_zone(self.zone.get());url=self.url.get().strip().rstrip("/")
            if not url.startswith(("https://","http://")):raise ValueError("Enter an http:// or https:// AZT server URL.")
            retry=float(self.retry.get());cap=float(self.retry_cap.get());alerts=int(self.retry_alert.get());cooldown=float(self.alert_cooldown.get())
            if not all(math.isfinite(v) for v in (retry,cap,cooldown)) or not 1<=retry<=60 or not retry<=cap<=300 or not 1<=alerts<=100 or not 10<=cooldown<=86400:
                raise ValueError("Retry settings: first 1–60s, cap up to 300s, failures 1–100, cooldown 10–86400s.")
            old=self.account()
            if old and old.get("desired_running") and (login!=old["mt5_login"] or server!=old["mt5_server"] or terminal!=old.get("terminal_path")):
                raise ValueError("Stop this account before changing its MT5 identity or terminal.")
            if url!=self.profile.server_url and any(row.get("desired_running") for row in self.profile.accounts):raise ValueError("Stop all account workers before changing the server URL.")
            for row in self.profile.accounts:
                if row is old:continue
                if (row["mt5_login"]==login and row["mt5_server"]==server) or str(row.get("terminal_path","")).lower()==terminal.lower():
                    raise ValueError("Use a separate MT5 installation and unique account for each entry.")
            account=old or {"id":uuid4().hex,"desired_running":False}
            account.update(alias=self.alias.get().strip(),mt5_login=login,mt5_server=server,terminal_path=terminal)
            if old is None:self.profile.accounts.append(account)
            self.selected_id=account["id"]
            self.profile.pairing_code=self.pairing.get().strip();self.profile.server_url=url;self.profile.telegram_username=self.telegram.get().strip().lstrip("@")
            self.profile.display_timezone=zone;self.profile.mt5_login=login;self.profile.mt5_server=server
            self.profile.retry_interval=retry;self.profile.retry_cap=cap;self.profile.retries_before_alert=alerts;self.profile.alert_cooldown=cooldown
            save_profile(self.profile);self._load_account_choices()
            if not quiet:self.status.set("Account and preferences saved.")
            if self.session_token:
                api=self.api();token=self.session_token;self.async_call(lambda:api.preferences(token,zone),lambda _data:None)
            return True
        except Exception as exc:
            self.status.set(str(exc));messagebox.showerror("AZT settings",str(exc),parent=self);return False

    def detect_mt5(self):
        path=filedialog.askopenfilename(parent=self,title="Select this account's MT5 terminal",filetypes=[("MT5 terminal","terminal64.exe"),("Executable","*.exe")])
        if not path:return
        self.terminal.set(path)
        def complete(data):
            self.login.set(str(data["mt5_login"]));self.server.set(data["mt5_server"])
            self.status.set(f"Detected {data['mt5_login']} @ {data['mt5_server']}. Save this account to continue.")
        self.async_call(lambda:self.manager.probe(path),complete)

    def api(self):
        account=self.account()
        return GoldAIServer(for_account(self.profile,account) if account else self.profile)

    def async_call(self,action,complete,*,quiet=False):
        if self.closing:return
        def run():
            try:self.callbacks.put((complete,action(),None,quiet))
            except Exception as exc:self.callbacks.put((complete,None,str(exc),quiet))
        threading.Thread(target=run,daemon=True).start()

    def _callbacks(self):
        if self.closing:return
        for _ in range(20):
            try:callback,data,error,quiet=self.callbacks.get_nowait()
            except queue.Empty:break
            if error:
                self.status.set(error)
                if not quiet:messagebox.showerror("AZT",error,parent=self)
            else:
                try:callback(data)
                except Exception as exc:self.status.set("Could not display server data: "+str(exc))
        self.after(100,self._callbacks)

    def connect(self,*,then_start=False):
        if self.smoke:return
        if not self.account() and not self.save(quiet=True):return
        api=self.api();selected=self.selected_id
        zone=self.profile.display_timezone
        self.status.set("Connecting to AZT…")
        def complete(result):
            if self.selected_id!=selected:return
            self.session_token=result.session_token
            self.metrics["AZT server"].set("Connected")
            self.status.set(f"{result.display_name or 'Account'} • {result.message}")
            self.account_limit.set(f"Subscription allowance: up to {result.max_mt5_accounts} MT5 accounts. Each uses its own terminal.")
            if self.session_token:self.refresh_data()
            if then_start:
                if result.allowed:self._start_selected()
                else:messagebox.showwarning("Trading unavailable",result.message,parent=self)
        def authorize_and_preferences():
            result=api.authorize()
            if result.session_token:api.preferences(result.session_token,zone)
            return result
        self.async_call(authorize_and_preferences,complete)

    def start(self):
        if not self.save(quiet=True):return
        # The child's own authorization fails closed. Persist the user's choice
        # before any network request so an initial outage also reconnects.
        self._start_selected()
    def _start_selected(self):
        account=self.account()
        set_desired_state(account["id"],True)
        account["desired_running"]=True;save_profile(self.profile);self.manager.start(account)
        self.status.set("Automated trading enabled. Connecting and waiting for fresh signals.")
    def stop(self):
        account=self.account()
        if not account:return
        set_desired_state(account["id"],False)
        account["desired_running"]=False;save_profile(self.profile);self.manager.stop(account["id"])
        self.status.set("Stop requested. Existing broker positions remain open.")

    def _runtime_tick(self):
        if self.closing:return
        self.manager.poll()
        account=self.account()
        if account:
            runtime=self.manager.status(account["id"])
            self.metrics["Automated trading"].set(runtime.get("state","STOPPED"))
            self.metrics["MT5 account"].set(str(account["mt5_login"])+" · "+runtime.get("mt5_state","OFF"))
            if runtime.get("state")=="ACCESS_DISABLED" and account.get("desired_running"):
                set_desired_state(account["id"],False)
                account["desired_running"]=False;save_profile(self.profile);self.status.set(runtime.get("message","Trading access disabled."))
            self.start_button.configure(state="disabled" if account.get("desired_running") else "normal")
            self.stop_button.configure(state="normal" if account.get("desired_running") else "disabled")
            if account.get("desired_running") and runtime.get("state") in {"RECONNECTING","DEGRADED","RECOVERED","FAILED","STALE","STOPPING"}:
                self.status.set(runtime.get("message",runtime["state"]))
        sub=self.overview_data.get("subscription",{})
        self.expiry.set(remaining_text(sub.get("expires_utc",""))+" • "+display_time(sub.get("expires_utc"),self.profile.display_timezone))
        self.after(1000,self._runtime_tick)

    def _periodic(self):
        if self.closing:return
        if is_friends_edition() and local_trial_expired():
            self.status.set("Your 14-day trial has expired. Automated trading is disabled; the trial will uninstall automatically.")
            self.on_close()
            return
        if self.session_token:self.refresh_data(quiet=True)
        self.after(15000,self._periodic)

    def refresh_data(self,quiet=False):
        if not self.session_token:return
        api=self.api();token=self.session_token;selected=self.selected_id
        page=self.page_name.get()
        def fetch():
            data={"overview":api.overview(token),"messages":api.messages(token),"trades":api.trades(token)}
            if is_friends_edition():
                observe_subscription(data["overview"].get("subscription", {}))
            if page=="Referrals":data["referrals"]=api.referrals(token)
            if page=="Payments":data.update(plans=api.plans(token),methods=api.payment_methods(token),payments=api.payments(token))
            return data
        def complete(data):
            if selected!=self.selected_id:return
            self.overview_data=data["overview"];self.trades_data=data["trades"]
            sub=self.overview_data.get("subscription",{})
            self.metrics["Subscription"].set(str(self.overview_data.get("subscription_status",sub.get("effective_status",sub.get("status","UNKNOWN")))).replace("_"," "))
            self.metrics["AZT server"].set("Connected")
            self.messages_data=data["messages"].get("messages",[]) if isinstance(data["messages"],dict) else data["messages"]
            self._render_messages();self._render_trades()
            if "referrals" in data:self._render_referrals(data["referrals"])
            if "plans" in data:self._render_payments(data)
        self.async_call(fetch,complete,quiet=quiet)

    def _render_messages(self):
        self.message_tree.delete(*self.message_tree.get_children())
        for message in self.messages_data:
            self.message_tree.insert("","end",iid=str(message["id"]),values=("Read" if message.get("read") or message.get("read_utc") else "Unread",message.get("subject",message.get("title","AZT message")),display_time(message.get("created_utc"),self.profile.display_timezone)))
    def _message_select(self,_event=None):
        selection=self.message_tree.selection()
        if not selection:return
        row=next((item for item in self.messages_data if str(item["id"])==selection[0]),{})
        self.message_body.delete("1.0","end");self.message_body.insert("1.0",row.get("body",row.get("message","")))
    def mark_read(self):
        selection=self.message_tree.selection()
        if not selection or not self.session_token:return
        api=self.api();token=self.session_token;message_id=int(selection[0])
        self.async_call(lambda:api.mark_read(token,message_id),lambda _data:self.refresh_data())

    def _render_trades(self):
        positions=self.trades_data.get("positions",[]);trades=self.trades_data.get("trades",[])
        self.metrics["Open positions"].set(str(len(positions)))
        zone=self.profile.display_timezone
        for tree in (self.positions,self.history,self.recent):tree.delete(*tree.get_children())
        pnl_by_currency={}
        for row in positions:
            value=float(row.get("pnl",row.get("profit",0)) or 0)
            self.positions.insert("","end",values=(row.get("account_key",row.get("account",row.get("account_login","—"))),row.get("ticket",""),row.get("symbol",""),row.get("direction",""),row.get("strategy","—"),row.get("entry","—"),row.get("current_price","—"),row.get("sl","—"),row.get("tp","—"),f"{value:+.2f} {row.get('currency','')}",display_time(row.get("opened_utc"),zone)),tags=("profit" if value>=0 else "loss",))
        for index,row in enumerate(sorted(trades,key=lambda item:str(item.get("closed_utc","")),reverse=True)):
            value=float(row.get("pnl",row.get("profit",0)) or 0);stamp=row.get("closed_utc",row.get("timestamp_utc"))
            self.history.insert("","end",values=(row.get("account_key",row.get("account",row.get("account_login","—"))),row.get("ticket",""),row.get("symbol",""),row.get("direction",""),row.get("strategy","—"),row.get("entry","—"),row.get("exit","—"),f"{value:+.2f} {row.get('currency','')}",row.get("result",""),display_time(stamp,zone)),tags=("profit" if value>=0 else "loss",))
            if index<5:self.recent.insert("","end",values=(row.get("symbol",""),row.get("direction",""),f"{value:+.2f}",display_time(stamp,zone)),tags=("profit" if value>=0 else "loss",))
            try:
                from zoneinfo import ZoneInfo
                date=datetime.fromisoformat(str(stamp).replace("Z","+00:00")).astimezone(ZoneInfo(zone)).date().isoformat()
                if date==datetime.now(ZoneInfo(zone)).date().isoformat():
                    currency=row.get("currency") or "UNKNOWN"
                    pnl_by_currency[currency]=pnl_by_currency.get(currency,0)+value
            except (ValueError,TypeError):pass
        self.metrics["Today PnL"].set(" / ".join(f"{value:+.2f} {currency}" for currency,value in pnl_by_currency.items()) or "0.00")

    def load_journal(self):
        if not self.session_token:return
        try:datetime.strptime(self.journal_date.get(),"%Y-%m-%d")
        except ValueError:self.status.set("Use YYYY-MM-DD for the journal date.");return
        api=self.api();token=self.session_token;date=self.journal_date.get()
        def complete(data):
            self.journal_text.delete("1.0","end")
            journal=data.get("journal",data)
            lines=[f"DAILY JOURNAL • {date} • {self.profile.display_timezone}",""]
            for key in ("trades_taken","trade_count","wins","losses","pnl","pnl_by_currency","win_rate","risk_used","strategies_used","strategies","notes"):
                if key in journal:lines.append(key.replace("_"," ").title()+": "+str(journal[key]))
            if len(lines)==2:lines.append(json.dumps(journal,ensure_ascii=False,indent=2))
            self.journal_text.insert("1.0","\n\n".join(lines))
        self.async_call(lambda:api.journal(token,date),complete)

    def _render_referrals(self,data):
        def money(value):
            if isinstance(value,dict):return ", ".join(f"{float(amount):.2f} {currency}" for currency,amount in value.items()) or "0.00"
            return str(value)
        self.referral_code.set(str(data.get("code",data.get("referral_code",""))))
        self.referral_link.set(str(data.get("link",data.get("referral_link",""))))
        self.referral_summary.set(f"Referred: {data.get('number_referred',data.get('referred_count',0))}   •   Active: {data.get('active_referrals',0)}\nEarned: {money(data.get('rewards_earned',data.get('earned',0)))}   •   Pending: {money(data.get('pending_rewards',data.get('pending',0)))}\n{data.get('policy_message','Rewards follow the referral policy configured by AZT Admin.')}")
        self.reward_tree.delete(*self.reward_tree.get_children())
        for row in data.get("reward_history",data.get("history",data.get("rewards",[]))):
            self.reward_tree.insert("","end",values=(display_time(row.get("created_utc"),self.profile.display_timezone),row.get("status",""),str(row.get("amount",0))+" "+str(row.get("currency","")),row.get("payment_id",row.get("id",""))))
    def link_referral(self):
        if not self.session_token:return
        api=self.api();token=self.session_token;code=self.referral_from.get().strip()
        self.async_call(lambda:api.link_referral(token,code),lambda _data:(self.status.set("Referrer recorded."),self.refresh_data()))
    def redeem(self):
        if not self.session_token:return
        api=self.api();token=self.session_token;code=self.promo.get().strip()
        self.async_call(lambda:api.redeem(token,code),lambda _data:(self.status.set("Promo access applied."),self.refresh_data()))

    def _render_payments(self,data):
        self.plans_data=data["plans"].get("plans",[]);self.methods_data=data["methods"].get("methods",[])
        self.plan_combo["values"]=[str(row.get("name",row["code"]))+" ["+row["code"]+"]" for row in self.plans_data]
        self.method_combo["values"]=[str(row.get("name",row["code"]))+" ["+row["code"]+"]" for row in self.methods_data]
        if self.plans_data and self.plan_combo.current()<0:self.plan_combo.current(0)
        self._payment_details()
        self.payment_tree.delete(*self.payment_tree.get_children())
        for row in data["payments"].get("payments",[]):
            self.payment_tree.insert("","end",values=(row.get("id"),row.get("plan_code"),row.get("method",row.get("provider")),str(row.get("amount"))+" "+str(row.get("currency")),row.get("status"),display_time(row.get("created_utc"),self.profile.display_timezone)))
    def _selected_payment(self):
        pi,mi=self.plan_combo.current(),self.method_combo.current()
        return (self.plans_data[pi] if pi>=0 and pi<len(self.plans_data) else None,self.methods_data[mi] if mi>=0 and mi<len(self.methods_data) else None)
    def _payment_details(self,_event=None):
        plan,method=self._selected_payment()
        if plan:
            self.amount_due.set("Price not configured — contact AZT Admin" if plan.get("amount") is None else f"Amount due: {plan['amount']} {plan.get('currency','USD')} • {plan.get('duration_days','—')} days • {plan.get('max_mt5_accounts',1)} MT5 account(s)")
        if method:
            text=str(method.get("name",method["code"]))
            if method.get("network"):text+="\nNETWORK: "+method["network"]
            for key in ("address","number","uid","recipient"):
                if method.get(key):text+="\n"+str(method[key])
            self.method_details.set(text+"\nVerification: "+str(method.get("verification","Manual approval")))
        else:self.method_details.set("Select one method to see its receiving details.")
    def copy_payment(self):
        _plan,method=self._selected_payment()
        if method:self.copy(str(method.get("address",method.get("number",method.get("uid","")))))
    def attach_proof(self):
        path=filedialog.askopenfilename(parent=self,title="Payment screenshot",filetypes=[("Screenshot","*.png *.jpg *.jpeg")])
        if not path:return
        raw=Path(path).read_bytes()
        if len(raw)>2*1024*1024:messagebox.showwarning("Screenshot too large","Choose a PNG or JPEG screenshot smaller than 2 MB.",parent=self);return
        mime="image/png" if raw.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if raw.startswith(b"\xff\xd8\xff") else ""
        if not mime:messagebox.showwarning("Invalid screenshot","Choose a PNG or JPEG image.",parent=self);return
        self.proof_data="data:"+mime+";base64,"+base64.b64encode(raw).decode("ascii");self.proof_label.set(Path(path).name)
    def submit_payment(self):
        if not self.session_token:return
        plan,method=self._selected_payment()
        if not plan or not method:messagebox.showwarning("AZT payment","Select a plan and payment method first.",parent=self);return
        api=self.api();token=self.session_token;proof=self.proof_data;tx=self.hash.get().strip()
        self.async_call(lambda:api.submit_payment(token,plan["code"],method["code"],proof,tx),lambda _data:(self.status.set("Payment submitted. Awaiting verification; no automatic approval is assumed."),self.refresh_data()))
    def copy(self,value):
        self.clipboard_clear();self.clipboard_append(value);self.status.set("Copied.")

    def on_close(self):
        if self.closing:return
        self.closing=True;self.withdraw()
        def close():
            self.manager.close();self.after(0,self.destroy)
        threading.Thread(target=close,daemon=True).start()

def smoke_test():
    from client.storage import PROFILE_PATH
    app=GoldAIClientApp(smoke=True)
    now=datetime.now().astimezone().isoformat()
    app.messages_data=[{"id":1,"title":"Welcome","body":"A private in-app message without Telegram.","created_utc":now,"read_utc":""}]
    app._render_messages()
    app.trades_data={"positions":[{"account_key":"Broker|123","ticket":"1","symbol":"XAUUSD.m","direction":"BUY","pnl":1.25,"currency":"USD","opened_utc":now}],"trades":[{"account_key":"Broker|123","ticket":"2","symbol":"GOLD","direction":"SELL","pnl":2,"currency":"USD","closed_utc":now}]}
    app._render_trades()
    app._render_referrals({"code":"AZT-TEST","link":"https://example.invalid/ref/AZT-TEST","number_referred":2,"active_referrals":1,"rewards_earned":{"USD":3},"pending_rewards":{"USD":1},"reward_history":[]})
    app._render_payments({"plans":{"plans":[{"code":"STARTER","name":"Starter","amount":None,"currency":"USD","duration_days":30,"max_mt5_accounts":1}]},"methods":{"methods":[{"code":"USDT_TRC20","name":"USDT","network":"TRC20 / Tron","address":"TEST-ADDRESS","verification":"MANUAL_HASH"}]},"payments":{"payments":[]}})
    assert "TEST-ADDRESS" not in app.method_details.get(),"Payment details shown before selecting a method"
    app.method_combo.current(0);app._payment_details()
    assert "TRC20 / Tron" in app.method_details.get()
    assert len(app.positions.get_children())==1 and len(app.history.get_children())==1
    assert "3.00 USD" in app.referral_summary.get()
    for width,height in ((1024,768),(1280,800),(1366,768),(1440,900)):
        app.state("normal");app.geometry(f"{width}x{height}");app.update()
        for page in app.pages:
            app.show(page);app.update()
            assert app.start_button.winfo_rooty()+app.start_button.winfo_height()<=app.winfo_rooty()+app.winfo_height()
            assert app.stop_button.winfo_viewable()
    assert not app.manager.processes
    assert len(app.pages)==5
    app.destroy()
    print("AZT Client responsive UI smoke passed; no server connection, MT5 connection or order.")

if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="--trial-guard":
        raise SystemExit(run_expiry_guard())
    elif len(sys.argv)>1 and sys.argv[1]=="--worker":
        from client.runtime import worker
        worker(sys.argv[2])
    elif len(sys.argv)>1 and sys.argv[1]=="--probe":
        from client.runtime import probe
        probe(sys.argv[2],sys.argv[3])
    elif "--smoke-test" in sys.argv:smoke_test()
    else:
        from client.instance import acquire
        try:workspace_lock=acquire(APP_DIR/".client.lock")
        except RuntimeError as exc:
            dialog=tk.Tk();dialog.withdraw();messagebox.showinfo("AZT Client",str(exc),parent=dialog);dialog.destroy()
        else:
            try:
                if is_friends_edition() and local_trial_expired():
                    dialog=tk.Tk();dialog.withdraw()
                    messagebox.showinfo("AZT Friends Trial", "Your 14-day trial has expired. AZT will uninstall the trial edition; your MetaTrader 5 and broker positions remain untouched.", parent=dialog)
                    dialog.destroy()
                    run_expiry_guard()
                else:
                    GoldAIClientApp().mainloop()
            finally:workspace_lock.close()
