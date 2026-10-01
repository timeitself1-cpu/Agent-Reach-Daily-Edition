"""Agent Reach Daily desktop window (tkinter/ttk, no extra dependencies).

Run with ``pythonw -m agent_reach.daily`` or double-click ``AgentReachDaily.pyw`` (no console
window). The window renders cached editions only; refreshes run in a background worker process
and report progress through the data folder, polled once per second while a refresh runs and
every 30 seconds otherwise. Everything the window shows is computed by ``app.AppController``
(no Tk), so it can be tested without a display.

Untrusted source and model text is only ever inserted into a Tk Text widget as plain text (it
is never interpreted as markup), and only absolute http(s) URLs open in the browser.
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import date
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from agent_reach.daily import APP_NAME, VERSION_LABEL
from agent_reach.daily.app import (
    AppController,
    Snapshot,
    details_report,
    filter_stories,
    load_window_geometry,
    publisher_breakdown,
    resolve_appearance,
    save_window_geometry,
    story_age,
    story_publishers,
)
from agent_reach.daily.edition import Story, all_categories, friendly_error, health_summary, safe_url
from agent_reach.daily.paths import DataPaths
from agent_reach.daily.feeds import FeedSpec, default_feeds
from agent_reach.daily.prefs import DailyPrefs, SOURCE_NOTES, save_prefs
from agent_reach.daily.timeutil import format_central, format_short_date

log = logging.getLogger(__name__)

STATUS_DOT = {"current": "#188038", "stale": "#b06000", "refreshing": "#1a73e8", "failed": "#c5221f",
              "empty": "#80868b", "demo": "#a50e0e", "archive": "#5f6368"}

#: Light and dark palettes. Chip/banner pairs are (background, text) with readable contrast in each.
PALETTES: dict[str, dict] = {
    "light": {
        "bg": "#f6f5f2", "card": "#ffffff", "ink": "#1d1d1f", "muted": "#5f6368", "accent": "#1a5fb4",
        "link": "#1a5fb4", "rule": "#e2e0da", "rank": "#9aa0a6", "field": "#ffffff", "button": "#ecebe7",
        "button_active": "#e0dfda", "select": "#cfe0fc", "ok": "#137333", "bad": "#a50e0e",
        "categories": {
            "News": ("#e8f0fe", "#1a4fa0"), "Sports": ("#e6f4ea", "#137333"), "Entertainment": ("#fce8f3", "#a1145c"),
            "Tech": ("#eceff1", "#37474f"), "Science & AI": ("#fef7e0", "#7a4f00"),
            "Internet Culture": ("#f3e8fd", "#6a1b9a")},
        "labels": {
            "Hot": ("#fde2e1", "#a50e0e"), "Rising": ("#fef0d9", "#8a4b00"), "New": ("#e0f2f1", "#00695c"),
            "Uncertain trend": ("#eceff1", "#455a64"), "Continuing": ("#f1f3f4", "#3c4043"),
            "Steady": ("#f1f3f4", "#3c4043"), "Cooling": ("#f1f3f4", "#5f6368"), "Fading": ("#f1f3f4", "#5f6368")},
        "banners": {"info": ("#e8f0fe", "#174ea6"), "warn": ("#fff4d6", "#6b4e00"),
                    "error": ("#fce8e6", "#a50e0e"), "demo": ("#ffd7d7", "#8a1010")},
    },
    "dark": {
        "bg": "#17181a", "card": "#202124", "ink": "#e8eaed", "muted": "#a8adb3", "accent": "#8ab4f8",
        "link": "#8ab4f8", "rule": "#3c4043", "rank": "#7c8187", "field": "#2a2b2e", "button": "#2d2f33",
        "button_active": "#3c4043", "select": "#3b4a63", "ok": "#81c995", "bad": "#f28b82",
        "categories": {
            "News": ("#1f2a3d", "#aecbfa"), "Sports": ("#1e3a2a", "#81c995"), "Entertainment": ("#3d1f33", "#f8a5d2"),
            "Tech": ("#2d3236", "#cfd8dc"), "Science & AI": ("#3a3018", "#fdd663"),
            "Internet Culture": ("#2f1f3d", "#d7aefb")},
        "labels": {
            "Hot": ("#3c1f1f", "#f28b82"), "Rising": ("#3d2d14", "#fcc66b"), "New": ("#173a36", "#80cbc4"),
            "Uncertain trend": ("#2d3236", "#bdc1c6"), "Continuing": ("#2d3236", "#e8eaed"),
            "Steady": ("#2d3236", "#e8eaed"), "Cooling": ("#2d3236", "#a8adb3"), "Fading": ("#2d3236", "#a8adb3")},
        "banners": {"info": ("#1f2a3d", "#aecbfa"), "warn": ("#3a3018", "#fdd663"),
                    "error": ("#3c1f1f", "#f28b82"), "demo": ("#4a1d1d", "#ffc9c9")},
    },
}


def dark_title_bar(window: tk.Misc, dark: bool) -> None:
    """Ask Windows 10/11 to draw this window's title bar dark or light (best effort)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (newer, older builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except (AttributeError, OSError):
        pass


POLL_RUNNING_MS = 1000
POLL_IDLE_MS = 30000


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


class DailyWindow:
    def __init__(self, root: tk.Tk, paths: DataPaths, controller: AppController | None = None,
                 auto_refresh: bool = True) -> None:
        self.root = root
        self.paths = paths
        self.ctrl = controller or AppController(paths)
        self.snap: Snapshot | None = None
        self._rendered_key: tuple | None = None
        self._banner_key: tuple | None = None
        self._links: dict[str, str] = {}
        self._date_values: list[date] = []
        self._expanded: set[str] = set()
        self._prereq_q: queue.Queue = queue.Queue()
        self._prereq_text: str | None = None  # None until a check starts
        self._poll_job: str | None = None
        self._cancelling = False
        # 1.0 at 96 DPI; pixel sizes scale with Windows display scaling (fonts scale by themselves)
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)

        prefs0 = self.ctrl.snapshot().prefs
        self.mode = resolve_appearance(prefs0.appearance)
        self.c = PALETTES[self.mode]
        root.title(APP_NAME)
        root.minsize(self.px(760), self.px(540))
        root.geometry(load_window_geometry(paths) or f"{self.px(1060)}x{self.px(800)}")
        root.report_callback_exception = self._callback_error
        self._fonts()
        self._style()
        self._build_menu()
        self._build()
        self.apply_theme(self.mode)
        self.refresh_view(force=True)
        if auto_refresh:
            root.after(1200, self._launch_check)
        self._schedule_poll()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    def px(self, n: float) -> int:
        return int(round(n * self.scale))

    # ------------------------------------------------------------ setup
    def _fonts(self) -> None:
        family = "Segoe UI" if sys.platform == "win32" else "TkDefaultFont"
        f = lambda size, **kw: tkfont.Font(family=family, size=size, **kw)  # noqa: E731
        self.f_base = f(11)
        self.f_small = f(9)
        self.f_brand = f(9, weight="bold")
        self.f_heading = f(22, weight="bold")
        self.f_sub = f(12)
        self.f_status = f(10, weight="bold")
        self.f_rank = f(15, weight="bold")
        self.f_title = f(15, weight="bold")
        self.f_bold = f(11, weight="bold")
        self.f_chip = f(9, weight="bold")
        self.f_kicker = f(9, weight="bold")
        self.f_overview = f(12)
        self.f_link = f(10, underline=True)
        self.f_small_link = f(9, underline=True)
        self.f_tiny = f(3)
        self.f_button = f(11, weight="bold")

    def _style(self) -> None:
        """ttk styles for the current palette. Dark mode needs the recolourable 'clam' theme
        (the native 'vista' theme ignores colours); light mode keeps the native look on Windows."""
        c = self.c
        style = ttk.Style(self.root)
        names = style.theme_names()
        style.theme_use("vista" if self.mode == "light" and "vista" in names else "clam" if "clam" in names else style.theme_use())
        if style.theme_use() == "clam":
            style.configure(".", background=c["bg"], foreground=c["ink"], fieldbackground=c["field"],
                            bordercolor=c["rule"], lightcolor=c["bg"], darkcolor=c["bg"], troughcolor=c["button"],
                            selectbackground=c["select"], selectforeground=c["ink"], insertcolor=c["ink"],
                            arrowcolor=c["ink"], focuscolor=c["accent"])
            style.configure("TButton", background=c["button"], foreground=c["ink"], bordercolor=c["rule"])
            style.map("TButton", background=[("disabled", c["bg"]), ("active", c["button_active"])],
                      foreground=[("disabled", c["muted"])])
            style.configure("TEntry", fieldbackground=c["field"], foreground=c["ink"])
            style.configure("TSpinbox", fieldbackground=c["field"], foreground=c["ink"], background=c["button"])
            style.configure("TCombobox", fieldbackground=c["field"], background=c["button"], foreground=c["ink"])
            style.map("TCombobox", fieldbackground=[("readonly", c["field"])], foreground=[("readonly", c["ink"])],
                      selectbackground=[("readonly", c["field"])], selectforeground=[("readonly", c["ink"])])
            style.configure("Treeview", background=c["card"], fieldbackground=c["card"], foreground=c["ink"])
            style.map("Treeview", background=[("selected", c["select"])], foreground=[("selected", c["ink"])])
            style.configure("Treeview.Heading", background=c["button"], foreground=c["ink"])
            style.configure("TNotebook", background=c["bg"], bordercolor=c["rule"])
            style.configure("TNotebook.Tab", background=c["button"], foreground=c["ink"])
            style.map("TNotebook.Tab", background=[("selected", c["card"])])
            for name in ("TFrame", "TLabel", "TCheckbutton", "TRadiobutton", "TLabelframe", "TLabelframe.Label"):
                style.configure(name, background=c["bg"], foreground=c["ink"])
            style.map("TCheckbutton", background=[("active", c["bg"])])
            style.map("TRadiobutton", background=[("active", c["bg"])])
            style.configure("Horizontal.TProgressbar", background=c["accent"], troughcolor=c["button"])
            for name in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
                style.configure(name, background=c["button"], troughcolor=c["bg"], bordercolor=c["rule"],
                                arrowcolor=c["muted"])
                style.map(name, background=[("active", c["button_active"])])
            self.root.option_add("*TCombobox*Listbox.background", c["field"])
            self.root.option_add("*TCombobox*Listbox.foreground", c["ink"])
            self.root.option_add("*TCombobox*Listbox.selectBackground", c["select"])
            self.root.option_add("*TCombobox*Listbox.selectForeground", c["ink"])
        style.configure("Header.TFrame", background=c["bg"])
        style.configure("Header.TLabel", background=c["bg"], foreground=c["ink"])
        style.configure("Brand.TLabel", background=c["bg"], foreground=c["accent"], font=self.f_brand)
        style.configure("Muted.TLabel", background=c["bg"], foreground=c["muted"], font=self.f_small)
        style.configure("Refresh.TButton", font=self.f_button, padding=(self.px(16), self.px(7)))
        style.configure("Small.TButton", font=self.f_small, padding=(self.px(6), self.px(2)))

    def apply_theme(self, mode: str) -> None:
        """Switch between the light and dark palettes without restarting."""
        self.mode = mode if mode in PALETTES else "light"
        self.c = c = PALETTES[self.mode]
        self._style()
        self.root.configure(bg=c["bg"])
        for w in (self.status_row, self.banner_frame, self.body_frame):
            w.configure(bg=c["bg"])
        self.status_dot.configure(bg=c["bg"])
        self.status_label.configure(bg=c["bg"], fg=c["ink"])
        self.times_label.configure(bg=c["bg"], fg=c["muted"])
        self.text.configure(bg=c["card"], fg=c["ink"], insertbackground=c["ink"], selectbackground=c["select"],
                            selectforeground=c["ink"], highlightbackground=c["rule"], highlightcolor=c["rule"])
        self._text_tags()
        dark_title_bar(self.root, self.mode == "dark")
        self._banner_key = None
        if self.snap is not None:
            self.refresh_view(force=True)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        m_file = tk.Menu(menubar, tearoff=False)
        m_file.add_command(label="Export edition as HTML...", accelerator="Ctrl+E", command=self.export_html)
        m_file.add_separator()
        m_file.add_command(label="Open data folder", command=lambda: self._open_path(self.paths.root))
        m_file.add_command(label="Open logs folder", command=lambda: self._open_path(self.paths.logs_dir))
        m_file.add_separator()
        m_file.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=m_file)
        m_view = tk.Menu(menubar, tearoff=False)
        m_view.add_command(label="Latest edition", accelerator="Home", command=self.show_latest)
        m_view.add_command(label="Details and source health...", accelerator="Ctrl+D", command=self.show_details)
        m_view.add_separator()
        m_view.add_command(label="Expand all source details", command=lambda: self._expand_all(True))
        m_view.add_command(label="Collapse all source details", command=lambda: self._expand_all(False))
        m_view.add_separator()
        m_view.add_command(label="Demo edition (NOT real news)", command=self.show_demo)
        menubar.add_cascade(label="View", menu=m_view)
        m_tools = tk.Menu(menubar, tearoff=False)
        m_tools.add_command(label="Refresh now", accelerator="F5", command=self.refresh_now)
        m_tools.add_command(label="Check local model (Ollama)", command=self._start_prereq_check)
        m_tools.add_command(label="Settings...", command=self.open_settings)
        menubar.add_cascade(label="Tools", menu=m_tools)
        m_help = tk.Menu(menubar, tearoff=False)
        m_help.add_command(label="How refreshing works", command=self.show_help)
        m_help.add_command(label="About", command=lambda: messagebox.showinfo(
            APP_NAME, f"{APP_NAME} {VERSION_LABEL}\n\nLocal daily news from public sources, summarized on this PC "
                      f"by a local model (Ollama). No paid or cloud AI service is used.\n\nData folder:\n{self.paths.root}",
            parent=self.root))
        menubar.add_cascade(label="Help", menu=m_help)
        self.root.config(menu=menubar)
        for seq in ("<F5>", "<Control-r>"):
            self.root.bind(seq, lambda e: self.refresh_now())
        self.root.bind("<Control-e>", lambda e: self.export_html())
        self.root.bind("<Control-d>", lambda e: self.show_details())
        self.root.bind("<Control-f>", lambda e: self.search_entry.focus_set())
        self.root.bind("<Home>", lambda e: self.text.yview_moveto(0))
        self.root.bind("<End>", lambda e: self.text.yview_moveto(1))
        self.root.bind("<Prior>", lambda e: self.text.yview_scroll(-1, "pages"))
        self.root.bind("<Next>", lambda e: self.text.yview_scroll(1, "pages"))

    def _build(self) -> None:
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)
        pad = self.px(20)

        # ---- header: brand, title, date, status | Refresh
        header = ttk.Frame(root, style="Header.TFrame", padding=(pad, self.px(12), pad, self.px(4)))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.heading_var = tk.StringVar()
        self.date_line_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.times_var = tk.StringVar()
        ttk.Label(header, text="AGENT REACH  ·  DAILY EDITION", style="Brand.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.heading_var, style="Header.TLabel", font=self.f_heading).grid(
            row=1, column=0, sticky="w")
        ttk.Label(header, textvariable=self.date_line_var, style="Header.TLabel", font=self.f_sub).grid(
            row=2, column=0, sticky="w")
        self.status_row = status_row = tk.Frame(header, bg=self.c["bg"])
        status_row.grid(row=3, column=0, sticky="ew", pady=(self.px(8), 0))
        status_row.columnconfigure(1, weight=1)
        self.status_dot = tk.Canvas(status_row, width=self.px(12), height=self.px(12), bg=self.c["bg"],
                                    highlightthickness=0)
        self.status_dot.grid(row=0, column=0, sticky="w", padx=(0, self.px(6)))
        self.status_label = tk.Label(status_row, textvariable=self.status_var, bg=self.c["bg"], fg=self.c["ink"],
                                     font=self.f_status,
                                     anchor="w", justify="left")
        self.status_label.grid(row=0, column=1, sticky="ew")
        self.times_label = tk.Label(header, textvariable=self.times_var, bg=self.c["bg"], fg=self.c["muted"],
                                    font=self.f_small,
                                    anchor="w", justify="left")
        self.times_label.grid(row=4, column=0, sticky="ew", pady=(self.px(2), 0))
        for lbl in (self.status_label, self.times_label):  # wrap to the real column width
            lbl.configure(wraplength=self.px(420))
            lbl.bind("<Configure>", lambda e: e.widget.configure(wraplength=max(self.px(200), e.width - 2)))

        right = ttk.Frame(header, style="Header.TFrame")
        right.grid(row=0, column=1, rowspan=5, sticky="ne", padx=(self.px(12), 0))
        self.refresh_btn = ttk.Button(right, text="Refresh", style="Refresh.TButton", command=self.refresh_now)
        self.refresh_btn.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.progress = ttk.Progressbar(right, mode="indeterminate", length=self.px(150))
        self.cancel_btn = ttk.Button(right, text="Cancel refresh", style="Small.TButton", command=self.cancel_refresh)
        links = ttk.Frame(right, style="Header.TFrame")
        links.grid(row=3, column=0, columnspan=3, sticky="e", pady=(self.px(8), 0))
        ttk.Button(links, text="Details", style="Small.TButton", command=self.show_details).pack(side="left")
        ttk.Button(links, text="Export", style="Small.TButton", command=self.export_html).pack(side="left", padx=self.px(4))
        ttk.Button(links, text="Settings", style="Small.TButton", command=self.open_settings).pack(side="left")

        # ---- filter bar: grid with a stretchy search box, so it shrinks instead of clipping controls
        bar = ttk.Frame(root, style="Header.TFrame", padding=(pad, self.px(6), pad, self.px(6)))
        bar.grid(row=1, column=0, sticky="ew")
        bar.columnconfigure(5, weight=1)
        gap = (self.px(4), self.px(12))
        ttk.Label(bar, text="Edition", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        self.date_var = tk.StringVar()
        self.date_box = ttk.Combobox(bar, textvariable=self.date_var, state="readonly", width=21)
        self.date_box.grid(row=0, column=1, sticky="w", padx=gap)
        self.date_box.bind("<<ComboboxSelected>>", self._on_date)
        ttk.Label(bar, text="Category", style="Header.TLabel").grid(row=0, column=2, sticky="w")
        self.cat_var = tk.StringVar(value="All")
        self.cat_box = ttk.Combobox(bar, textvariable=self.cat_var, state="readonly", width=14,
                                    values=["All", *all_categories()])
        self.cat_box.grid(row=0, column=3, sticky="w", padx=gap)
        self.cat_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_view(force=True))
        ttk.Label(bar, text="Search", style="Header.TLabel").grid(row=0, column=4, sticky="w")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(bar, textvariable=self.search_var, width=12)
        self.search_entry.grid(row=0, column=5, sticky="ew", padx=(self.px(4), self.px(4)))
        self.search_entry.bind("<Escape>", lambda e: self._clear_filters())
        self.search_var.trace_add("write", lambda *a: self.refresh_view(force=True))
        ttk.Button(bar, text="Clear", style="Small.TButton", command=self._clear_filters).grid(row=0, column=6, sticky="e")

        self.banner_frame = tk.Frame(root, bg=self.c["bg"], padx=pad)
        self.banner_frame.grid(row=2, column=0, sticky="ew")

        # ---- reading area
        self.body_frame = body = tk.Frame(root, bg=self.c["bg"], padx=pad, pady=self.px(4))
        body.grid(row=3, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.text = tk.Text(body, wrap="word", bg=self.c["card"], fg=self.c["ink"], relief="flat", bd=0, padx=self.px(26),
                            pady=self.px(18), font=self.f_base, cursor="arrow", highlightthickness=1,
                            highlightbackground=self.c["rule"], highlightcolor=self.c["rule"], spacing1=1, spacing3=1,
                            takefocus=1)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.bind("<Button-1>", lambda e: self.text.focus_set(), add="+")
        self._text_tags()

        footer = ttk.Frame(root, style="Header.TFrame", padding=(pad, self.px(2), pad, self.px(8)))
        footer.grid(row=4, column=0, sticky="ew")
        self.footer_var = tk.StringVar()
        ttk.Label(footer, textvariable=self.footer_var, style="Muted.TLabel").pack(side="left")
        ttk.Label(footer, text=VERSION_LABEL, style="Muted.TLabel").pack(side="right")
        self.root.bind("<Configure>", self._on_resize)

    def _text_tags(self) -> None:
        t = self.text
        c = self.c
        indent = self.px(46)
        t.tag_configure("overview", font=self.f_overview, foreground=c["ink"], spacing3=self.px(6))
        t.tag_configure("baseline", font=self.f_small, foreground=c["muted"], spacing3=self.px(4))
        t.tag_configure("headline", font=self.f_title, lmargin1=0, lmargin2=indent, tabs=(indent,),
                        spacing1=self.px(4), spacing3=self.px(2))
        t.tag_configure("rank", font=self.f_rank, foreground=c["rank"])
        t.tag_configure("meta", font=self.f_small, foreground=c["muted"], lmargin1=indent, lmargin2=indent,
                        spacing3=self.px(4))
        t.tag_configure("body", font=self.f_base, lmargin1=indent, lmargin2=indent, spacing1=self.px(2),
                        spacing3=self.px(2))
        t.tag_configure("kicker", font=self.f_kicker, foreground=c["accent"], lmargin1=indent, lmargin2=indent,
                        spacing1=self.px(8))
        t.tag_configure("why", font=self.f_base, lmargin1=indent, lmargin2=indent, spacing1=self.px(2))
        t.tag_configure("sources", font=self.f_small, foreground=c["muted"], lmargin1=indent, lmargin2=indent,
                        spacing1=self.px(8))
        t.tag_configure("evidence", font=self.f_small, lmargin1=indent + self.px(12), lmargin2=indent + self.px(24),
                        spacing1=self.px(4))
        t.tag_configure("excerpt", font=self.f_small, foreground=c["muted"], lmargin1=indent + self.px(24),
                        lmargin2=indent + self.px(24))
        t.tag_configure("link", font=self.f_link, foreground=c["link"])
        t.tag_configure("small_link", font=self.f_small_link, foreground=c["link"])
        for tag in ("link", "small_link"):
            t.tag_bind(tag, "<Enter>", lambda e: t.configure(cursor="hand2"))
            t.tag_bind(tag, "<Leave>", lambda e: t.configure(cursor="arrow"))
        t.tag_configure("sep", font=self.f_tiny, spacing1=self.px(14), spacing3=self.px(14))
        t.tag_configure("rule", font=self.f_tiny, background=c["rule"])
        t.tag_configure("h2", font=self.f_title, spacing1=self.px(6), spacing3=self.px(6))
        t.tag_configure("plain", font=self.f_base, spacing1=self.px(2), spacing3=self.px(2))
        t.tag_configure("muted", foreground=c["muted"])
        t.tag_configure("ok", foreground=c["ok"], font=self.f_bold)
        t.tag_configure("bad", foreground=c["bad"], font=self.f_bold)
        t.tag_configure("bold", font=self.f_bold)
        for name, (bg, fg) in {**c["categories"], **c["labels"]}.items():
            # lmargincolor: a line that starts with a chip must not paint its left margin too
            t.tag_configure(f"chip:{name}", background=bg, foreground=fg, font=self.f_chip, lmargincolor=c["card"])

    # ------------------------------------------------------------ polling / render
    def _schedule_poll(self) -> None:
        """Exactly one pending poll: 1 s while a refresh runs, 30 s otherwise."""
        if self._poll_job is not None:
            try:
                self.root.after_cancel(self._poll_job)
            except tk.TclError:
                pass
        running = bool(self.snap and self.snap.activity.running)
        self._poll_job = self.root.after(POLL_RUNNING_MS if running else POLL_IDLE_MS, self._poll)

    def _poll(self) -> None:
        self._poll_job = None
        self._drain_prereq()
        try:
            self.refresh_view()
        except Exception:  # noqa: BLE001 - a polling hiccup must not kill the window
            log.exception("refresh_view failed")
        self._schedule_poll()

    def refresh_view(self, force: bool = False) -> None:
        was_running = bool(self.snap and self.snap.activity.running)
        snap = self.ctrl.snapshot()
        self.snap = snap
        self.heading_var.set(snap.heading)
        self.date_line_var.set(snap.date_line)
        self.status_var.set(snap.status)
        self._draw_dot(snap.status_kind)
        times = [snap.last_success]
        if snap.next_refresh:
            times.append(snap.next_refresh)
        self.times_var.set("   \u00b7   ".join(times))
        if snap.activity.running or self._cancelling:
            self.refresh_btn.state(["disabled"])
            self.refresh_btn.configure(text="Refreshing...")
            self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(self.px(6), 0))
            self.cancel_btn.grid(row=2, column=0, columnspan=3, sticky="e", pady=(self.px(4), 0))
            self.progress.start(12)
            if self._cancelling:
                self.cancel_btn.state(["disabled"])
            if not was_running:
                self._schedule_poll()
        else:
            self.refresh_btn.state(["!disabled"])
            self.refresh_btn.configure(text="Refresh")
            self.cancel_btn.state(["!disabled"])
            self.progress.stop()
            self.progress.grid_remove()
            self.cancel_btn.grid_remove()
        self._render_banners(snap)
        self._update_dates(snap)
        shown = snap.shown
        if shown is not None:
            self.footer_var.set(f"{snap.coverage_line}   ·   Summaries by "
                                + (f"local model {shown.model.llm_model}" if shown.model.summaries == "local_model"
                                   else "source lead sentences (local model not used)"))
        else:
            self.footer_var.set(f"Data folder: {self.paths.root}")
        key = (shown.edition_date, shown.revision, shown.demo, shown.run_id) if shown else ("none", snap.first_run,
                                                                                          snap.activity.running)
        key = key + (self.cat_var.get(), self.search_var.get(), tuple(sorted(self._expanded)),
                     self._prereq_text if shown is None else "", snap.state.last_attempt_outcome)
        if force or key != self._rendered_key:
            self._rendered_key = key
            self._render_body(snap)

    def _draw_dot(self, kind: str) -> None:
        c = self.status_dot
        c.delete("all")
        d = self.px(10)
        c.create_oval(1, 1, d, d, fill=STATUS_DOT.get(kind, self.c["muted"]), outline="")

    def _render_banners(self, snap: Snapshot) -> None:
        key = tuple((b.kind, b.text) for b in snap.banners)
        if key == self._banner_key:
            return
        self._banner_key = key
        for child in self.banner_frame.winfo_children():
            child.destroy()
        if not snap.banners:
            self.banner_frame.grid_remove()  # an emptied frame would otherwise keep its old height
            return
        self.banner_frame.grid()
        width = max(self.px(400), self.root.winfo_width() - self.px(60))
        for b in snap.banners[:4]:
            bg, fg = self.c["banners"].get(b.kind, self.c["banners"]["info"])
            tk.Label(self.banner_frame, text=b.text, bg=bg, fg=fg, anchor="w", justify="left", wraplength=width,
                     font=self.f_bold if b.kind in ("demo", "error") else self.f_small,
                     padx=self.px(12), pady=self.px(6)).pack(fill="x", pady=(self.px(2), self.px(2)))

    def _on_resize(self, event) -> None:
        if event.widget is self.root:
            width = max(self.px(400), event.width - self.px(60))
            for child in self.banner_frame.winfo_children():
                child.configure(wraplength=width)

    def _update_dates(self, snap: Snapshot) -> None:
        dates = self.ctrl.list_dates()
        if dates != self._date_values:
            self._date_values = dates
            labels = [format_short_date(d) + ("  (latest)" if i == 0 else "") for i, d in enumerate(dates)]
            self.date_box.configure(values=labels)
        shown = snap.shown
        if shown is not None and not shown.demo and shown.edition_date in dates:
            self.date_box.current(dates.index(shown.edition_date))
        elif shown is not None and shown.demo:
            self.date_var.set("DEMO")
        else:
            self.date_var.set("")

    def _chip(self, name: str) -> None:
        tag = f"chip:{name}" if f"chip:{name}" in self.text.tag_names() else "chip:Continuing"
        self.text.insert("end", f" {name} ", ("meta", tag))
        self.text.insert("end", "  ", ("meta",))

    def _render_body(self, snap: Snapshot) -> None:
        t = self.text
        y = t.yview()[0]
        same_edition = getattr(self, "_body_edition", None) == (snap.shown.run_id if snap.shown else None)
        t.configure(state="normal")
        t.delete("1.0", "end")
        for tag in list(self._links):
            t.tag_delete(tag)
        self._links.clear()
        if snap.shown is None:
            if snap.activity.running:
                self._render_collecting(snap)
            else:
                self._render_first_run(snap)
        else:
            self._render_edition(snap)
        t.configure(state="disabled")
        self._body_edition = snap.shown.run_id if snap.shown else None
        t.yview_moveto(y if same_edition else 0)

    def _render_collecting(self, snap: Snapshot) -> None:
        t = self.text
        t.insert("end", "Collecting today's news\n", ("h2",))
        t.insert("end", f"{snap.activity.message}\n\n", ("plain", "bold"))
        t.insert("end", "Public news sources are fetched over the internet, then the local model on this PC groups and "
                        "summarizes them. On a computer without a graphics card this can take 10 to 40 minutes.\n\n"
                        "You can keep reading or close this window: the refresh continues in the background and the "
                        "new edition appears here when it is ready.\n", ("plain", "muted"))

    def _render_first_run(self, snap: Snapshot) -> None:
        t = self.text
        if snap.state.last_attempt_outcome:
            t.insert("end", "No edition yet\n", ("h2",))
            t.insert("end", "The last refresh did not produce an edition (the reason is shown above). Check the "
                            "items below, then choose Refresh.\n\n", ("plain",))
        else:
            t.insert("end", "Welcome to Agent Reach\n", ("h2",))
            t.insert("end", "Agent Reach collects public news sources, removes noise, groups related reports and "
                            "writes a short daily briefing with a local AI model (Ollama) on this PC. Nothing is sent "
                            "to a paid or cloud AI service.\n\n", ("plain",))
        t.insert("end", "Before the first refresh\n", ("bold",))
        t.insert("end", "1.  This app: ", ("plain",))
        t.insert("end", "ready\n", ("ok",))
        t.insert("end", "2.  Local model: ", ("plain",))
        if self._prereq_text is None:
            self._start_prereq_check(announce=False)
        text = self._prereq_text or ""
        t.insert("end", text + "\n", ("ok",) if text.startswith("ready") else ("plain",))
        t.insert("end", "3.  Internet access for the news sources. Some sources (X, Reddit) are often blocked; the "
                        "edition says which sources were missing.\n\n", ("plain",))
        btn = ttk.Button(t, text="Collect today's news now", style="Refresh.TButton", command=self.refresh_now)
        t.window_create("end", window=btn)
        t.insert("end", "    ")
        demo = ttk.Button(t, text="Preview the demo edition", command=self.show_demo)
        t.window_create("end", window=demo)
        t.insert("end", "\n\nThe first edition is a baseline: stories are not marked new, rising or continuing until "
                        "there is an earlier edition to compare with. After that a new edition is collected every 24 "
                        "hours while your PC is on (Help > How refreshing works). The demo edition uses clearly "
                        "marked synthetic stories.\n", ("plain", "muted"))

    def _render_edition(self, snap: Snapshot) -> None:
        t = self.text
        edition = snap.shown
        assert edition is not None
        stories = filter_stories(edition.stories, self.cat_var.get(), self.search_var.get())
        filtered = bool(self.search_var.get().strip()) or self.cat_var.get() not in ("", "All")
        if edition.overview and not filtered:
            t.insert("end", edition.overview + "\n", ("overview",))
        if not filtered and stories and all(s.velocity_basis == "cold_start" for s in edition.stories):
            t.insert("end", "Baseline edition: trend labels (new, rising, continuing) appear once there is an earlier "
                            "edition to compare with.\n", ("baseline",))
        if snap.details and not filtered:
            t.insert("end", f"{len(snap.details)} coverage note(s) for this edition. ", ("baseline",))
            t.insert("end", "Show details", ("baseline",) + self._link_tag("action:details", small=True))
            t.insert("end", "\n", ("baseline",))
        if not edition.stories:
            t.insert("end", "\nThis edition has no stories.\n", ("plain",))
        elif not stories:
            t.insert("end", "\nNo stories match the current category and search. ", ("plain",))
            t.insert("end", "Clear filters", ("plain",) + self._link_tag("action:clear"))
            t.insert("end", "\n")
        now = self.ctrl.now_fn()
        for i, s in enumerate(stories):
            self._render_story(s, now, first=(i == 0 and filtered))
        t.insert("end", "\n", ("sep",))

    def _link_tag(self, target: str, small: bool = False) -> tuple[str, str]:
        name = f"link{len(self._links)}"
        self._links[name] = target
        self.text.tag_bind(name, "<Button-1>", lambda e, n=name: self._click(n))
        return ("small_link" if small else "link", name)

    def _click(self, name: str) -> str:
        target = self._links.get(name, "")
        if target == "action:clear":
            self._clear_filters()
        elif target == "action:details":
            self.show_details()
        elif target.startswith("toggle:"):
            sid = target.split(":", 1)[1]
            self._expanded.symmetric_difference_update({sid})
            self.refresh_view(force=True)
        else:
            self._open_url(target)
        return "break"

    def _open_url(self, target: str) -> None:
        url = safe_url(target)
        if url:
            webbrowser.open(url, new=2)

    def _render_story(self, s: Story, now, first: bool = False) -> None:
        t = self.text
        if not first:
            t.insert("end", "\n", ("sep",))
        t.insert("end", f"{s.rank:02d}\t", ("headline", "rank"))
        t.insert("end", s.headline + "\n", ("headline",))
        self._chip(s.category.value)
        for label in s.labels:
            self._chip(label)
        n_sources = len({(e.publisher or e.source_name) for e in s.evidence})
        t.insert("end", f"{story_age(s, now)}   ·   {n_sources} source{'s' if n_sources != 1 else ''}\n", ("meta",))
        t.insert("end", " ".join(s.sentences) + "\n", ("body",))
        if s.why_it_matters:
            t.insert("end", "WHY IT MATTERS\n", ("kicker",))
            t.insert("end", s.why_it_matters + "\n", ("why",))
        pubs, more = story_publishers(s)
        t.insert("end", "Sources:  ", ("sources",))
        for i, (name, url) in enumerate(pubs):
            if i:
                t.insert("end", "  ·  ", ("sources",))
            if url:
                t.insert("end", name, ("sources",) + self._link_tag(url, small=True))
            else:
                t.insert("end", name, ("sources",))
        if more:
            t.insert("end", f"  +{more} more", ("sources",))
        expanded = s.story_id in self._expanded
        t.insert("end", "     ", ("sources",))
        t.insert("end", "Hide source details" if expanded else "Source details",
                 ("sources",) + self._link_tag(f"toggle:{s.story_id}", small=True))
        t.insert("end", "\n", ("sources",))
        if expanded:
            self._render_evidence(s)

    def _render_evidence(self, s: Story) -> None:
        t = self.text
        for ev in s.evidence:
            t.insert("end", f"• {ev.source_name}: ", ("evidence",))
            if ev.url:
                t.insert("end", ev.title, ("evidence",) + self._link_tag(ev.url, small=True))
            else:
                t.insert("end", ev.title, ("evidence",))
            extra = [ev.publisher] if ev.publisher and ev.publisher != ev.source_name else []
            if ev.published_at_utc:
                extra.append("published " + format_central(ev.published_at_utc))
            else:
                extra.append("publication time not stated")
                if ev.retrieved_at_utc:
                    extra.append("retrieved " + format_central(ev.retrieved_at_utc))
            t.insert("end", f"  ({'; '.join(extra)})\n", ("evidence", "muted"))
            if ev.excerpt:
                t.insert("end", ev.excerpt + "\n", ("excerpt",))
        if s.momentum_note:
            t.insert("end", f"Trend comparison: {s.momentum_note}\n", ("excerpt",))

    def _expand_all(self, expand: bool) -> None:
        shown = self.snap.shown if self.snap else None
        self._expanded = {s.story_id for s in shown.stories} if (expand and shown) else set()
        self.refresh_view(force=True)

    # ------------------------------------------------------------ actions
    def _launch_check(self) -> None:
        try:
            if self.ctrl.maybe_auto_refresh():
                self.refresh_view(force=True)
        except Exception:  # noqa: BLE001
            log.exception("launch check failed")

    def refresh_now(self) -> None:
        snap = self.snap or self.ctrl.snapshot()
        if snap.activity.running or self._cancelling:
            self._flash_status("A refresh is already running.")
            return
        allow = False
        st = snap.state
        if st.last_attempt_outcome == "failed" and "Ollama" in (st.last_attempt_message or "") and snap.prefs.require_llm:
            allow = messagebox.askyesno(
                APP_NAME, "The last refresh could not use the local model (Ollama).\n\nYes: try again, and if "
                          "Ollama is still unavailable build an edition WITHOUT AI summaries (lead sentences "
                          "from the sources).\nNo: try again with the local model only.", parent=self.root)
        try:
            started = self.ctrl.start_refresh(manual=True, allow_extractive=allow)
        except OSError as exc:
            log.exception("could not start the refresh worker")
            messagebox.showerror(APP_NAME, f"Could not start the refresh: {exc}", parent=self.root)
            return
        if started:
            self._flash_status("Refresh started...")
            self.refresh_view(force=True)

    def _flash_status(self, text: str) -> None:
        self.status_var.set(text)
        self._draw_dot("refreshing")

    def cancel_refresh(self) -> None:
        if not messagebox.askyesno(APP_NAME, "Stop the running refresh? The current edition stays as it is.",
                                   parent=self.root):
            return
        self._cancelling = True
        self._flash_status("Stopping the refresh...")
        self.refresh_view()

        def work() -> None:
            try:
                self.ctrl.cancel_refresh()
            except Exception:  # noqa: BLE001
                log.exception("cancel failed")
            finally:
                self.root.after(0, self._cancel_done)

        threading.Thread(target=work, name="cancel-refresh", daemon=True).start()

    def _cancel_done(self) -> None:
        self._cancelling = False
        self.refresh_view(force=True)

    def _on_date(self, _event=None) -> None:
        i = self.date_box.current()
        if 0 <= i < len(self._date_values):
            self.ctrl.demo = None
            self.ctrl.selected_date = None if i == 0 else self._date_values[i]
            self.refresh_view(force=True)

    def show_latest(self) -> None:
        self.ctrl.demo = None
        self.ctrl.selected_date = None
        self.refresh_view(force=True)

    def show_demo(self) -> None:
        try:
            self.ctrl.load_demo()
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_NAME, f"The demo edition could not be opened: {exc}", parent=self.root)
            return
        self.refresh_view(force=True)

    def _clear_filters(self) -> None:
        self.cat_var.set("All")
        self.search_var.set("")
        self.refresh_view(force=True)

    def export_html(self) -> None:
        snap = self.snap or self.ctrl.snapshot()
        edition = snap.shown
        if edition is None:
            messagebox.showinfo(APP_NAME, "There is no edition to export yet.", parent=self.root)
            return
        from agent_reach.daily.render_html import render_edition_html

        self.paths.exports_dir.mkdir(parents=True, exist_ok=True)
        name = f"{'DEMO-' if edition.demo else ''}AgentReachDaily-{edition.edition_date.isoformat()}.html"
        target = filedialog.asksaveasfilename(parent=self.root, initialdir=str(self.paths.exports_dir),
                                              initialfile=name, defaultextension=".html",
                                              filetypes=[("HTML page", "*.html")])
        if not target:
            return
        try:
            Path(target).write_text(render_edition_html(edition), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not save the file: {exc}", parent=self.root)
            return
        if messagebox.askyesno(APP_NAME, f"Saved {target}\n\nOpen it in your browser?", parent=self.root):
            webbrowser.open(Path(target).as_uri())

    def show_details(self) -> None:
        DetailsWindow(self)

    def show_help(self) -> None:
        messagebox.showinfo(APP_NAME, (
            "How refreshing works\n\n"
            "- A new edition is collected 24 hours after the start of the last successful refresh (or daily at a "
            "fixed Central time, if chosen in Settings). Refresh collects one immediately.\n"
            "- The optional scheduled task checks every hour and at logon, and does nothing when no refresh is due. "
            "It only runs while you are logged on. A PC that is off or asleep cannot collect news; the refresh "
            "happens at the next chance.\n"
            "- Ollama must be running. The app tries to start the installed Ollama app if it is not.\n"
            "- If a refresh fails or finds too little news, the previous edition is kept and the app retries "
            "later (30 minutes, then longer, up to 6 hours).\n"
            "- Editions are dated by the US Central day the refresh started and kept for 30 days by default."),
            parent=self.root)

    def _start_prereq_check(self, announce: bool = True) -> None:
        prefs = (self.snap.prefs if self.snap else DailyPrefs())

        def work() -> None:
            from agent_reach.daily.prereqs import check_ollama

            status = check_ollama(prefs.ollama_host, [prefs.ollama_model, prefs.embed_model])
            prefix = "ready - " if status.ready else "NOT ready - "
            self._prereq_q.put(prefix + status.describe())

        self._prereq_text = "checking the local model (Ollama)..."
        threading.Thread(target=work, name="prereq-check", daemon=True).start()
        self.root.after(300, lambda: self._poll_prereq_soon(0, announce))

    def _drain_prereq(self) -> bool:
        got = False
        try:
            while True:
                self._prereq_text = self._prereq_q.get_nowait()
                got = True
        except queue.Empty:
            pass
        return got

    def _poll_prereq_soon(self, tries: int = 0, announce: bool = True) -> None:
        if self._drain_prereq():
            self.refresh_view(force=True)
            if announce:
                messagebox.showinfo(APP_NAME, f"Local model: {self._prereq_text}", parent=self.root)
        elif tries < 30:
            self.root.after(300, lambda: self._poll_prereq_soon(tries + 1, announce))

    def open_settings(self) -> None:
        SettingsDialog(self, (self.snap or self.ctrl.snapshot()).prefs)

    @staticmethod
    def _open_path(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            webbrowser.open(path.as_uri())

    def _callback_error(self, exc_type, exc, tb) -> None:
        """Tk callback errors go to gui.log; the reader sees a short message, never a traceback."""
        log.error("unexpected error in the window", exc_info=(exc_type, exc, tb))
        try:
            messagebox.showerror(APP_NAME, "Something went wrong in the window. Your editions are safe.\n\n"
                                           f"Details were written to the log folder:\n{self.paths.logs_dir}",
                                 parent=self.root)
        except tk.TclError:
            pass

    def _on_close(self) -> None:
        if self.snap and self.snap.activity.running:
            messagebox.showinfo(APP_NAME, "The refresh continues in the background. The new edition will be "
                                          "shown the next time you open Agent Reach.", parent=self.root)
        try:
            if self.root.state() == "normal":
                save_window_geometry(self.paths, self.root.geometry())
        except tk.TclError:
            pass
        self.root.destroy()


class DetailsWindow:
    """Secondary information: source health, edition metadata, refresh history and local paths."""

    def __init__(self, window: DailyWindow) -> None:
        self.window = window
        snap = window.snap or window.ctrl.snapshot()
        top = tk.Toplevel(window.root, bg=window.c["bg"])
        top.title("Details")
        dark_title_bar(top, window.mode == "dark")
        top.geometry(f"{window.px(860)}x{window.px(560)}")
        top.minsize(window.px(560), window.px(360))
        top.transient(window.root)
        top.bind("<Escape>", lambda e: top.destroy())
        nb = ttk.Notebook(top)
        nb.pack(fill="both", expand=True, padx=window.px(10), pady=(window.px(10), 0))
        self._sources_tab(nb, snap)
        self._publishers_tab(nb, snap)
        for title, rows in details_report(snap, window.paths):
            self._text_tab(nb, title, rows)
        btns = ttk.Frame(top, padding=window.px(10))
        btns.pack(fill="x")
        ttk.Button(btns, text="Close", command=top.destroy).pack(side="right")
        ttk.Button(btns, text="Open logs folder",
                   command=lambda: DailyWindow._open_path(window.paths.logs_dir)).pack(side="right", padx=window.px(6))
        ttk.Button(btns, text="Check local model", command=window._start_prereq_check).pack(side="right")
        top.focus_set()

    def _tree(self, parent, columns: list[tuple[str, str, int, str]], height: int = 12) -> ttk.Treeview:
        """Treeview with a scrollbar; columns = [(id, heading, width, anchor)], the first is the tree column."""
        w = self.window
        box = ttk.Frame(parent)
        box.pack(fill="both", expand=True)
        tree = ttk.Treeview(box, columns=[c[0] for c in columns[1:]], show="tree headings", height=height)
        for i, (cid, heading, width, anchor) in enumerate(columns):
            key = "#0" if i == 0 else cid
            tree.heading(key, text=heading, anchor="w" if anchor == "w" else "e")
            tree.column(key, width=w.px(width), anchor=anchor, stretch=(i == len(columns) - 1))
        sb = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return tree

    def _sources_tab(self, nb: ttk.Notebook, snap: Snapshot) -> None:
        w = self.window
        frm = ttk.Frame(nb, padding=w.px(12))
        nb.add(frm, text="Sources")
        edition = snap.shown
        if edition is None:
            ttk.Label(frm, text="No edition yet: source health appears after the first refresh.").pack(anchor="w")
            return
        feeds = [f for h in edition.source_health for f in h.feeds]
        line = f"{health_summary(edition.source_health)}   ({len(edition.source_health)} collection channels"
        if feeds:
            line += f"; {sum(f.status == 'ok' for f in feeds)} of {len(feeds)} publisher feeds delivered articles"
        ttk.Label(frm, text=line + ")", font=w.f_bold).pack(anchor="w", pady=(0, w.px(6)))
        tree = self._tree(frm, [("name", "Channel / publisher feed", 250, "w"), ("status", "Status", 80, "w"),
                                ("collected", "Collected", 90, "e"), ("used", "Used", 60, "e"),
                                ("notes", "Notes", 360, "w")])
        labels = {"ok": "OK", "partial": "PARTIAL", "empty": "EMPTY", "failed": "FAILED"}
        for h in edition.source_health:
            bad = [f for f in h.feeds if f.status != "ok"]
            note = (f"{len(bad)} of {len(h.feeds)} feeds returned nothing (expand)" if bad
                    else f"{len(h.feeds)} publisher feeds (expand)" if h.feeds else friendly_error(h.error))
            node = tree.insert("", "end", text=h.name, open=bool(bad),
                               values=(labels.get(h.status, h.status.upper()), h.item_count, h.used, note))
            for f in sorted(h.feeds, key=lambda f: (f.status == "ok", -f.used, f.name.lower())):
                tree.insert(node, "end", text=f.name, values=(labels.get(f.status, f.status.upper()), f.collected,
                                                              f.used, friendly_error(f.error) or (f.category or "")))
        ttk.Label(frm, text="Collected: articles taken in this refresh. Used: articles cited in this edition. "
                            "PARTIAL: the channel answered but some of it failed (for example a rate limit or a broken "
                            "feed). Expand a channel to see its publisher feeds.", style="Muted.TLabel",
                  wraplength=w.px(780)).pack(anchor="w", pady=(w.px(6), 0))

    def _publishers_tab(self, nb: ttk.Notebook, snap: Snapshot) -> None:
        w = self.window
        frm = ttk.Frame(nb, padding=w.px(12))
        nb.add(frm, text="Publishers")
        edition = snap.shown
        if edition is None:
            ttk.Label(frm, text="No edition yet.").pack(anchor="w")
            return
        rows = publisher_breakdown(edition)
        ttk.Label(frm, text=f"{len(rows)} publishers are cited in this edition", font=w.f_bold).pack(
            anchor="w", pady=(0, w.px(6)))
        tree = self._tree(frm, [("publisher", "Publisher", 260, "w"), ("stories", "Stories", 70, "e"),
                                ("articles", "Articles", 70, "e"), ("via", "Reached through", 330, "w")])
        for r in rows:
            tree.insert("", "end", text=r.publisher, values=(r.stories, r.articles, ", ".join(r.channels)))
        ttk.Label(frm, text="Includes publishers that arrive through aggregators such as Google News. A publisher "
                            "name is a rough diversity indicator, not proof of independent reporting.",
                  style="Muted.TLabel", wraplength=w.px(780)).pack(anchor="w", pady=(w.px(6), 0))

    def _text_tab(self, nb: ttk.Notebook, title: str, rows: list[tuple[str, str]]) -> None:
        w = self.window
        frm = ttk.Frame(nb, padding=w.px(6))
        nb.add(frm, text=title)
        txt = tk.Text(frm, wrap="word", relief="flat", bg=w.c["card"], fg=w.c["ink"], font=w.f_small, padx=w.px(10),
                      pady=w.px(8), highlightthickness=0)
        sb = ttk.Scrollbar(frm, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        txt.tag_configure("label", font=w.f_bold)
        txt.tag_configure("row", lmargin1=0, lmargin2=w.px(190), tabs=(w.px(190),), spacing1=w.px(3))
        for label, value in rows:
            if label:
                txt.insert("end", f"{label}\t", ("row", "label"))
                txt.insert("end", f"{value}\n", ("row",))
            else:
                txt.insert("end", f"• {value}\n", ("row",))
        txt.configure(state="disabled")


class SettingsDialog:
    def __init__(self, window: DailyWindow, prefs: DailyPrefs) -> None:
        self.window = window
        self.prefs = prefs
        self.top = top = tk.Toplevel(window.root, bg=window.c["bg"])
        top.title("Settings")
        top.geometry(f"{window.px(820)}x{window.px(640)}")
        top.minsize(window.px(640), window.px(520))
        top.bind("<Escape>", lambda e: top.destroy())
        top.transient(window.root)
        dark_title_bar(top, window.mode == "dark")
        top.grab_set()
        self._results: queue.Queue = queue.Queue()
        self._pending = 0
        self.feeds: list[FeedSpec] = [f.model_copy() for f in prefs.feeds]
        self.feed_results: dict[str, str] = {}
        nb = ttk.Notebook(top)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        self._sources_tab(nb)
        self._feeds_tab(nb)
        self._model_tab(nb)
        self._schedule_tab(nb)
        self._storage_tab(nb)
        self._appearance_tab(nb)
        btns = ttk.Frame(top, padding=(10, 0, 10, 10))
        btns.pack(fill="x")
        ttk.Button(btns, text="Save", style="Accent.TButton", command=self.save).pack(side="right")
        ttk.Button(btns, text="Cancel", command=top.destroy).pack(side="right", padx=6)

    def _tab(self, nb: ttk.Notebook, title: str) -> ttk.Frame:
        frm = ttk.Frame(nb, padding=12)
        nb.add(frm, text=title)
        return frm

    # ......................................................... background work (results polled on the Tk thread)
    def _bg(self, fn, done) -> None:
        def work():
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001
                result = exc
            self._results.put((done, result))

        self._pending += 1
        if self._pending == 1:
            self.top.after(150, self._drain)
        threading.Thread(target=work, daemon=True).start()

    def _drain(self) -> None:
        try:
            while True:
                done, result = self._results.get_nowait()
                self._pending -= 1
                if self.top.winfo_exists():
                    done(result)
        except queue.Empty:
            pass
        if self._pending > 0 and self.top.winfo_exists():
            self.top.after(150, self._drain)

    # ......................................................... channels
    def _sources_tab(self, nb) -> None:
        from agent_reach.ingestion import INGESTER_REGISTRY

        frm = self._tab(nb, "Sources")
        ttk.Label(frm, text="Collection channels. 'Publisher feeds' gathers articles from the publishers on the next "
                            "tab; the others are aggregators and trend lists. Tech-only channels are capped in the "
                            "edition.", wraplength=self.window.px(740)).grid(row=0, column=0, columnspan=2, sticky="w",
                                                                             pady=(0, 8))
        self.source_vars: dict[str, tk.BooleanVar] = {}
        for i, name in enumerate(INGESTER_REGISTRY):
            var = tk.BooleanVar(value=name in self.prefs.enabled_sources)
            self.source_vars[name] = var
            ttk.Checkbutton(frm, text=SOURCE_NOTES.get(name, name), variable=var).grid(
                row=1 + i // 2, column=i % 2, sticky="w", padx=(0, 16), pady=1)
        row = 2 + len(INGESTER_REGISTRY) // 2
        ttk.Separator(frm).grid(row=row, column=0, columnspan=2, sticky="ew", pady=10)
        self.per_feed_var = tk.StringVar(value=str(self.prefs.items_per_feed))
        self.budget_var = tk.StringVar(value=str(self.prefs.max_items_for_llm))
        ttk.Label(frm, text="Articles taken from each publisher feed:").grid(row=row + 1, column=0, sticky="w", pady=2)
        ttk.Spinbox(frm, from_=3, to=30, textvariable=self.per_feed_var, width=6).grid(row=row + 1, column=1, sticky="w")
        ttk.Label(frm, text="Articles grouped and summarized per refresh:").grid(row=row + 2, column=0, sticky="w", pady=2)
        ttk.Spinbox(frm, from_=40, to=400, increment=10, textvariable=self.budget_var, width=6).grid(
            row=row + 2, column=1, sticky="w")
        ttk.Label(frm, text="Every publisher feed has its own allowance and is guaranteed a few articles in the "
                            "processing budget, so one busy source cannot crowd out the others. A larger budget "
                            "covers more but makes each refresh slower on a PC without a graphics card.",
                  wraplength=self.window.px(740), style="Muted.TLabel").grid(row=row + 3, column=0, columnspan=2,
                                                                             sticky="w", pady=(6, 0))

    # ......................................................... publisher feeds
    def _feeds_tab(self, nb) -> None:
        w = self.window
        frm = self._tab(nb, "Publisher feeds")
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(1, weight=1)
        self.feeds_summary = tk.StringVar()
        ttk.Label(frm, textvariable=self.feeds_summary).grid(row=0, column=0, sticky="w", pady=(0, 6))
        box = ttk.Frame(frm)
        box.grid(row=1, column=0, sticky="nsew")
        cols = ("on", "category", "result")
        self.feed_tree = tree = ttk.Treeview(box, columns=cols, show="tree headings", height=12, selectmode="extended")
        tree.heading("#0", text="Publisher feed", anchor="w")
        tree.heading("on", text="On", anchor="w")
        tree.heading("category", text="Category", anchor="w")
        tree.heading("result", text="Last test", anchor="w")
        tree.column("#0", width=w.px(250), stretch=False)
        tree.column("on", width=w.px(40), stretch=False)
        tree.column("category", width=w.px(110), stretch=False)
        tree.column("result", width=w.px(300), stretch=True)
        sb = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tree.bind("<Double-1>", lambda e: self._edit_feed())
        tree.bind("<space>", lambda e: self._toggle_feeds())
        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        for text, cmd in (("Add feed...", self._add_feed), ("Edit...", self._edit_feed),
                          ("Turn on/off", self._toggle_feeds), ("Remove", self._remove_feeds)):
            ttk.Button(btns, text=text, command=cmd).pack(side="left", padx=(0, 4))
        tests = ttk.Frame(frm)
        tests.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(tests, text="Test selected", command=self._test_selected).pack(side="left", padx=(0, 4))
        ttk.Button(tests, text="Test all feeds", command=self._test_all).pack(side="left", padx=(0, 4))
        ttk.Button(tests, text="Restore defaults", command=self._restore_feeds).pack(side="right")
        ttk.Label(frm, text="Each feed is one publisher channel with its own allowance and its own health line in "
                            "Details. A feed that stops working never blocks the edition; it shows as failed. "
                            "Testing fetches the feed now over the internet.", style="Muted.TLabel",
                  wraplength=w.px(740)).grid(row=4, column=0, sticky="w", pady=(6, 0))
        self._fill_feeds()

    def _fill_feeds(self, select: list[str] | None = None) -> None:
        tree = self.feed_tree
        tree.delete(*tree.get_children())
        for i, f in enumerate(self.feeds):
            tree.insert("", "end", iid=str(i), text=f.name,
                        values=("yes" if f.enabled else "no", f.category, self.feed_results.get(f.url, "")))
        if select:
            ids = [str(i) for i, f in enumerate(self.feeds) if f.url in select]
            tree.selection_set(ids)
            if ids:
                tree.see(ids[0])
        on = [f for f in self.feeds if f.enabled]
        self.feeds_summary.set(f"{len(on)} of {len(self.feeds)} feeds on, from {len({f.publisher for f in on})} "
                               f"publishers. Double-click a feed to edit it.")

    def _selected_feeds(self) -> list[FeedSpec]:
        return [self.feeds[int(i)] for i in self.feed_tree.selection()]

    def _add_feed(self) -> None:
        FeedDialog(self, None)

    def _edit_feed(self) -> None:
        sel = self._selected_feeds()
        if sel:
            FeedDialog(self, sel[0])

    def save_feed(self, old: FeedSpec | None, new: FeedSpec) -> str | None:
        """Called by FeedDialog. Returns an error message, or None when saved."""
        if any(f.url.lower() == new.url.lower() and f is not old for f in self.feeds):
            return "That feed address is already in the list."
        if old is None:
            self.feeds.append(new)
        else:
            self.feeds[self.feeds.index(old)] = new
        self._fill_feeds(select=[new.url])
        return None

    def _toggle_feeds(self) -> None:
        sel = self._selected_feeds()
        if not sel:
            return
        turn_on = not all(f.enabled for f in sel)
        for f in sel:
            f.enabled = turn_on
        self._fill_feeds(select=[f.url for f in sel])

    def _remove_feeds(self) -> None:
        sel = self._selected_feeds()
        if sel and messagebox.askyesno(APP_NAME, f"Remove {len(sel)} feed(s) from the list?", parent=self.top):
            self.feeds = [f for f in self.feeds if f not in sel]
            self._fill_feeds()

    def _restore_feeds(self) -> None:
        if messagebox.askyesno(APP_NAME, "Replace the feed list with the default publishers? Feeds you added will "
                                         "be removed.", parent=self.top):
            self.feeds = default_feeds()
            self.feed_results.clear()
            self._fill_feeds()

    def _test_selected(self) -> None:
        self._test(self._selected_feeds())

    def _test_all(self) -> None:
        self._test([f for f in self.feeds if f.enabled])

    def _test(self, feeds: list[FeedSpec]) -> None:
        from agent_reach.daily.feeds import check_feed

        for f in feeds:
            self.feed_results[f.url] = "testing..."

            def done(result, url=f.url):
                self.feed_results[url] = (result.message if not isinstance(result, Exception)
                                          else f"Could not test: {result}")
                self._fill_feeds(select=[g.url for g in self._selected_feeds()])

            self._bg(lambda spec=f: check_feed(spec), done)
        self._fill_feeds(select=[f.url for f in self._selected_feeds()])

    def _model_tab(self, nb) -> None:
        frm = self._tab(nb, "Model")
        self.host_var = tk.StringVar(value=self.prefs.ollama_host)
        self.model_var = tk.StringVar(value=self.prefs.ollama_model)
        self.embed_var = tk.StringVar(value=self.prefs.embed_model)
        self.require_var = tk.BooleanVar(value=self.prefs.require_llm)
        self.why_var = tk.BooleanVar(value=self.prefs.why_it_matters)
        self.start_var = tk.BooleanVar(value=self.prefs.start_ollama_if_down)
        for row, (label, var) in enumerate([("Ollama address", self.host_var), ("Summary model", self.model_var),
                                            ("Embedding model", self.embed_var)]):
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(frm, textvariable=var, width=40).grid(row=row, column=1, sticky="w", pady=3)
        ttk.Checkbutton(frm, text="Require the local model (no edition from extractive summaries)",
                        variable=self.require_var).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 2))
        ttk.Checkbutton(frm, text="Write 'why it matters' notes (only when supported by the evidence)",
                        variable=self.why_var).grid(row=4, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(frm, text="Start the installed Ollama app when it is not running",
                        variable=self.start_var).grid(row=5, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(frm, text="Models must already be downloaded (ollama pull <name>); refreshes never download "
                            "models. Changing models makes the next trend comparison 'uncertain'.",
                  wraplength=560, foreground=self.window.c["muted"]).grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _schedule_tab(self, nb) -> None:
        frm = self._tab(nb, "Schedule")
        self.mode_var = tk.StringVar(value=self.prefs.schedule_mode)
        self.hours_var = tk.StringVar(value=f"{self.prefs.refresh_interval_hours:g}")
        self.time_var = tk.StringVar(value=self.prefs.fixed_time_central)
        self.launch_var = tk.BooleanVar(value=self.prefs.refresh_on_launch)
        ttk.Radiobutton(frm, text="Every N hours after the last successful refresh (elapsed time, default)",
                        value="elapsed", variable=self.mode_var).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(frm, text="    Hours:").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(frm, from_=1, to=168, textvariable=self.hours_var, width=6).grid(row=1, column=1, sticky="w")
        ttk.Radiobutton(frm, text="Daily at a fixed US Central time (wall clock; follows CDT/CST)",
                        value="fixed_central", variable=self.mode_var).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(frm, text="    Time (HH:MM):").grid(row=3, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.time_var, width=8).grid(row=3, column=1, sticky="w")
        ttk.Checkbutton(frm, text="When this window opens, start a refresh if one is due",
                        variable=self.launch_var).grid(row=4, column=0, columnspan=3, sticky="w", pady=(12, 0))
        ttk.Separator(frm).grid(row=5, column=0, columnspan=3, sticky="ew", pady=12)
        ttk.Label(frm, text="Background refresh (Windows Task Scheduler)", font=self.window.f_bold).grid(
            row=6, column=0, columnspan=3, sticky="w")
        self.task_var = tk.StringVar(value="Checking...")
        ttk.Label(frm, textvariable=self.task_var, wraplength=560).grid(row=7, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Button(frm, text="Enable / update", command=self._install_task).grid(row=8, column=0, sticky="w")
        ttk.Button(frm, text="Disable", command=self._uninstall_task).grid(row=8, column=1, sticky="w")
        ttk.Label(frm, text="The task checks hourly and at logon, runs only while you are logged on, and never "
                            "wakes the PC. With it disabled, refreshes happen when this window is open.",
                  wraplength=560, foreground=self.window.c["muted"]).grid(row=9, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self._task_bg(lambda: self._task_text())

    def _storage_tab(self, nb) -> None:
        frm = self._tab(nb, "Storage")
        self.retention_var = tk.StringVar(value=str(self.prefs.retention_days))
        self.max_var = tk.StringVar(value=str(self.prefs.max_stories))
        self.age_var = tk.StringVar(value=f"{self.prefs.max_story_age_hours:g}")
        ttk.Label(frm, text="Keep editions for (days):").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Spinbox(frm, from_=1, to=3650, textvariable=self.retention_var, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(frm, text="Most stories per edition:").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Spinbox(frm, from_=3, to=50, textvariable=self.max_var, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(frm, text="Leave out stories published more than (hours) ago:").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Spinbox(frm, from_=6, to=336, textvariable=self.age_var, width=8).grid(row=2, column=1, sticky="w")
        ttk.Label(frm, text=f"Data folder: {self.window.paths.root}", wraplength=560).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(12, 4))
        ttk.Button(frm, text="Open data folder",
                   command=lambda: DailyWindow._open_path(self.window.paths.root)).grid(row=4, column=0, sticky="w")
        ttk.Separator(frm).grid(row=5, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Button(frm, text="Delete all cached editions...", command=self._reset_cache).grid(row=6, column=0, sticky="w")
        ttk.Label(frm, text="Fewer, stronger stories are preferred to filler: an edition can have fewer stories than "
                            "the maximum. The newest edition is never deleted by retention, even after failed refreshes.",
                  wraplength=560, foreground=self.window.c["muted"]).grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _appearance_tab(self, nb) -> None:
        frm = self._tab(nb, "Appearance")
        self.appearance_var = tk.StringVar(value=self.prefs.appearance)
        for value, text in (("system", "Match Windows (light or dark app mode)"), ("light", "Light"), ("dark", "Dark")):
            ttk.Radiobutton(frm, text=text, value=value, variable=self.appearance_var).pack(anchor="w", pady=2)
        ttk.Label(frm, text="Exported HTML editions follow the light or dark setting of the browser that opens them.",
                  style="Muted.TLabel", wraplength=self.window.px(740)).pack(anchor="w", pady=(10, 0))

    # ......................................................... task helpers
    def _task_bg(self, fn) -> None:
        def show(result) -> None:
            self.task_var.set(f"Could not query Task Scheduler: {result}" if isinstance(result, Exception) else result)

        self._bg(fn, show)

    @staticmethod
    def _task_text() -> str:
        from agent_reach.daily import scheduler
        from agent_reach.daily.paths import PROJECT_ROOT

        st = scheduler.task_status()
        if not st.supported:
            return st.detail
        if not st.installed:
            return "Not installed: refreshes run only while this window is open."
        here = scheduler.gui_python(sys.executable)
        where = "" if st.matches(here, PROJECT_ROOT) else " (installed from a different folder; use Enable / update)"
        return f"Installed and {'enabled' if st.enabled else 'disabled'}{where}."

    def _install_task(self) -> None:
        def run():
            from agent_reach.daily import scheduler
            from agent_reach.daily.paths import PROJECT_ROOT, default_root

            data_dir = None if self.window.paths.root == default_root().resolve() else self.window.paths.root
            ok, msg = scheduler.install_task(sys.executable, PROJECT_ROOT, data_dir=data_dir)
            return ("Enabled. " if ok else "Failed: ") + msg + "\n" + self._task_text()

        self.task_var.set("Installing...")
        self._task_bg(run)

    def _uninstall_task(self) -> None:
        def run():
            from agent_reach.daily import scheduler

            ok, msg = scheduler.uninstall_task()
            return ("Disabled. " if ok else "Failed: ") + msg + " Cached news is kept."

        self.task_var.set("Removing...")
        self._task_bg(run)

    def _reset_cache(self) -> None:
        if not messagebox.askyesno(APP_NAME, "Delete every cached edition? Settings and refresh history are kept. "
                                             "This cannot be undone.", parent=self.top, icon="warning"):
            return
        from agent_reach.daily.lock import LockBusy, RefreshLock
        from agent_reach.daily.store import EditionStore

        lock = RefreshLock(self.window.paths.lock_file, None)
        try:
            lock.acquire()
        except LockBusy:
            messagebox.showwarning(APP_NAME, "A refresh is running. Try again when it has finished.", parent=self.top)
            return
        try:
            n = EditionStore(self.window.paths).reset()
        finally:
            lock.release()
        messagebox.showinfo(APP_NAME, f"Deleted {n} cached edition(s).", parent=self.top)
        self.window.show_latest()

    def save(self) -> None:
        try:
            data = self.prefs.model_dump()
            data.update(
                enabled_sources=[k for k, v in self.source_vars.items() if v.get()],
                ollama_host=self.host_var.get(), ollama_model=self.model_var.get().strip(),
                embed_model=self.embed_var.get().strip(), require_llm=self.require_var.get(),
                why_it_matters=self.why_var.get(), start_ollama_if_down=self.start_var.get(),
                schedule_mode=self.mode_var.get(), refresh_interval_hours=float(self.hours_var.get()),
                fixed_time_central=self.time_var.get(), refresh_on_launch=self.launch_var.get(),
                retention_days=int(self.retention_var.get()), max_stories=int(self.max_var.get()),
                max_story_age_hours=float(self.age_var.get()),
                feeds=[f.model_dump() for f in self.feeds], items_per_feed=int(self.per_feed_var.get()),
                max_items_for_llm=int(self.budget_var.get()), appearance=self.appearance_var.get(),
            )
            prefs = DailyPrefs.model_validate(data)
            if "news_rss" in prefs.enabled_sources and not prefs.enabled_feeds():
                raise ValueError("'Publisher feeds' is on but every publisher feed is turned off.")
        except (ValueError, TypeError) as exc:
            messagebox.showerror(APP_NAME, f"Please check the settings:\n\n{exc}", parent=self.top)
            return
        save_prefs(self.window.paths, prefs)
        self.top.destroy()
        new_mode = resolve_appearance(prefs.appearance)
        if new_mode != self.window.mode:
            self.window.apply_theme(new_mode)
        self.window.refresh_view(force=True)


class FeedDialog:
    """Add or edit one publisher feed, with a Test button."""

    def __init__(self, settings: SettingsDialog, feed: FeedSpec | None) -> None:
        self.settings, self.feed = settings, feed
        w = settings.window
        self.top = top = tk.Toplevel(settings.top, bg=w.c["bg"])
        top.title("Edit feed" if feed else "Add feed")
        top.transient(settings.top)
        dark_title_bar(top, w.mode == "dark")
        top.bind("<Escape>", lambda e: top.destroy())
        frm = ttk.Frame(top, padding=w.px(14))
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        self.name_var = tk.StringVar(value=feed.name if feed else "")
        self.url_var = tk.StringVar(value=feed.url if feed else "https://")
        self.cat_var = tk.StringVar(value=feed.category if feed else "News")
        ttk.Label(frm, text="Name").grid(row=0, column=0, sticky="w", pady=3)
        name = ttk.Entry(frm, textvariable=self.name_var, width=48)
        name.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(frm, text="Feed address (RSS or Atom)").grid(row=1, column=0, sticky="w", pady=3, padx=(0, 8))
        ttk.Entry(frm, textvariable=self.url_var, width=48).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(frm, text="Category").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Combobox(frm, textvariable=self.cat_var, state="readonly", values=all_categories(), width=18).grid(
            row=2, column=1, sticky="w", pady=3)
        self.result_var = tk.StringVar(value="Business and health feeds belong under News.")
        ttk.Label(frm, textvariable=self.result_var, wraplength=w.px(460), style="Muted.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 8))
        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=2, sticky="ew")
        ttk.Button(btns, text="Save", command=self.save).pack(side="right")
        ttk.Button(btns, text="Cancel", command=top.destroy).pack(side="right", padx=6)
        self.test_btn = ttk.Button(btns, text="Test", command=self.test)
        self.test_btn.pack(side="left")
        name.focus_set()
        top.grab_set()

    def _spec(self, name: str | None = None) -> FeedSpec | None:
        try:
            return FeedSpec(name=name or self.name_var.get(), url=self.url_var.get(), category=self.cat_var.get(),
                            enabled=self.feed.enabled if self.feed else True)
        except ValueError as exc:
            errors = getattr(exc, "errors", lambda: [])()
            self.result_var.set("Please check: " + ("; ".join(e["msg"] for e in errors) if errors else str(exc)))
            return None

    def test(self) -> None:
        from agent_reach.daily.feeds import check_feed

        spec = self._spec(name=self.name_var.get().strip() or "New feed")
        if spec is None:
            return
        self.result_var.set("Testing the feed over the internet...")
        self.test_btn.state(["disabled"])

        def done(result) -> None:
            if self.top.winfo_exists():
                self.test_btn.state(["!disabled"])
                self.result_var.set(result.message if not isinstance(result, Exception) else f"Could not test: {result}")
                if not isinstance(result, Exception) and result.feed_title and not self.name_var.get().strip():
                    self.name_var.set(result.feed_title)

        self.settings._bg(lambda: check_feed(spec), done)

    def save(self) -> None:
        spec = self._spec()
        if spec is None:
            return
        problem = self.settings.save_feed(self.feed, spec)
        if problem:
            self.result_var.set(problem)
            return
        self.top.destroy()


def run_gui(paths: DataPaths | None = None) -> int:
    from agent_reach.daily.logs import setup_logging

    paths = (paths or DataPaths.resolve()).ensure()
    setup_logging(paths, "gui")
    _enable_dpi_awareness()
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        log.error("cannot open a window: %s", exc)
        print(f"Agent Reach cannot open a window: {exc}", file=sys.stderr)
        return 1
    try:
        DailyWindow(root, paths)
        root.mainloop()
    except Exception:  # noqa: BLE001
        log.exception("GUI crashed")
        try:
            messagebox.showerror(APP_NAME, f"Agent Reach hit an error and has to close. Your editions are safe.\n\n"
                                           f"Details are in {paths.logs_dir}")
        except tk.TclError:
            pass
        return 1
    return 0


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(prog="agent_reach.daily.gui")
    p.add_argument("--data-dir", type=Path)
    args = p.parse_args()
    sys.exit(run_gui(DataPaths.resolve(args.data_dir)))


if __name__ == "__main__":
    main()
