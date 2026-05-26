"""
Stock Monitor — CustomTkinter GUI
Usage: python monitor_gui.py
"""
from __future__ import annotations

import json
import queue
import random
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).parent))

from notifier import send_notification
from state_manager import StateManager
from scrapers.continente import ContinenteScraper
from scrapers.toysrus import ToysRusScraper
from scrapers.creativetoys import CreativeToysScraper

# ── theme ─────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C_BG     = "#111827"
C_PANEL  = "#1f2937"
C_CARD   = "#374151"
C_ACCENT = "#60a5fa"
C_GREEN  = "#34d399"
C_RED    = "#f87171"
C_BLUE   = "#60a5fa"
C_ORANGE = "#fbbf24"
C_GRAY   = "#6b7280"
C_TEXT   = "#f9fafb"
C_GOLD   = "#fde68a"

SCRAPER_MAP = {
    "continente":   ContinenteScraper,
    "toysrus":      ToysRusScraper,
    "creativetoys": CreativeToysScraper,
}
SITE_LABEL = {
    "continente":   "Continente",
    "toysrus":      "ToysRus",
    "creativetoys": "CreativeToys",
}
SITE_URL = {
    "continente":   "https://www.continente.pt",
    "toysrus":      "https://www.toysrus.pt",
    "creativetoys": "https://creativetoys.pt",
}
EVENT_TAG = {
    "new_product":   ("🆕", "new"),
    "back_in_stock": ("✅", "back"),
    "out_of_stock":  ("❌", "oos"),
    "price_change":  ("💰", "price"),
}

CONFIG_PATH = Path(__file__).parent / "config.json"


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _compute_discount(original_price, current_price) -> str:
    """Return '↓ -X%' if original > current, else ''."""
    if not original_price or not current_price:
        return ""
    try:
        orig = float(original_price)
        curr = float(current_price)
        if orig > curr > 0:
            pct = round((orig - curr) / orig * 100)
            return f"↓ -{pct}%"
    except (ValueError, TypeError):
        pass
    return ""


# ── Ignore-list dialog ────────────────────────────────────────────────────────

class IgnoreListDialog(ctk.CTkToplevel):
    def __init__(self, app: "App"):
        super().__init__(app)
        self._app = app
        self.title("Ignore List")
        self.geometry("460x460")
        self.configure(fg_color=C_BG)
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()
        self.lift()
        self.focus_force()

        self._keywords: list[str] = list(app._cfg.get("ignore_keywords", []))
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="Ignore List",
                     font=("Segoe UI", 16, "bold"),
                     text_color=C_TEXT).pack(padx=20, pady=(20, 2), anchor="w")
        ctk.CTkLabel(self,
                     text="Products whose name contains any keyword are silently skipped.",
                     font=("Segoe UI", 11), text_color=C_GRAY,
                     wraplength=420).pack(padx=20, anchor="w")

        # keyword listbox
        lf = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=8)
        lf.pack(padx=20, pady=12, fill="both", expand=True)

        self._lb = tk.Listbox(
            lf, bg=C_PANEL, fg=C_TEXT,
            font=("Segoe UI", 12), borderwidth=0, highlightthickness=0,
            selectbackground=C_ACCENT, selectforeground="#111827",
            activestyle="none",
        )
        self._lb.pack(padx=8, pady=8, fill="both", expand=True)
        for kw in self._keywords:
            self._lb.insert("end", kw)

        # add row
        af = ctk.CTkFrame(self, fg_color="transparent")
        af.pack(padx=20, pady=(0, 8), fill="x")
        af.grid_columnconfigure(0, weight=1)

        self._entry = ctk.CTkEntry(
            af, placeholder_text="keyword (e.g. peluche)…",
            height=36, font=("Segoe UI", 12),
            fg_color=C_CARD, border_color=C_CARD,
        )
        self._entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._entry.bind("<Return>", lambda _: self._add())

        ctk.CTkButton(af, text="Add", width=72, height=36,
                      fg_color=C_ACCENT, text_color="#111827",
                      command=self._add).grid(row=0, column=1)

        # button row
        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(padx=20, pady=(0, 20), fill="x")
        bf.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(bf, text="Remove Selected", width=150, height=36,
                      fg_color=C_CARD, hover_color="#4b5563",
                      command=self._remove).grid(row=0, column=0, padx=(0, 8))

        ctk.CTkButton(bf, text="Save & Close", width=120, height=36,
                      fg_color=C_GREEN, text_color="#111827",
                      command=self._save).grid(row=0, column=2)

    def _add(self):
        kw = self._entry.get().strip().lower()
        if kw and kw not in self._keywords:
            self._keywords.append(kw)
            self._lb.insert("end", kw)
        self._entry.delete(0, "end")

    def _remove(self):
        sel = self._lb.curselection()
        if sel:
            idx = sel[0]
            self._keywords.pop(idx)
            self._lb.delete(idx)

    def _save(self):
        self._app._cfg["ignore_keywords"] = self._keywords
        try:
            _save_config(self._app._cfg)
        except Exception:
            pass
        n = len(self._keywords)
        self._app._log_write(
            f"{datetime.now().strftime('%H:%M:%S')}  "
            f"Ignore list saved: {n} keyword(s)\n", "info"
        )
        self._app._refresh_table()
        self.destroy()


# ── Main app ──────────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Stock Monitor")
        self.geometry("1380x800")
        self.minsize(980, 620)
        self.configure(fg_color=C_BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._cfg     = _load_config()
        self._state   = StateManager("known_products.json")
        self._q: queue.Queue = queue.Queue()
        self._running = False
        self._thread  = None
        self._next_at: float | None = None
        self._iid_to_url: dict[str, str] = {}

        self._filter_site   = ctk.StringVar(value="All Sites")
        self._filter_status = ctk.StringVar(value="All Status")
        self._search_var    = ctk.StringVar()
        for var in (self._filter_site, self._filter_status, self._search_var):
            var.trace_add("write", lambda *_: self._apply_filters())

        self._build_ui()
        self._refresh_table()
        self._update_stats()
        self._poll_queue()
        self._tick()

    # ── layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_header()
        self._build_stats_bar()
        self._build_main()

    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=0, height=64)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(2, weight=1)
        hdr.grid_propagate(False)

        self._dot = ctk.CTkLabel(hdr, text="●", font=("Segoe UI", 20),
                                  text_color=C_GRAY, width=26)
        self._dot.grid(row=0, column=0, padx=(20, 6), pady=18)

        ctk.CTkLabel(hdr, text="Stock Monitor",
                     font=("Segoe UI", 20, "bold"),
                     text_color=C_TEXT).grid(row=0, column=1, sticky="w", pady=18)

        # Site pills
        pills = ctk.CTkFrame(hdr, fg_color="transparent")
        pills.grid(row=0, column=2, padx=16, sticky="w")
        active = [s for s, c in self._cfg.get("sites", {}).items() if c.get("enabled")]
        for i, s in enumerate(active):
            ctk.CTkLabel(pills, text=SITE_LABEL.get(s, s),
                         font=("Segoe UI", 11, "bold"),
                         fg_color=C_CARD, corner_radius=6,
                         text_color=C_ACCENT,
                         padx=10, pady=3).grid(row=0, column=i, padx=4)

        # Ignore-list button
        ctk.CTkButton(hdr, text="🚫  Ignore", width=100, height=36,
                      font=("Segoe UI", 12),
                      fg_color=C_CARD, hover_color="#4b5563",
                      border_color=C_RED, border_width=1,
                      command=self._open_ignore_dialog
                      ).grid(row=0, column=3, padx=(0, 8), pady=14)

        # Test Notify button
        ctk.CTkButton(hdr, text="🔔  Test", width=90, height=36,
                      font=("Segoe UI", 12),
                      fg_color=C_CARD, hover_color="#4b5563",
                      border_color=C_ORANGE, border_width=1,
                      command=self._test_notification
                      ).grid(row=0, column=4, padx=(0, 8), pady=14)

        # Check Now button
        self._btn_now = ctk.CTkButton(hdr, text="⟳  Check Now", width=120, height=36,
                                       font=("Segoe UI", 12),
                                       fg_color=C_CARD, hover_color=C_CARD,
                                       border_color=C_ACCENT, border_width=1,
                                       state="disabled",
                                       command=self._check_now)
        self._btn_now.grid(row=0, column=5, padx=(0, 10), pady=14)

        # Start / Stop
        self._btn = ctk.CTkButton(hdr, text="▶  Start", width=110, height=36,
                                   font=("Segoe UI", 13, "bold"),
                                   fg_color=C_GREEN, text_color="#111827",
                                   hover_color="#059669",
                                   command=self._toggle)
        self._btn.grid(row=0, column=6, padx=(0, 20), pady=14)

    def _build_stats_bar(self):
        bar = ctk.CTkFrame(self, fg_color="#0d1117", corner_radius=0, height=40)
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(99, weight=1)

        lkw = dict(font=("Segoe UI", 12))
        self._lbl_total    = ctk.CTkLabel(bar, text="—  products",      text_color=C_TEXT,   **lkw)
        self._lbl_in       = ctk.CTkLabel(bar, text="✅  —  in stock",   text_color=C_GREEN,  **lkw)
        self._lbl_out      = ctk.CTkLabel(bar, text="❌  —  out",        text_color=C_RED,    **lkw)
        self._lbl_discount = ctk.CTkLabel(bar, text="",                  text_color=C_GOLD,   **lkw)
        self._lbl_last     = ctk.CTkLabel(bar, text="Last check: —",     text_color=C_GRAY,   **lkw)
        self._lbl_next     = ctk.CTkLabel(bar, text="",                  text_color=C_ACCENT, **lkw)

        def sep(col):
            ctk.CTkLabel(bar, text="│", text_color=C_CARD,
                         font=("Segoe UI", 14)).grid(row=0, column=col, padx=4)

        self._lbl_total.grid(row=0, column=0, padx=(20, 8), pady=8)
        sep(1)
        self._lbl_in.grid(row=0, column=2, padx=8)
        sep(3)
        self._lbl_out.grid(row=0, column=4, padx=8)
        sep(5)
        self._lbl_discount.grid(row=0, column=6, padx=8)
        sep(7)
        self._lbl_last.grid(row=0, column=8, padx=8)
        self._lbl_next.grid(row=0, column=9, padx=(4, 20))

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0)
        main.grid(row=2, column=0, sticky="nsew", padx=14, pady=14)
        main.grid_columnconfigure(0, weight=62)
        main.grid_columnconfigure(1, weight=38)
        main.grid_rowconfigure(0, weight=1)
        self._build_products(main)
        self._build_log(main)

    def _build_products(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=C_PANEL, corner_radius=12)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)

        # ── filter row
        flt = ctk.CTkFrame(panel, fg_color="transparent")
        flt.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        flt.grid_columnconfigure(2, weight=1)

        active    = [s for s, c in self._cfg.get("sites", {}).items() if c.get("enabled")]
        site_opts = ["All Sites"] + [SITE_LABEL.get(s, s) for s in active]
        om_kw     = dict(height=34, fg_color=C_CARD, button_color=C_CARD,
                         dropdown_fg_color=C_CARD, font=("Segoe UI", 12),
                         dropdown_font=("Segoe UI", 12))

        ctk.CTkOptionMenu(flt, values=site_opts, variable=self._filter_site,
                          width=136, **om_kw).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkOptionMenu(flt,
                          values=["All Status", "In Stock", "Out of Stock", "On Sale"],
                          variable=self._filter_status,
                          width=136, **om_kw).grid(row=0, column=1, padx=(0, 8))
        ctk.CTkEntry(flt, textvariable=self._search_var,
                     placeholder_text="🔍  Search products…",
                     height=34, font=("Segoe UI", 12),
                     fg_color=C_CARD, border_color=C_CARD
                     ).grid(row=0, column=2, sticky="ew")

        # ── treeview
        self._style_tree()
        wrap = ctk.CTkFrame(panel, fg_color="transparent")
        wrap.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 4))
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(0, weight=1)

        self._tv = ttk.Treeview(
            wrap,
            columns=("site", "name", "price", "sale", "status"),
            show="headings",
            style="Dark.Treeview",
            selectmode="browse",
        )
        self._tv.heading("site",   text="Site",    anchor="w")
        self._tv.heading("name",   text="Product", anchor="w")
        self._tv.heading("price",  text="Price",   anchor="e")
        self._tv.heading("sale",   text="Sale",    anchor="center")
        self._tv.heading("status", text="Status",  anchor="center")
        self._tv.column("site",   width=110, minwidth=90,  anchor="w",      stretch=False)
        self._tv.column("name",   width=280, minwidth=160, anchor="w")
        self._tv.column("price",  width=76,  minwidth=60,  anchor="e",      stretch=False)
        self._tv.column("sale",   width=90,  minwidth=70,  anchor="center", stretch=False)
        self._tv.column("status", width=130, minwidth=100, anchor="center", stretch=False)

        self._tv.tag_configure("in",   background="#14291e", foreground="#d1fae5")
        self._tv.tag_configure("out",  background="#2a1515", foreground="#9ca3af")
        self._tv.tag_configure("disc", background="#2d2010", foreground="#fde68a")

        self._tv.bind("<Double-Button-1>", self._on_row_open)
        self._tv.bind("<Return>",          self._on_row_open)
        self._tv.bind("<Button-3>",        self._on_row_right_click)

        sb = ttk.Scrollbar(wrap, orient="vertical", command=self._tv.yview)
        self._tv.configure(yscrollcommand=sb.set)
        self._tv.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        # hint + row count
        hint_row = ctk.CTkFrame(panel, fg_color="transparent")
        hint_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))
        hint_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(hint_row,
                     text="↑ Double-click a row to open the product page",
                     font=("Segoe UI", 10), text_color=C_GRAY
                     ).grid(row=0, column=0, sticky="w")
        self._lbl_rows = ctk.CTkLabel(hint_row, text="",
                                       font=("Segoe UI", 11), text_color=C_GRAY)
        self._lbl_rows.grid(row=0, column=1, sticky="e")

    def _style_tree(self):
        s = ttk.Style()
        s.theme_use("default")
        s.configure("Dark.Treeview",
            background=C_PANEL, foreground=C_TEXT,
            fieldbackground=C_PANEL, rowheight=30,
            font=("Segoe UI", 11), borderwidth=0,
        )
        s.configure("Dark.Treeview.Heading",
            background="#0d1117", foreground=C_ACCENT,
            font=("Segoe UI", 11, "bold"), relief="flat",
        )
        s.map("Dark.Treeview",
            background=[("selected", C_ACCENT)],
            foreground=[("selected", "#111827")],
        )

    def _build_log(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=C_PANEL, corner_radius=12)
        panel.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(panel, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hdr, text="Events",
                     font=("Segoe UI", 14, "bold"),
                     text_color=C_TEXT).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(hdr, text="🆕 new  ✅ back  ❌ oos  💰 price  — every entry triggers a notification",
                     font=("Segoe UI", 10),
                     text_color=C_GRAY).grid(row=1, column=0, sticky="w")

        ctk.CTkButton(hdr, text="Clear", width=58, height=28,
                      font=("Segoe UI", 11), fg_color=C_CARD,
                      hover_color="#4b5563",
                      command=self._clear_log).grid(row=0, column=1, rowspan=2)

        self._log_box = ctk.CTkTextbox(panel, font=("Consolas", 11),
                                        fg_color="#0d1117", text_color=C_TEXT,
                                        corner_radius=8, wrap="word",
                                        state="disabled")
        self._log_box.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))

        tw = self._log_box._textbox
        tw.tag_configure("ts",    foreground=C_GRAY)
        tw.tag_configure("site",  foreground=C_ACCENT)
        tw.tag_configure("new",   foreground=C_BLUE)
        tw.tag_configure("back",  foreground=C_GREEN)
        tw.tag_configure("oos",   foreground=C_RED)
        tw.tag_configure("price", foreground=C_ORANGE)
        tw.tag_configure("disc",  foreground=C_GOLD)
        tw.tag_configure("info",  foreground=C_GRAY)
        tw.tag_configure("err",   foreground=C_RED)

        self._log_write("Stock Monitor ready. Press ▶ Start to begin.\n", "info")

    # ── monitoring ────────────────────────────────────────────────────────────

    def _toggle(self):
        if self._running:
            self._running = False
            self._btn.configure(text="▶  Start", fg_color=C_GREEN,
                                 text_color="#111827", hover_color="#059669")
            self._btn_now.configure(state="disabled")
            self._dot.configure(text_color=C_GRAY)
            self._lbl_next.configure(text="")
        else:
            self._running = True
            self._btn.configure(text="■  Stop", fg_color=C_RED,
                                 text_color=C_TEXT, hover_color="#dc2626")
            self._btn_now.configure(state="normal")
            self._dot.configure(text_color=C_GREEN)
            self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._thread.start()

    def _check_now(self):
        if self._running and self._next_at:
            self._next_at = time.time()

    def _monitor_loop(self):
        while self._running:
            self._q.put(("status", "checking"))
            self._run_check()
            if not self._running:
                break
            lo = self._cfg.get("check_interval_min_seconds", 90)
            hi = self._cfg.get("check_interval_max_seconds", 150)
            self._next_at = time.time() + random.uniform(lo, hi)
            while self._running and time.time() < self._next_at:
                time.sleep(0.3)
        self._next_at = None

    def _run_check(self):
        ignore = [kw.lower() for kw in self._cfg.get("ignore_keywords", [])]
        for site, cfg in self._cfg.get("sites", {}).items():
            if not self._running:
                break
            if not cfg.get("enabled", True):
                continue
            cls = SCRAPER_MAP.get(site)
            if not cls:
                continue
            try:
                products = cls(cfg["url"]).fetch_products()
                if ignore and products:
                    products = {
                        pid: p for pid, p in products.items()
                        if not any(kw in p.get("name", "").lower() for kw in ignore)
                    }
                if not products:
                    self._q.put(("warn", site, "0 products returned — skipping"))
                    continue
                if self._state.is_first_run_for_site(site):
                    self._state.initialize_site(site, products)
                    self._q.put(("baseline", site, len(products)))
                else:
                    old = self._state.get_site_state(site)
                    # Also strip ignored products from the old state so that
                    # filtering them from new results doesn't look like a
                    # disappearance and fire spurious out_of_stock events.
                    if ignore:
                        old = {pid: p for pid, p in old.items()
                               if not any(kw in p.get("name", "").lower()
                                          for kw in ignore)}
                    for ev in self._state.diff_products(old, products):
                        self._q.put(("event", site, ev))
                    self._state.update_site_state(site, products)
                time.sleep(random.uniform(1, 3))
            except Exception as e:
                self._q.put(("err", site, str(e)[:120]))
        self._state.save()
        self._q.put(("done", datetime.now()))

    # ── queue polling ─────────────────────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                item = self._q.get_nowait()
                k = item[0]
                if k == "status":
                    self._dot.configure(text_color=C_ORANGE)
                    self._lbl_next.configure(text="Checking…")
                elif k == "baseline":
                    _, site, n = item
                    self._log_write(
                        f"{datetime.now().strftime('%H:%M:%S')}  "
                        f"[{SITE_LABEL.get(site, site)}] baseline: {n} products\n", "info"
                    )
                    self._refresh_table()
                    self._update_stats()
                elif k == "event":
                    _, site, ev = item
                    self._log_event(site, ev)
                    self._refresh_table()
                    self._update_stats()
                elif k == "warn":
                    _, site, msg = item
                    self._log_write(
                        f"{datetime.now().strftime('%H:%M:%S')}  "
                        f"[{SITE_LABEL.get(site, site)}] ⚠ {msg}\n", "info"
                    )
                elif k == "err":
                    _, site, msg = item
                    self._log_write(
                        f"{datetime.now().strftime('%H:%M:%S')}  "
                        f"[{SITE_LABEL.get(site, site)}] ERROR: {msg}\n", "err"
                    )
                elif k == "done":
                    t = item[1].strftime("%H:%M:%S")
                    self._lbl_last.configure(text=f"Last check: {t}")
                    self._dot.configure(text_color=C_GREEN)
                    self._refresh_table()
                    self._update_stats()
        except queue.Empty:
            pass
        self.after(400, self._poll_queue)

    # ── table ─────────────────────────────────────────────────────────────────

    def _refresh_table(self):
        self._rows = []
        ignore = [kw.lower() for kw in self._cfg.get("ignore_keywords", [])]
        for site, products in self._state._state.items():
            if not isinstance(products, dict):
                continue
            label = SITE_LABEL.get(site, site)
            for pid, p in products.items():
                name = p.get("name", "?")
                if ignore and any(kw in name.lower() for kw in ignore):
                    continue
                in_s  = p.get("in_stock", True)
                price = f"€{p['price']}" if p.get("price") else "—"
                url   = p.get("url") or SITE_URL.get(site, "")
                disc  = _compute_discount(p.get("original_price"), p.get("price"))
                self._rows.append((label, name, price, disc,
                                   "✅  In Stock" if in_s else "❌  Out of Stock",
                                   in_s, url))
        self._apply_filters()

    def _apply_filters(self):
        sf = self._filter_site.get()
        st = self._filter_status.get()
        q  = self._search_var.get().lower()

        for i in self._tv.get_children():
            self._tv.delete(i)

        self._iid_to_url = {}
        shown = 0

        for site, name, price, disc, status, in_s, url in self._rows:
            if sf != "All Sites"    and site != sf:                       continue
            if st == "In Stock"     and not in_s:                         continue
            if st == "Out of Stock" and in_s:                             continue
            if st == "On Sale"      and not disc:                         continue
            if q and q not in name.lower() and q not in site.lower():     continue

            if disc and in_s:
                tag = "disc"
            elif in_s:
                tag = "in"
            else:
                tag = "out"

            iid = self._tv.insert("", "end",
                                  values=(site, name, price, disc, status),
                                  tags=(tag,))
            self._iid_to_url[iid] = url
            shown += 1

        total = len(self._rows)
        self._lbl_rows.configure(
            text=f"Showing {shown} of {total}" if shown != total else f"{total} products"
        )

    def _update_stats(self):
        total = in_s = out_s = disc_count = 0
        ignore = [kw.lower() for kw in self._cfg.get("ignore_keywords", [])]
        for site, products in self._state._state.items():
            if not isinstance(products, dict):
                continue
            for pid, p in products.items():
                if ignore and any(kw in p.get("name", "").lower() for kw in ignore):
                    continue
                total += 1
                if p.get("in_stock", True):
                    in_s += 1
                else:
                    out_s += 1
                if _compute_discount(p.get("original_price"), p.get("price")):
                    disc_count += 1
        self._lbl_total.configure(text=f"{total}  products")
        self._lbl_in.configure(text=f"✅  {in_s}  in stock")
        self._lbl_out.configure(text=f"❌  {out_s}  out of stock")
        self._lbl_discount.configure(
            text=f"💰  {disc_count}  on sale" if disc_count else ""
        )

    # ── click to open ─────────────────────────────────────────────────────────

    def _on_row_open(self, event=None):
        sel = self._tv.selection()
        if not sel:
            return
        url = self._iid_to_url.get(sel[0])
        if url:
            webbrowser.open(url)

    # ── ignore list ───────────────────────────────────────────────────────────

    def _open_ignore_dialog(self):
        IgnoreListDialog(self)

    def _on_row_right_click(self, event):
        iid = self._tv.identify_row(event.y)
        if not iid:
            return
        self._tv.selection_set(iid)
        values = self._tv.item(iid, "values")
        if not values:
            return
        name = values[1]  # product name column

        menu = tk.Menu(self, tearoff=0,
                       bg=C_CARD, fg=C_TEXT,
                       activebackground=C_ACCENT, activeforeground="#111827",
                       relief="flat", bd=0, font=("Segoe UI", 11))
        short = name[:45] + "…" if len(name) > 45 else name
        menu.add_command(label=f"🚫  Ignore  \"{short}\"",
                         command=lambda n=name: self._add_to_ignore(n))
        menu.add_separator()
        menu.add_command(label="🔗  Open product page",
                         command=self._on_row_open)
        menu.add_command(label="✏  Manage ignore list…",
                         command=self._open_ignore_dialog)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _add_to_ignore(self, name: str):
        keywords = list(self._cfg.get("ignore_keywords", []))
        name_lower = name.lower()
        if name_lower not in keywords:
            keywords.append(name_lower)
            self._cfg["ignore_keywords"] = keywords
            try:
                _save_config(self._cfg)
            except Exception:
                pass
            self._log_write(
                f"{datetime.now().strftime('%H:%M:%S')}  "
                f"Ignored: \"{name}\"\n", "info"
            )
            self._refresh_table()
            self._update_stats()

    # ── log ───────────────────────────────────────────────────────────────────

    def _log_event(self, site: str, event: dict):
        p      = event["product"]
        name   = p.get("name", "?")[:52]
        pstr   = f"€{p['price']}" if p.get("price") else ""
        t      = event["type"]
        icon, tag = EVENT_TAG.get(t, ("•", "info"))
        slabel = SITE_LABEL.get(site, site)
        ts     = datetime.now().strftime("%H:%M:%S")

        if t == "new_product":
            stk  = "IN STOCK" if p.get("in_stock") else "OUT OF STOCK"
            body = f"{icon} {name}  {pstr}  ({stk})\n"
        elif t == "back_in_stock":
            body = f"{icon} {name}  {pstr}  — BACK IN STOCK\n"
        elif t == "out_of_stock":
            body = f"{icon} {name}  — OUT OF STOCK\n"
        elif t == "price_change":
            try:
                old_p = float(event.get("old_price") or 0)
                new_p = float(p.get("price") or 0)
                if old_p > 0 and new_p > 0 and new_p < old_p:
                    pct  = round((old_p - new_p) / old_p * 100)
                    body = f"{icon} {name}  €{event.get('old_price','?')} → {pstr}  ↓ -{pct}% OFF\n"
                    tag  = "disc"
                else:
                    body = f"{icon} {name}  €{event.get('old_price','?')} → {pstr}\n"
            except (ValueError, TypeError):
                body = f"{icon} {name}  €{event.get('old_price','?')} → {pstr}\n"
        else:
            body = f"{icon} {name}\n"

        tw = self._log_box._textbox
        tw.configure(state="normal")
        tw.insert("end", f"{ts}  ", "ts")
        tw.insert("end", f"[{slabel}]  ", "site")
        tw.insert("end", body, tag)
        tw.see("end")
        tw.configure(state="disabled")

    def _log_write(self, text: str, tag: str = "info"):
        tw = self._log_box._textbox
        tw.configure(state="normal")
        tw.insert("end", text, tag)
        tw.see("end")
        tw.configure(state="disabled")

    def _clear_log(self):
        tw = self._log_box._textbox
        tw.configure(state="normal")
        tw.delete("1.0", "end")
        tw.configure(state="disabled")

    # ── test notification ─────────────────────────────────────────────────────

    def _test_notification(self):
        try:
            send_notification(
                title="Stock Monitor — Test Alert",
                message="🆕 Pokémon EX Box — €29.99 (IN STOCK)\n"
                        "💰 Booster Bundle — €19.99 → €14.99 ↓ -25%  [ToysRus]",
            )
            self._log_write(
                f"{datetime.now().strftime('%H:%M:%S')}  Test notification sent.\n", "info"
            )
        except Exception as e:
            self._log_write(
                f"{datetime.now().strftime('%H:%M:%S')}  Notification test failed: {e}\n", "err"
            )

    # ── countdown ─────────────────────────────────────────────────────────────

    def _tick(self):
        if self._running and self._next_at:
            rem = max(0, self._next_at - time.time())
            m, s = divmod(int(rem), 60)
            self._lbl_next.configure(text=f"Next: {m}m {s:02d}s")
        self.after(1000, self._tick)

    def _on_close(self):
        self._running = False
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
