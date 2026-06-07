#!/usr/bin/env python3
"""
BountyHunter Desktop Widget — always-on-top real-time dashboard.
Minimal, elegant, dark-theme overlay. Drag to move. Right-click for menu.
Auto-refreshes every 2 minutes. Survives network errors gracefully.
"""
import json, os, sys, time, threading, webbrowser
from datetime import datetime, timezone

try: import requests
except ImportError: os.system(f"{sys.executable} -m pip install requests -q"); import requests

import tkinter as tk
from tkinter import font as tkfont

DATA_URL = "https://luw8072-gif.github.io/bountyhunter/data"
WALLET = "0x76485924c7CA4EFcC03e622441fF3ab633c86143"
DASHBOARD = "https://luw8072-gif.github.io/bountyhunter/"
REFRESH_SEC = 120

# ── Colors ──
BG      = "#080c14"
CARD    = "#0f1520"
BORDER  = "#1a2540"
TEXT    = "#c9d1d9"
ACCENT  = "#58a6ff"
GREEN   = "#3fb950"
GOLD    = "#d2991d"
RED     = "#f85149"
DIM     = "#6e7681"
WHITE   = "#e6edf3"

class BountyWidget:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("BountyHunter")
        self.root.geometry("300x380+20+60")
        self.root.configure(bg=BG)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.94)
        self.root.minsize(260, 320)

        # Drag
        self._dx = 0; self._dy = 0
        self.root.bind("<Button-1>", lambda e: (setattr(self, '_dx', e.x), setattr(self, '_dy', e.y)))
        self.root.bind("<B1-Motion>", lambda e: self.root.geometry(f"+{self.root.winfo_x()+e.x-self._dx}+{self.root.winfo_y()+e.y-self._dy}"))

        # Right-click menu
        self.menu = tk.Menu(self.root, tearoff=0, bg=CARD, fg=TEXT, font=("", 9))
        self.menu.add_command(label="打开仪表盘", command=lambda: webbrowser.open(DASHBOARD))
        self.menu.add_command(label="复制钱包", command=lambda: (self.root.clipboard_clear(), self.root.clipboard_append(WALLET)))
        self.menu.add_command(label="刷新", command=self.refresh)
        self.menu.add_command(label="关闭", command=self.root.destroy)
        self.root.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))

        # ── Top bar ──
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=10, pady=(10,0))
        tk.Label(top, text="BountyHunter", font=("Segoe UI", 12, "bold"), bg=BG, fg=WHITE).pack(side="left")
        self.dot = tk.Label(top, text="●", font=("", 7), bg=BG, fg=GREEN)
        self.dot.pack(side="left", padx=(4,0))

        # ── Stat cards (2x2 grid) ──
        grid = tk.Frame(self.root, bg=BG)
        grid.pack(fill="x", padx=10, pady=(8,0))
        grid.columnconfigure(0, weight=1); grid.columnconfigure(1, weight=1)

        self.cards = {}
        items = [
            ("bounties", "活跃赏金", "—", ACCENT, 0),
            ("value",    "市场总值", "—", GOLD,   1),
            ("claimed",  "已申领",   "—", GOLD,   2),
            ("earned",   "已到账",   "—", GREEN,  3),
        ]
        for key, label, default, color, idx in items:
            r, c = divmod(idx, 2)
            f = tk.Frame(grid, bg=CARD, highlightbackground=BORDER, highlightthickness=1, padx=8, pady=8)
            f.grid(row=r, column=c, padx=2, pady=2, sticky="nsew")
            v = tk.Label(f, text=default, font=("Segoe UI", 20, "bold"), bg=CARD, fg=color)
            v.pack()
            tk.Label(f, text=label, font=("Segoe UI", 8), bg=CARD, fg=DIM).pack()
            self.cards[key] = v

        # ── PR list title ──
        pr_top = tk.Frame(self.root, bg=BG)
        pr_top.pack(fill="x", padx=12, pady=(10,2))
        tk.Label(pr_top, text="PR 状态", font=("Segoe UI", 9, "bold"), bg=BG, fg=TEXT).pack(side="left")

        # ── PR list ──
        self.pr_canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0, height=130)
        self.pr_canvas.pack(fill="x", padx=8)
        self.pr_inner = tk.Frame(self.pr_canvas, bg=BG)
        self.pr_canvas.create_window((0,0), window=self.pr_inner, anchor="nw")
        self.pr_labels = []

        # ── Footer ──
        foot = tk.Frame(self.root, bg=BG)
        foot.pack(fill="x", padx=10, pady=(6,8), side="bottom")
        tk.Label(foot, text=f"{WALLET[:8]}...{WALLET[-4:]}", font=("Consolas", 7), bg=BG, fg=DIM).pack(side="left")
        self.tick_label = tk.Label(foot, text="", font=("Consolas", 7), bg=BG, fg=DIM)
        self.tick_label.pack(side="right")

        self.data_cache = {}
        self.refresh()
        self._loop()

    # ── Data ──
    def _get(self, fname):
        try:
            r = requests.get(f"{DATA_URL}/{fname}", timeout=12)
            return r.json() if r.status_code == 200 else None
        except: return None

    def refresh(self):
        def _t():
            self.data_cache["meta"] = self._get("meta.json") or {}
            self.data_cache["earnings"] = self._get("earnings.json") or {}
            self.data_cache["matches"] = self._get("matches.json") or []
            self.root.after(0, self._render)
        threading.Thread(target=_t, daemon=True).start()

    def _render(self):
        meta = self.data_cache.get("meta", {})
        earn = self.data_cache.get("earnings", {})
        s = earn.get("summary", {})

        total    = meta.get("total", "—")
        value    = meta.get("total_value_usd", 0)
        claimed  = s.get("total_claimed_usd", 0)
        earned   = s.get("total_earned_usd", 0)
        merged   = s.get("merged_prs", 0)
        open_pr  = s.get("open_prs", 0)

        self.cards["bounties"].config(text=str(total))
        self.cards["value"].config(text=f"${value:,.0f}" if value else "$0")
        self.cards["claimed"].config(text=f"${claimed:,.0f}")
        self.cards["earned"].config(text=f"${earned:,.0f}")

        if earned > 0:
            self.cards["earned"].config(fg="#00ff00")
            self.dot.config(fg="#00ff00")

        # PR list
        for w in self.pr_labels: w.destroy()
        self.pr_labels.clear()

        prs = earn.get("prs", [])
        if prs:
            for pr in prs:
                row = tk.Frame(self.pr_inner, bg=BG)
                row.pack(fill="x", pady=0)
                merged_flag = pr.get("merged")
                icon = "✔" if merged_flag else ("●" if pr.get("state")=="open" else "✖")
                color = GREEN if merged_flag else (ACCENT if pr.get("state")=="open" else RED)
                line = f"{icon} #{pr['pr']} {pr['title'][:22]}  ${pr['bounty']:,}"
                lbl = tk.Label(row, text=line, font=("Segoe UI", 8), bg=BG, fg=color, anchor="w")
                lbl.pack(side="left")
                self.pr_labels.append(row)
        else:
            lbl = tk.Label(self.pr_inner, text="等待数据...", font=("Segoe UI", 8), bg=BG, fg=DIM)
            lbl.pack()
            self.pr_labels.append(lbl)

        self.tick_label.config(text=datetime.now().strftime("%H:%M"))

    def _loop(self):
        self.refresh()
        self.root.after(REFRESH_SEC * 1000, self._loop)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    BountyWidget().run()
