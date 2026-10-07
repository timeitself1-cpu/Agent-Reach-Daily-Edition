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
    compact_times,
    details_report,
    feed_note,
    filter_stories,
    load_window_geometry,
    publisher_breakdown,
    resolve_appearance,
    save_window_geometry,
    story_age,
    story_publishers,
)
from agent_reach.daily.edition import (
    Story,
    all_categories,
    category_sections,
    friendly_error,
    health_summary,
    primary_url,
    safe_url,
    top_stories,
)
from agent_reach.daily import reading as RD
from agent_reach.daily.paths import DataPaths
from agent_reach.daily.feeds import FeedSpec, default_feeds
from agent_reach.daily.prefs import DailyPrefs, SOURCE_NOTES, save_prefs
from agent_reach.daily.strength import strength_of
from agent_reach.daily.timeutil import format_central, format_clock, format_long_date, format_short_date, utcnow

log = logging.getLogger(__name__)

POLL_RUNNING_MS = 1000
POLL_IDLE_MS = 30000

STATUS_DOT = {"current": "#34c759", "stale": "#ff9f0a", "refreshing": "#0a84ff", "failed": "#ff3b30",
              "empty": "#8e8e93", "demo": "#ff3b30", "archive": "#8e8e93"}

#: macOS-like light and dark palettes. Category values are (tint, text) pairs; the reading view uses
#: the text colour for the small category label above each headline.
PALETTES: dict[str, dict] = {
    "light": {
        "bg": "#ececec", "sidebar": "#e8e8ea", "card": "#ffffff", "ink": "#1d1d1f", "ink2": "#3a3a3c",
        "muted": "#86868b", "accent": "#007aff", "link": "#0066cc", "rule": "#d8d8dc", "rank": "#aeaeb2",
        "field": "#ffffff", "button": "#f5f5f7", "button_active": "#e5e5ea", "select": "#d0d0d7",
        "sidebar_sel": "#d4d4da", "sidebar_hover": "#dfdfe4", "hairline": "#e6e6eb", "ok": "#248a3d", "bad": "#d70015",
        "categories": {
            "News": ("#e5f0ff", "#0060df"), "Sports": ("#e3f6e8", "#248a3d"), "Entertainment": ("#fdebf3", "#c41e6a"),
            "Tech": ("#eef0f3", "#5e5ce6"), "Science & AI": ("#fff4e0", "#b25000"),
            "Internet Culture": ("#f4ecff", "#8944ab")},
        "tags": {"new": "#248a3d", "updated": "#0060df", "day": "#b25000", "follow": "#a05a00"},
        "labels": {
            "Hot": ("#ffe5e3", "#d70015"), "Rising": ("#fff1dd", "#b25000"), "New": ("#e1f5f2", "#0b7a6b"),
            "Uncertain trend": ("#eef0f3", "#6e6e73"), "Continuing": ("#eef0f3", "#6e6e73"),
            "Steady": ("#eef0f3", "#6e6e73"), "Cooling": ("#eef0f3", "#86868b"), "Fading": ("#eef0f3", "#86868b")},
        "banners": {"info": ("#e5f0ff", "#0040a8"), "warn": ("#fff4d6", "#7a5200"),
                    "error": ("#ffe5e3", "#a1000f"), "demo": ("#ffe1e1", "#a1000f")},
    },
    "dark": {
        "bg": "#1e1e1e", "sidebar": "#252527", "card": "#1c1c1e", "ink": "#f5f5f7", "ink2": "#d1d1d6",
        "muted": "#98989d", "accent": "#0a84ff", "link": "#4da3ff", "rule": "#38383a", "rank": "#636366",
        "field": "#2c2c2e", "button": "#2c2c2e", "button_active": "#3a3a3c", "select": "#3a3a3c",
        "sidebar_sel": "#39393d", "sidebar_hover": "#2f2f32", "hairline": "#2c2c2e", "ok": "#30d158", "bad": "#ff6961",
        "categories": {
            "News": ("#14243d", "#64a8ff"), "Sports": ("#14301d", "#4cd964"), "Entertainment": ("#3a1528", "#ff7eb6"),
            "Tech": ("#26263a", "#a5a3ff"), "Science & AI": ("#3a2a10", "#ffb340"),
            "Internet Culture": ("#2c1a3a", "#d39bff")},
        "tags": {"new": "#30d158", "updated": "#64a8ff", "day": "#ffb340", "follow": "#ffd60a"},
        "labels": {
            "Hot": ("#3c1614", "#ff6961"), "Rising": ("#3a2a10", "#ffb340"), "New": ("#10302b", "#5edcc8"),
            "Uncertain trend": ("#2c2c2e", "#aeaeb2"), "Continuing": ("#2c2c2e", "#aeaeb2"),
            "Steady": ("#2c2c2e", "#aeaeb2"), "Cooling": ("#2c2c2e", "#98989d"), "Fading": ("#2c2c2e", "#98989d")},
        "banners": {"info": ("#14243d", "#9cc7ff"), "warn": ("#3a2f10", "#ffd36b"),
                    "error": ("#3c1614", "#ff8a80"), "demo": ("#4a1d1d", "#ffc9c9")},
    },
}

TOP = "top"
SEARCH = "search"
FOLLOWING = "following"


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


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


class DailyWindow:
    """Reader window: toolbar, section sidebar (Top Stories + categories) and a clean story list."""

    def __init__(self, root: tk.Tk, paths: DataPaths, controller: AppController | None = None,
                 auto_refresh: bool = True) -> None:
        self.root = root
        self.paths = paths
        self.ctrl = controller or AppController(paths)
        self.snap: Snapshot | None = None
        self._rendered_key: tuple | None = None
        self._banner_key: tuple | None = None
        self._sidebar_key: tuple | None = None
        self._links: dict[str, str] = {}
        self._date_values: list[date] = []
        self._expanded: set[str] = set()
        self._prereq_q: queue.Queue = queue.Queue()
        self._podcast_q: queue.Queue = queue.Queue()
        self._podcast_busy = False
        self._prereq_text: str | None = None  # None until a check starts
        self._poll_job: str | None = None
        self._cancelling = False
        self._cancel_thread: threading.Thread | None = None
        self._generated_at = None
        self.section = TOP
        self._read: set[str] = set(RD.load_reading(paths).read)
        self._mark_story: dict[str, Story] = {}
        self._story_marks: list[str] = []
        # 1.0 at 96 DPI; pixel sizes scale with Windows display scaling (fonts scale by themselves)
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)

        prefs0 = self.ctrl.snapshot().prefs
        self.mode = resolve_appearance(prefs0.appearance)
        self.c = PALETTES[self.mode]
        root.title(APP_NAME)
        root.minsize(self.px(780), self.px(540))
        root.geometry(load_window_geometry(paths) or f"{self.px(1120)}x{self.px(820)}")
        root.report_callback_exception = self._callback_error
        self._fonts()
        self._style()
        self._build()
        self.menu = self._build_menu()
        self._bind_keys()
        self.apply_theme(self.mode)
        self._update_search_hint()
        self.refresh_view(force=True)
        if auto_refresh:
            root.after(1200, self._launch_check)
        self._schedule_poll()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    def px(self, n: float) -> int:
        return int(round(n * self.scale))

    # ------------------------------------------------------------ setup
    def _fonts(self) -> None:
        families = set(tkfont.families(self.root))
        if sys.platform == "win32":
            text = "Segoe UI Variable Text" if "Segoe UI Variable Text" in families else "Segoe UI"
            display = "Segoe UI Variable Display" if "Segoe UI Variable Display" in families else text
        else:
            text = display = "TkDefaultFont"
        f = lambda size, family=text, **kw: tkfont.Font(family=family, size=size, **kw)  # noqa: E731
        self.f_base = f(11)
        self.f_small = f(9)
        self.f_bold = f(11, weight="bold")
        self.f_title = f(14, display, weight="bold")  # story headline
        self.f_h1 = f(22, display, weight="bold")  # section title
        self.f_app = f(13, display, weight="bold")
        self.f_sub = f(11)
        self.f_status = f(9, weight="bold")
        self.f_rank = f(13, display, weight="bold")
        self.f_kicker = f(8, weight="bold")
        self.f_side = f(10)
        self.f_side_bold = f(10, weight="bold")
        self.f_side_head = f(8, weight="bold")
        self.f_link = f(9, underline=True)
        self.f_small_link = f(9, underline=True)
        self.f_tiny = f(4)
        self.f_hair = f(1)
        self.f_button = f(10, weight="bold")
        self.f_brand = self.f_side_head
        self.f_chip = self.f_kicker
        self.f_heading = self.f_h1
        self.f_overview = self.f_sub

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
                style.configure(name, background=c["button"], troughcolor=c["card"], bordercolor=c["card"],
                                arrowcolor=c["muted"])
                style.map(name, background=[("active", c["button_active"])])
            self.root.option_add("*TCombobox*Listbox.background", c["field"])
            self.root.option_add("*TCombobox*Listbox.foreground", c["ink"])
            self.root.option_add("*TCombobox*Listbox.selectBackground", c["select"])
            self.root.option_add("*TCombobox*Listbox.selectForeground", c["ink"])
        style.configure("Header.TFrame", background=c["bg"])
        style.configure("Header.TLabel", background=c["bg"], foreground=c["ink"])
        style.configure("Muted.TLabel", background=c["bg"], foreground=c["muted"], font=self.f_small)
        style.configure("Refresh.TButton", font=self.f_button, padding=(self.px(14), self.px(4)))
        style.configure("Small.TButton", font=self.f_small, padding=(self.px(6), self.px(2)))
        style.configure("Accent.TButton", font=self.f_bold, padding=(self.px(14), self.px(3)))

    def apply_theme(self, mode: str) -> None:
        """Switch between the light and dark palettes without restarting."""
        self.mode = mode if mode in PALETTES else "light"
        self.c = c = PALETTES[self.mode]
        self._style()
        self.root.configure(bg=c["bg"])
        for w in (self.toolbar, self.banner_frame, self.title_box):
            w.configure(bg=c["bg"])
        self.app_label.configure(bg=c["bg"], fg=c["ink"])
        self.divider.configure(bg=c["rule"])
        self.sidebar.configure(bg=c["sidebar"])
        self.section_box.configure(bg=c["sidebar"])
        self.side_footer.configure(bg=c["sidebar"])
        self.status_row.configure(bg=c["sidebar"])
        self.status_dot.configure(bg=c["sidebar"])
        self.status_label.configure(bg=c["sidebar"], fg=c["ink"])
        self.times_label.configure(bg=c["sidebar"], fg=c["muted"])
        self.links_frame.configure(bg=c["sidebar"])
        self.search_hint.configure(bg=c["field"], fg=c["muted"])
        if hasattr(self, "menu"):
            self.menu.configure(bg=c["card"], fg=c["ink"], activebackground=c["accent"], activeforeground="#ffffff",
                                disabledforeground=c["muted"], bd=0, relief="flat")
        for lbl in self.footer_links:
            lbl.configure(bg=c["sidebar"], fg=c["link"])
        self.text.configure(bg=c["card"], fg=c["ink"], insertbackground=c["ink"], selectbackground=c["select"],
                            selectforeground=c["ink"])
        self._text_tags()
        dark_title_bar(self.root, self.mode == "dark")
        self._banner_key = self._sidebar_key = None
        if self.snap is not None:
            self.refresh_view(force=True)

    def _build_menu(self) -> tk.Menu:
        """The toolbar's "..." menu (no classic menu bar). Every command also has a shortcut or a link."""
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="Refresh now", accelerator="F5", command=self.refresh_now)
        menu.add_command(label="Details, sources and changes", accelerator="Ctrl+D", command=self.show_details)
        menu.add_command(label="Export as web page...", accelerator="Ctrl+E", command=self.export_html)
        menu.add_command(label="Settings...", accelerator="Ctrl+,", command=self.open_settings)
        menu.add_separator()
        menu.add_command(label="Mark all as read", command=self.mark_all_read)
        menu.add_command(label="Expand all sources", command=lambda: self._expand_all(True))
        menu.add_command(label="Collapse all sources", command=lambda: self._expand_all(False))
        menu.add_command(label="Latest edition", command=self.show_latest)
        menu.add_command(label="Demo edition (not real news)", command=self.show_demo)
        menu.add_separator()
        menu.add_command(label="Check local model (Ollama)", command=self._start_prereq_check)
        menu.add_command(label="Listen to the podcast", command=self.listen)
        menu.add_command(label="Record the podcast again", command=lambda: self.record_podcast(then_open=True))
        menu.add_command(label="Open podcasts folder", command=lambda: self._open_path(self.paths.podcasts_dir))
        menu.add_separator()
        menu.add_command(label="Open data folder", command=lambda: self._open_path(self.paths.root))
        menu.add_command(label="Open logs folder", command=lambda: self._open_path(self.paths.logs_dir))
        menu.add_separator()
        menu.add_command(label="How refreshing works", command=self.show_help)
        menu.add_command(label="Keyboard shortcuts", command=self.show_shortcuts)
        menu.add_command(label="About Agent Reach", command=self.show_about)
        menu.add_separator()
        menu.add_command(label="Quit", accelerator="Ctrl+Q", command=self._on_close)
        return menu

    def _bind_keys(self) -> None:
        for seq in ("<F5>", "<Control-r>"):
            self.root.bind(seq, lambda e: self.refresh_now())
        self.root.bind("<Control-e>", lambda e: self.export_html())
        self.root.bind("<Control-d>", lambda e: self.show_details())
        self.root.bind("<Control-comma>", lambda e: self.open_settings())
        self.root.bind("<Control-q>", lambda e: self._on_close())
        self.root.bind("<Control-f>", lambda e: self.search_entry.focus_set())
        for n in range(1, 8):
            self.root.bind(f"<Control-Key-{n}>", lambda e, n=n: self._section_by_number(n))
        for key, step in (("j", 1), ("k", -1)):
            self.root.bind(f"<KeyPress-{key}>", lambda e, step=step: None if self._typing() else self.jump_story(step))
        self.root.bind("<KeyPress-o>", lambda e: None if self._typing() else self.open_current())
        self.root.bind("<KeyPress-s>", lambda e: None if self._typing() else self.toggle_current_sources())
        self.root.bind("<KeyPress-p>", lambda e: None if self._typing() else self.listen())
        self.root.bind("<Home>", lambda e: self.text.yview_moveto(0))
        self.root.bind("<End>", lambda e: self.text.yview_moveto(1))
        self.root.bind("<Prior>", lambda e: self.text.yview_scroll(-1, "pages"))
        self.root.bind("<Next>", lambda e: self.text.yview_scroll(1, "pages"))

    def _typing(self) -> bool:
        try:
            return isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox, ttk.Spinbox))
        except (KeyError, tk.TclError):
            return False

    def _show_menu(self) -> None:
        b = self.more_btn
        try:
            self.menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())
        finally:
            self.menu.grab_release()

    def show_shortcuts(self) -> None:
        messagebox.showinfo(APP_NAME, (
            "Keyboard shortcuts\n\n"
            "J / K          next / previous story\n"
            "O              open the story's main article\n"
            "S              show or hide the story's sources\n"
            "P              listen to the podcast\n"
            "Ctrl+1 ... 7   Top Stories, then each category\n"
            "Ctrl+F         search (Esc clears)\n"
            "F5 or Ctrl+R   refresh now\n"
            "Ctrl+D         details, sources and changes\n"
            "Ctrl+E         export as a web page\n"
            "Ctrl+,         settings\n"
            "Home / End     top / bottom\n"
            "Ctrl+Q         quit\n\n"
            "Click a headline to open its main article; click Sources to see every report. Right-click a story "
            "to mark it read, or to follow or mute the names in it."), parent=self.root)

    def show_about(self) -> None:
        messagebox.showinfo(APP_NAME, f"{APP_NAME} {VERSION_LABEL}\n\nLocal daily news from public sources, summarized "
                                      "on this PC by a local model (Ollama). No paid or cloud AI service is used.\n\n"
                                      f"Data folder:\n{self.paths.root}", parent=self.root)

    def _build(self) -> None:
        root, c = self.root, self.c
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        pad = self.px(16)

        # ---- toolbar: the edition title on the left; search, edition date, Refresh and "..." on the right
        self.toolbar = tk.Frame(root, bg=c["bg"], padx=pad, pady=self.px(10))
        self.toolbar.grid(row=0, column=0, sticky="ew")
        self.toolbar.columnconfigure(0, weight=1)
        self.title_box = tk.Frame(self.toolbar, bg=c["bg"])
        self.title_box.grid(row=0, column=0, sticky="w")
        self.heading_var = tk.StringVar()
        self.date_line_var = tk.StringVar()  # the date is shown under each section title, not twice
        self.app_label = tk.Label(self.title_box, textvariable=self.heading_var, font=self.f_app, bg=c["bg"],
                                  fg=c["ink"])
        self.app_label.pack(side="left")
        right = ttk.Frame(self.toolbar, style="Header.TFrame")
        right.grid(row=0, column=1, sticky="e")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(right, textvariable=self.search_var, width=24)
        self.search_entry.pack(side="left", padx=(0, self.px(8)))
        self.search_entry.bind("<Escape>", lambda e: self._clear_filters())
        self.search_hint = tk.Label(self.search_entry, text="Search", bg=c["field"], fg=c["muted"], font=self.f_small,
                                    cursor="xterm")
        self.search_hint.bind("<Button-1>", lambda e: self.search_entry.focus_set())
        for seq in ("<FocusIn>", "<FocusOut>"):
            self.search_entry.bind(seq, lambda e: self._update_search_hint(), add="+")
        self.search_var.trace_add("write", lambda *a: (self._update_search_hint(), self._on_search()))
        self.date_var = tk.StringVar()
        self.date_box = ttk.Combobox(right, textvariable=self.date_var, state="readonly", width=15)
        self.date_box.pack(side="left", padx=(0, self.px(8)))
        self.date_box.bind("<<ComboboxSelected>>", self._on_date)
        self.progress = ttk.Progressbar(right, mode="indeterminate", length=self.px(90))
        self.cancel_btn = ttk.Button(right, text="Stop", style="Small.TButton", command=self.cancel_refresh)
        self.more_btn = ttk.Button(right, text="\u2026", width=3, style="Small.TButton", command=self._show_menu)
        self.more_btn.pack(side="right", padx=(self.px(6), 0))
        self.refresh_btn = ttk.Button(right, text="Refresh", style="Refresh.TButton", command=self.refresh_now)
        self.refresh_btn.pack(side="right")
        self.listen_btn = ttk.Button(right, text="\u25b6 Listen", style="Small.TButton", command=self.listen)
        self.listen_btn.pack(side="right", padx=(0, self.px(8)))

        self.banner_frame = tk.Frame(root, bg=c["bg"], padx=pad)
        self.banner_frame.grid(row=1, column=0, sticky="ew")

        # ---- main: sidebar | divider | reading pane
        main = tk.Frame(root, bg=c["rule"])
        main.grid(row=2, column=0, sticky="nsew")
        main.rowconfigure(0, weight=1)
        main.columnconfigure(2, weight=1)
        self.sidebar = tk.Frame(main, bg=c["sidebar"], width=self.px(232))
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)
        self.sidebar.columnconfigure(0, weight=1)
        self.sidebar.rowconfigure(1, weight=1)
        self.section_box = tk.Frame(self.sidebar, bg=c["sidebar"], padx=self.px(8), pady=self.px(10))
        self.section_box.grid(row=0, column=0, sticky="new")
        self.section_box.columnconfigure(0, weight=1)
        self.side_footer = tk.Frame(self.sidebar, bg=c["sidebar"], padx=self.px(14), pady=self.px(12))
        self.side_footer.grid(row=2, column=0, sticky="sew")
        self.status_row = tk.Frame(self.side_footer, bg=c["sidebar"])
        self.status_row.pack(fill="x", anchor="w")
        self.status_dot = tk.Canvas(self.status_row, width=self.px(10), height=self.px(10), bg=c["sidebar"],
                                    highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, self.px(6)))
        self.status_var = tk.StringVar()
        self.times_var = tk.StringVar()
        self.status_label = tk.Label(self.status_row, textvariable=self.status_var, bg=c["sidebar"], fg=c["ink"],
                                     font=self.f_status, anchor="w", justify="left", wraplength=self.px(190))
        self.status_label.pack(side="left", fill="x")
        self.times_label = tk.Label(self.side_footer, textvariable=self.times_var, bg=c["sidebar"], fg=c["muted"],
                                    font=self.f_small, anchor="w", justify="left", wraplength=self.px(205))
        self.times_label.pack(fill="x", anchor="w", pady=(self.px(4), self.px(8)))
        links = tk.Frame(self.side_footer, bg=c["sidebar"])
        links.pack(fill="x", anchor="w")
        self.footer_links = []
        for text, cmd in (("Details", self.show_details), ("Export", self.export_html), ("Settings", self.open_settings)):
            lbl = tk.Label(links, text=text, bg=c["sidebar"], fg=c["link"], font=self.f_small, cursor="hand2")
            lbl.pack(side="left", padx=(0, self.px(12)))
            lbl.bind("<Button-1>", lambda e, cmd=cmd: cmd())
            self.footer_links.append(lbl)
        self.links_frame = links
        self.divider = tk.Frame(main, bg=c["rule"], width=1)
        self.divider.grid(row=0, column=1, sticky="ns")
        body = tk.Frame(main, bg=c["card"])
        body.grid(row=0, column=2, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self.body_frame = body
        self.text = tk.Text(body, wrap="word", bg=c["card"], fg=c["ink"], relief="flat", bd=0,
                            padx=self.px(36), pady=self.px(22), font=self.f_base, cursor="arrow",
                            highlightthickness=0, spacing1=1, spacing3=1, takefocus=1)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.bind("<Button-1>", lambda e: self.text.focus_set(), add="+")
        self.text.bind("<Configure>", self._fit_column)
        for seq in ("<Button-3>", "<Button-2>"):  # right click (Windows/Linux), and Mac-style secondary click
            self.text.bind(seq, self._story_menu)
        self._text_tags()
        self.root.bind("<Configure>", self._on_resize)

    def _text_tags(self) -> None:
        t = self.text
        c = self.c
        indent = self.px(34)
        t.tag_configure("h1", font=self.f_h1, foreground=c["ink"], spacing3=self.px(2))
        t.tag_configure("sub", font=self.f_sub, foreground=c["muted"], spacing3=self.px(10))
        t.tag_configure("kicker", font=self.f_kicker, foreground=c["muted"], lmargin1=indent, lmargin2=indent,
                        spacing1=self.px(16))
        t.tag_configure("headline", font=self.f_title, foreground=c["ink"], lmargin1=0, lmargin2=indent,
                        tabs=(indent,), spacing1=self.px(3), spacing3=self.px(3))
        t.tag_configure("rank", font=self.f_rank, foreground=c["rank"])
        t.tag_configure("headline_link")
        t.tag_bind("headline_link", "<Enter>", lambda e: t.configure(cursor="hand2"))
        t.tag_bind("headline_link", "<Leave>", lambda e: t.configure(cursor="arrow"))
        # story divider: a spacer line, then a hairline (a tag background also fills the line's spacing)
        t.tag_configure("gap", font=self.f_hair, spacing1=self.px(12), spacing3=0)
        t.tag_configure("rule", font=self.f_hair, background=c["hairline"], spacing1=0, spacing3=0)
        t.tag_configure("body", font=self.f_base, foreground=c["ink2"], lmargin1=indent, lmargin2=indent,
                        spacing1=self.px(1), spacing3=self.px(2))
        t.tag_configure("why_label", font=self.f_kicker, foreground=c["accent"])
        t.tag_configure("why", font=self.f_base, foreground=c["ink2"], lmargin1=indent, lmargin2=indent,
                        spacing1=self.px(4))
        t.tag_configure("sources", font=self.f_small, foreground=c["muted"], lmargin1=indent, lmargin2=indent,
                        spacing1=self.px(5))
        t.tag_configure("evidence", font=self.f_small, foreground=c["ink2"], lmargin1=indent + self.px(10),
                        lmargin2=indent + self.px(22), spacing1=self.px(4))
        t.tag_configure("excerpt", font=self.f_small, foreground=c["muted"], lmargin1=indent + self.px(22),
                        lmargin2=indent + self.px(22))
        t.tag_configure("link", font=self.f_link, foreground=c["link"])
        t.tag_configure("small_link", font=self.f_small_link, foreground=c["link"])
        for tag in ("link", "small_link"):
            t.tag_bind(tag, "<Enter>", lambda e: t.configure(cursor="hand2"))
            t.tag_bind(tag, "<Leave>", lambda e: t.configure(cursor="arrow"))
        t.tag_configure("h2", font=self.f_title, foreground=c["ink"], spacing1=self.px(6), spacing3=self.px(6))
        t.tag_configure("plain", font=self.f_base, foreground=c["ink2"], spacing1=self.px(2), spacing3=self.px(2))
        t.tag_configure("muted", foreground=c["muted"])
        t.tag_configure("ok", foreground=c["ok"], font=self.f_bold)
        t.tag_configure("bad", foreground=c["bad"], font=self.f_bold)
        t.tag_configure("bold", font=self.f_bold)
        for name, (_tint, fg) in {**c["categories"], **c["labels"]}.items():
            t.tag_configure(f"chip:{name}", foreground=fg, font=self.f_kicker)
        for name, fg in c["tags"].items():
            t.tag_configure(f"tag:{name}", foreground=fg, font=self.f_kicker)
        t.tag_configure("read", foreground=c["muted"])  # headlines already read
        t.tag_configure("brief_head", font=self.f_kicker, foreground=c["accent"], spacing1=self.px(6),
                        spacing3=self.px(2))
        t.tag_configure("brief", font=self.f_base, foreground=c["ink2"], lmargin1=self.px(4),
                        lmargin2=self.px(18), spacing1=self.px(3))
        t.tag_raise("why_label")  # tag priority follows creation order, not the order a tuple lists them

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
        self.times_var.set("\n".join(compact_times(snap)))
        if snap.activity.running or self._cancelling:
            self.refresh_btn.state(["disabled"])
            self.refresh_btn.configure(text="Refreshing...")
            if not self.progress.winfo_ismapped():
                self.cancel_btn.pack(side="right", padx=(self.px(6), 0))
                self.progress.pack(side="right", padx=(self.px(8), 0))
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
            self.progress.pack_forget()
            self.cancel_btn.pack_forget()
        self._render_banners(snap)
        self._update_dates(snap)
        self._render_sidebar(snap)
        shown = snap.shown
        key = (shown.edition_date, shown.revision, shown.demo, shown.run_id) if shown else ("none", snap.first_run,
                                                                                          snap.activity.running)
        key = key + (self.section, self.search_var.get(), tuple(sorted(self._expanded)),
                     self._prereq_text if shown is None else "", snap.state.last_attempt_outcome)
        if force or key != self._rendered_key:
            self._rendered_key = key
            self._render_body(snap)

    def _draw_dot(self, kind: str) -> None:
        c = self.status_dot
        c.delete("all")
        d = self.px(8)
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
        for b in snap.banners[:3]:
            bg, fg = self.c["banners"].get(b.kind, self.c["banners"]["info"])
            tk.Label(self.banner_frame, text=b.text, bg=bg, fg=fg, anchor="w", justify="left", wraplength=width,
                     font=self.f_bold if b.kind == "demo" else self.f_small,
                     padx=self.px(12), pady=self.px(6)).pack(fill="x", pady=(0, self.px(8)))

    def _fit_column(self, event=None) -> None:
        """Keep lines readable: the text column is at most ~820 px wide and centred in the pane."""
        width = event.width if event is not None else self.text.winfo_width()
        pad = max(self.px(36), (width - self.px(820)) // 2)
        if int(str(self.text.cget("padx"))) != pad:
            self.text.configure(padx=pad)

    def _on_resize(self, event) -> None:
        if event.widget is self.root:
            width = max(self.px(400), event.width - self.px(60))
            for child in self.banner_frame.winfo_children():
                child.configure(wraplength=width)

    def _update_dates(self, snap: Snapshot) -> None:
        dates = self.ctrl.list_dates()
        if dates != self._date_values:
            self._date_values = dates
            labels = [format_short_date(d) for d in dates]
            self.date_box.configure(values=labels)
        shown = snap.shown
        # nothing to choose or hear before the first edition (an empty box and a dead button only confuse)
        self.date_box.configure(state="readonly" if dates else "disabled")
        if not self._podcast_busy:
            self.listen_btn.state(["!disabled"] if shown is not None and not shown.demo else ["disabled"])
        if shown is not None and not shown.demo and shown.edition_date in dates:
            self.date_box.current(dates.index(shown.edition_date))
        elif shown is not None and shown.demo:
            self.date_var.set("DEMO")
        else:
            self.date_var.set("")

    # ------------------------------------------------------------ sidebar
    def sections(self, edition) -> list[tuple[str, str, list[Story]]]:
        """[(key, title, stories)] for the sidebar: Top Stories, Following (when a followed topic
        appears), then non-empty categories. Stories about a muted topic are left out everywhere."""
        if edition is None:
            return []
        prefs = self.snap.prefs if self.snap else DailyPrefs()
        mute = lambda stories: RD.without_muted(stories, prefs.mute_topics)[0]  # noqa: E731
        out = [(TOP, "Top Stories", mute(top_stories(edition)))]
        follow = mute(RD.followed(edition.stories, prefs.follow_topics))
        if follow:
            out.append((FOLLOWING, "Following", follow))
        out += [(cat, cat, mute(stories)) for cat, stories in category_sections(edition)]
        return [x for x in out if x[2] or x[0] == TOP]

    def unread(self, stories: list[Story]) -> int:
        return sum(1 for s in stories if s.story_id not in self._read)

    def _render_sidebar(self, snap: Snapshot) -> None:
        sections = self.sections(snap.shown)
        if self.section not in {k for k, _, _ in sections} and self.section != SEARCH:
            self.section = TOP
        key = (tuple((k, len(s), self.unread(s)) for k, _, s in sections), self.section, self.mode)
        if key == self._sidebar_key:
            return
        self._sidebar_key = key
        for child in self.section_box.winfo_children():
            child.destroy()
        c = self.c
        if sections:
            tk.Label(self.section_box, text="SECTIONS", bg=c["sidebar"], fg=c["muted"], font=self.f_side_head,
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=self.px(8), pady=(0, self.px(4)))
        d = self.px(8)
        for i, (k, title, stories) in enumerate(sections, start=1):
            selected = k == self.section
            bg = c["sidebar_sel"] if selected else c["sidebar"]
            row = tk.Frame(self.section_box, bg=bg, padx=self.px(8), pady=self.px(5), cursor="hand2")
            row.grid(row=i, column=0, sticky="ew", pady=1)
            row.columnconfigure(1, weight=1)
            dot = tk.Canvas(row, width=d + 2, height=d + 2, bg=bg, highlightthickness=0)
            colour = (c["accent"] if k == TOP else c["tags"]["follow"] if k == FOLLOWING
                      else c["categories"].get(k, (None, c["muted"]))[1])
            if k == FOLLOWING:
                dot.configure(width=d + 6, height=d + 4)
                dot.create_text((d + 6) // 2, (d + 4) // 2, text="\u2605", fill=colour, font=self.f_small)
            else:
                dot.create_oval(1, 1, d, d, fill=colour, outline="")
            dot.grid(row=0, column=0, sticky="w", padx=(0, self.px(8)))
            name = tk.Label(row, text=title, bg=bg, fg=c["ink"], anchor="w",
                            font=self.f_side_bold if selected else self.f_side)
            name.grid(row=0, column=1, sticky="w")
            n_unread = self.unread(stories)  # like a mail app: the badge counts what is still unread
            count = tk.Label(row, text=str(n_unread) if n_unread else "", bg=bg, fg=c["muted"], font=self.f_small)
            count.grid(row=0, column=2, sticky="e")
            parts = (row, dot, name, count)
            for w in parts:
                w.bind("<Button-1>", lambda e, k=k: self.show_section(k))
            if not selected:
                row.bind("<Enter>", lambda e, ws=parts: [w.configure(bg=c["sidebar_hover"]) for w in ws])
                row.bind("<Leave>", lambda e, ws=parts: [w.configure(bg=c["sidebar"]) for w in ws])

    def show_section(self, key: str) -> None:
        self.section = key
        if self.search_var.get():
            self.search_var.set("")  # leaving search
        self.refresh_view(force=True)
        self.text.yview_moveto(0)

    def _section_by_number(self, n: int) -> None:
        sections = self.sections(self.snap.shown if self.snap else None)
        if 0 < n <= len(sections):
            self.show_section(sections[n - 1][0])

    def _update_search_hint(self) -> None:
        """'Search' placeholder inside the empty, unfocused search box (never written into the box)."""
        try:
            focused = self.root.focus_get() is self.search_entry
        except (KeyError, tk.TclError):  # focus in a closed dialog
            focused = False
        if self.search_var.get() or focused:
            self.search_hint.place_forget()
        else:
            self.search_hint.place(x=self.px(7), rely=0.5, anchor="w")

    def _on_search(self) -> None:
        if self.search_var.get().strip():
            self.section = SEARCH
        elif self.section == SEARCH:
            self.section = TOP
        self.refresh_view(force=True)

    # ------------------------------------------------------------ reading pane
    def _render_body(self, snap: Snapshot) -> None:
        t = self.text
        y = t.yview()[0]
        same = getattr(self, "_body_view", None) == (snap.shown.run_id if snap.shown else None, self.section)
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
        self._body_view = (snap.shown.run_id if snap.shown else None, self.section)
        t.yview_moveto(y if same else 0)

    def _render_collecting(self, snap: Snapshot) -> None:
        t = self.text
        t.insert("end", "Collecting today's news\n", ("h1",))
        t.insert("end", f"{snap.activity.message}\n\n", ("sub",))
        t.insert("end", "Public news sources are fetched over the internet, then the local model on this PC groups and "
                        "summarizes them. On a computer without a graphics card this can take 10 to 40 minutes.\n\n"
                        "You can close this window: the refresh continues in the background and the new edition "
                        "appears here when it is ready.\n", ("plain", "muted"))

    def _render_first_run(self, snap: Snapshot) -> None:
        t = self.text
        if snap.state.last_attempt_outcome:
            t.insert("end", "No edition yet\n", ("h1",))
            t.insert("end", "The last refresh did not produce an edition (the reason is shown above). Check the "
                            "items below, then choose Refresh.\n\n", ("plain",))
        else:
            t.insert("end", "Welcome to Agent Reach\n", ("h1",))
            t.insert("end", "Agent Reach collects public news, removes noise, groups related reports and writes a "
                            "short daily briefing with a local AI model (Ollama) on this PC. Nothing is sent to a paid "
                            "or cloud AI service.\n\n", ("plain",))
        t.insert("end", "Before the first refresh\n", ("bold",))
        t.insert("end", "1.  This app: ", ("plain",))
        t.insert("end", "ready\n", ("ok",))
        t.insert("end", "2.  Local model: ", ("plain",))
        if self._prereq_text is None:
            self._start_prereq_check(announce=False)
        text = self._prereq_text or ""
        t.insert("end", text + "\n", ("ok",) if text.startswith("ready") else ("plain",))
        t.insert("end", "3.  Internet access for the news sources.\n\n", ("plain",))
        btn = ttk.Button(t, text="Collect today's news now", style="Refresh.TButton", command=self.refresh_now)
        t.window_create("end", window=btn)
        t.insert("end", "    ")
        demo = ttk.Button(t, text="Preview the demo edition", command=self.show_demo)
        t.window_create("end", window=demo)
        t.insert("end", "\n\nA new edition is collected every 24 hours while your PC is on (\u2026 menu > How "
                        "refreshing works). The demo edition uses clearly marked synthetic stories.\n", ("plain", "muted"))

    def _render_edition(self, snap: Snapshot) -> None:
        t = self.text
        edition = snap.shown
        assert edition is not None
        self._generated_at = edition.generation_completed_utc
        query = self.search_var.get().strip()
        prefs = snap.prefs
        if self.section == SEARCH:
            title = "Search"
            stories, _ = RD.without_muted(filter_stories(edition.stories, "All", query), prefs.mute_topics)
            sub = f"{len(stories)} {'story' if len(stories) == 1 else 'stories'} matching “{query}”"
        else:
            sections = {k: (title, st) for k, title, st in self.sections(edition)}
            title, stories = sections.get(self.section, ("Top Stories", top_stories(edition)))
            d = edition.edition_date
            sub = f"{d:%A}, {format_long_date(d)}   ·   {len(stories)} {'story' if len(stories) == 1 else 'stories'}"
            if not edition.demo:
                sub += f"   ·   updated {format_clock(edition.generation_completed_utc)}"
            muted = RD.without_muted(edition.stories, prefs.mute_topics)[1]
            if muted:
                sub += f"   ·   {muted} muted"
        t.insert("end", title + "\n", ("h1",))
        t.insert("end", sub + "\n", ("sub",))
        if self.section == TOP and len(stories) >= 3:
            self._render_brief(stories)
        if not edition.stories:
            t.insert("end", "\nThis edition has no stories.\n", ("plain",))
        elif not stories:
            t.insert("end", "\nNothing matches your search. ", ("plain",))
            t.insert("end", "Clear search", self._link_tag("action:clear"))
            t.insert("end", "\n")
        now = self.ctrl.now_fn()
        show_category = self.section in (TOP, SEARCH, FOLLOWING)
        self._story_marks, self._mark_story = [], {}
        tags = RD.change_tags(edition)
        since = self.ctrl.developing(edition)
        for i, s in enumerate(stories, start=1):
            if i > 1:
                t.insert("end", "\n", ("gap",))
                t.insert("end", "\n", ("rule",))
            mark = f"story{i}"
            t.mark_set(mark, "end-1c")
            t.mark_gravity(mark, "left")
            self._story_marks.append(mark)
            self._mark_story[mark] = s
            day = RD.day_label(since[s.rank], edition.edition_date) if s.rank in since else ""
            self._render_story(s, now, number=i, show_category=show_category, change=tags.get(s.rank, ""),
                               day=day, follows=RD.matching_topics(s, prefs.follow_topics))
        t.insert("end", "\n")

    def _render_brief(self, stories: list[Story]) -> None:
        """'In brief': the lead sentence of the first five stories; a click jumps to the story."""
        t = self.text
        t.insert("end", "IN BRIEF\n", ("brief_head",))
        for i, (_story, line) in enumerate(RD.in_brief(stories), start=1):
            t.insert("end", "\u2022  ", ("brief",))
            t.insert("end", line, ("brief", self._action_tag(f"jump:{i}")))
            t.insert("end", "\n", ("brief",))
        t.tag_bind("brief", "<Enter>", lambda e: t.configure(cursor="hand2"))
        t.tag_bind("brief", "<Leave>", lambda e: t.configure(cursor="arrow"))

    def _action_tag(self, target: str) -> str:
        """A per-link tag name that runs ``target`` (URL, toggle or action) when clicked."""
        name = f"link{len(self._links)}"
        self._links[name] = target
        self.text.tag_bind(name, "<Button-1>", lambda e, n=name: self._click(n))
        return name

    def _link_tag(self, target: str, small: bool = False) -> tuple[str, str]:
        return ("small_link" if small else "link", self._action_tag(target))

    def jump_story(self, step: int) -> None:
        """j / k: scroll to the next or previous story (the first press from the top goes to story 2)."""
        marks = getattr(self, "_story_marks", [])
        if not marks:
            return
        t = self.text
        top = int(t.index("@0,0").split(".")[0])
        lines = [int(t.index(m).split(".")[0]) for m in marks]
        # the story being read: the last one starting at or just below the top of the view
        current = max((i for i, ln in enumerate(lines) if ln <= top + 2), default=0)
        if step > 0:
            target = min(current + 1, len(marks) - 1)
        else:
            target = current if top > lines[current] else max(current - 1, 0)
        t.yview(marks[target])

    def _click(self, name: str) -> str:
        target = self._links.get(name, "")
        if target == "action:clear":
            self._clear_filters()
        elif target == "action:details":
            self.show_details()
        elif target.startswith("toggle:"):
            sid = target.split(":", 1)[1]
            self._expanded.symmetric_difference_update({sid})
            if sid in self._expanded:
                self.mark_read([sid], refresh=False)
            self.refresh_view(force=True)
        elif target.startswith("open:"):
            sid, url = target[5:].split("\t", 1)
            self._open_url(url)
            self.mark_read([sid])
        elif target.startswith("jump:"):
            mark = f"story{target[5:]}"
            if mark in self._mark_story:
                self.text.yview(mark)
        else:
            self._open_url(target)
        return "break"

    def mark_read(self, story_ids: list[str], read: bool = True, refresh: bool = True) -> None:
        """Remember (in the data folder) which stories the reader has opened."""
        state = RD.set_read(self.paths, story_ids, utcnow(), read=read)
        self._read = set(state.read)
        self._sidebar_key = None
        if refresh:
            self.refresh_view(force=True)

    def story_at(self, index: str) -> Story | None:
        """The story whose block contains a text index (the last story mark at or before it)."""
        line = int(self.text.index(index).split(".")[0])
        found = None
        for mark in self._story_marks:
            if int(self.text.index(mark).split(".")[0]) <= line:
                found = self._mark_story.get(mark)
        return found

    def story_menu_items(self, story: Story) -> list[tuple[str, object]]:
        """(label, action) for the right-click menu of a story; None marks a separator."""
        items: list[tuple[str, object]] = []
        url = primary_url(story)
        if url:
            items.append(("Open article", lambda: (self._open_url(url), self.mark_read([story.story_id]))))
            items.append(("Copy link", lambda: (self.root.clipboard_clear(), self.root.clipboard_append(url))))
        if story.story_id in self._read:
            items.append(("Mark as unread", lambda: self.mark_read([story.story_id], read=False)))
        else:
            items.append(("Mark as read", lambda: self.mark_read([story.story_id])))
        prefs = self.snap.prefs if self.snap else DailyPrefs()
        names = RD.topic_suggestions(story)
        if names:
            items.append(("", None))
            for name in names:
                if name.lower() in {t.lower() for t in prefs.follow_topics}:
                    items.append((f"Stop following \u201c{name}\u201d", lambda n=name: self.set_topic(n, "follow", False)))
                else:
                    items.append((f"Follow \u201c{name}\u201d", lambda n=name: self.set_topic(n, "follow", True)))
            for name in names:
                items.append((f"Mute \u201c{name}\u201d", lambda n=name: self.set_topic(n, "mute", True)))
        return items

    def _story_menu(self, event) -> str | None:
        story = self.story_at(f"@{event.x},{event.y}")
        if story is None:
            return None
        menu = tk.Menu(self.root, tearoff=False)
        for label, action in self.story_menu_items(story):
            if action is None:
                menu.add_separator()
            else:
                menu.add_command(label=label, command=action)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def set_topic(self, topic: str, kind: str, on: bool) -> None:
        """Follow / unfollow / mute a topic from the story menu (saved in Settings > Topics)."""
        from agent_reach.daily.prefs import load_prefs

        prefs, _ = load_prefs(self.paths)
        key = "follow_topics" if kind == "follow" else "mute_topics"
        topics = [t for t in getattr(prefs, key) if t.lower() != topic.lower()]
        if on:
            topics.append(topic)
        setattr(prefs, key, topics)  # validated (whitespace, length, duplicates) like the Topics tab
        try:
            save_prefs(self.paths, prefs)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not save your topics: {exc}\n\nIs the settings file read-only "
                                           f"or open in another program?\n{self.paths.settings}", parent=self.root)
            return
        self._sidebar_key = None
        self.refresh_view(force=True)

    def current_story(self) -> Story | None:
        """The story at the top of the reading pane (what J / K moved to)."""
        story = self.story_at("@0,0")
        return story or (self._mark_story.get(self._story_marks[0]) if self._story_marks else None)

    def open_current(self) -> None:
        story = self.current_story()
        url = primary_url(story) if story else None
        if story is not None and url:
            self._open_url(url)
            self.mark_read([story.story_id])

    def toggle_current_sources(self) -> None:
        story = self.current_story()
        if story is not None:
            self._expanded.symmetric_difference_update({story.story_id})
            if story.story_id in self._expanded:
                self.mark_read([story.story_id], refresh=False)
            self.refresh_view(force=True)

    # ------------------------------------------------------------ podcast
    def listen(self) -> None:
        """Play the podcast of the edition on screen; record it first when it does not exist yet."""
        from agent_reach.daily.podcast import existing_podcast

        edition = self.snap.shown if self.snap else None
        if edition is None or edition.demo:
            messagebox.showinfo(APP_NAME, "There is no edition to listen to yet." if edition is None
                                else "The demo edition has no podcast.", parent=self.root)
            return
        audio = existing_podcast(self.paths, edition.edition_date)
        if audio is not None:
            self.play(audio)
        elif self._podcast_busy:
            self._flash_status("The podcast is being recorded...")
        elif messagebox.askyesno(APP_NAME, "Record today's podcast now? It is spoken by this PC's own voice and "
                                           "usually takes a minute or two.", parent=self.root):
            self.record_podcast(then_open=True)

    def record_podcast(self, then_open: bool = False) -> None:
        """Record the podcast in the background; the window stays responsive."""
        from agent_reach.daily.podcast import make_podcast

        edition = self.snap.shown if self.snap else None
        if edition is None or edition.demo or self._podcast_busy:
            return
        prefs = self.snap.prefs
        self._podcast_busy = True
        self.listen_btn.state(["disabled"])
        self._flash_status("Recording the podcast...")

        def work() -> None:
            try:
                self._podcast_q.put((make_podcast(self.paths, edition, prefs), then_open))
            except Exception as exc:  # noqa: BLE001 - reported in the window
                log.exception("podcast failed")
                self._podcast_q.put((exc, then_open))

        threading.Thread(target=work, name="podcast", daemon=True).start()
        self.root.after(300, self._poll_podcast)

    def _poll_podcast(self) -> None:
        try:
            result, then_open = self._podcast_q.get_nowait()
        except queue.Empty:
            self.root.after(300, self._poll_podcast)
            return
        self._podcast_busy = False
        self.listen_btn.state(["!disabled"])
        self.refresh_view(force=True)
        if isinstance(result, Exception) or not result.ok:
            text = str(result) if isinstance(result, Exception) else result.message
            messagebox.showwarning(APP_NAME, text, parent=self.root)
        elif then_open and result.audio is not None:
            self.play(result.audio)

    def play(self, audio: Path) -> None:
        """Open the recording in the default audio player."""
        if sys.platform == "win32":
            os.startfile(str(audio))  # type: ignore[attr-defined]
        else:
            webbrowser.open(audio.as_uri())

    def mark_all_read(self) -> None:
        shown = self.snap.shown if self.snap else None
        if shown is not None and not shown.demo:
            self.mark_read([s.story_id for s in shown.stories])

    def _open_url(self, target: str) -> None:
        url = safe_url(target)
        if url:
            webbrowser.open(url, new=2)

    def _render_story(self, s: Story, now, number: int, show_category: bool = True, change: str = "",
                      day: str = "", follows: list[str] | None = None) -> None:
        t = self.text
        strength = strength_of(s, self._generated_at)
        names = strength.publishers or [name for name, _ in story_publishers(s, limit=6)[0]]
        pubs, more = names[:3], max(0, len(names) - 3)
        # kicker: CATEGORY  LABEL  age · publishers
        if show_category:
            t.insert("end", s.category.value.upper(), ("kicker", f"chip:{s.category.value}"))
            t.insert("end", "   ", ("kicker",))
        if follows:
            t.insert("end", "\u2605 " + follows[0].upper(), ("kicker", "tag:follow"))
            t.insert("end", "   ", ("kicker",))
        if change:
            t.insert("end", change.upper(), ("kicker", f"tag:{change}"))
            t.insert("end", "   ", ("kicker",))
        if day:
            t.insert("end", day.upper(), ("kicker", "tag:day"))
            t.insert("end", "   ", ("kicker",))
        for label in s.labels:
            if change == "new" and label == "New":
                continue  # one NEW is enough
            tag = f"chip:{label}" if f"chip:{label}" in t.tag_names() else "kicker"
            t.insert("end", label.upper(), ("kicker", tag))
            t.insert("end", "   ", ("kicker",))
        meta = [story_age(s, now), ", ".join(pubs) + (f" +{more}" if more else "")]
        t.insert("end", "  \u00b7  ".join(m for m in meta if m) + "\n", ("kicker",))
        t.insert("end", f"{number}\t", ("headline", "rank"))
        url = primary_url(s)
        read = ("read",) if s.story_id in self._read else ()
        if url:  # the headline opens the main article (hover: accent colour) and marks the story read
            name = self._action_tag(f"open:{s.story_id}\t{url}")
            t.insert("end", s.headline, ("headline", "headline_link", name) + read)
            t.tag_bind(name, "<Enter>", lambda e, n=name: t.tag_configure(n, foreground=self.c["accent"]), add="+")
            t.tag_bind(name, "<Leave>", lambda e, n=name: t.tag_configure(n, foreground=""), add="+")
            t.insert("end", "\n", ("headline",))
        else:
            t.insert("end", s.headline + "\n", ("headline",) + read)
        t.insert("end", " ".join(s.sentences) + "\n", ("body",))
        if s.why_it_matters:
            t.insert("end", "WHY IT MATTERS   ", ("why", "why_label"))
            t.insert("end", s.why_it_matters + "\n", ("why",))
        expanded = s.story_id in self._expanded
        t.insert("end", "Hide sources" if expanded else f"Sources ({len(s.evidence)})",
                 ("sources",) + self._link_tag(f"toggle:{s.story_id}", small=True))
        t.insert("end", f"   \u00b7   {strength.label}\n", ("sources",))
        if expanded:
            t.insert("end", f"{strength.label}: {'; '.join(strength.reasons)}.\n", ("excerpt",))
            self._render_evidence(s)

    def _render_evidence(self, s: Story) -> None:
        t = self.text
        for ev in s.evidence:
            t.insert("end", "• ", ("evidence",))
            url = safe_url(ev.url)
            if url:
                t.insert("end", ev.title, ("evidence",) + self._link_tag(url, small=True))
            else:
                t.insert("end", ev.title, ("evidence",))
            extra = [ev.publisher or ev.source_name]
            if ev.published_at_utc:
                extra.append("published " + format_central(ev.published_at_utc))
            else:
                extra.append("publication time not stated")
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

        # the Tk thread notices the end of this thread itself (poll_cancel): Tk calls from another thread
        # are not reliable, and a lost call would leave the window on 'Refreshing...' for good
        self._cancel_thread = threading.Thread(target=work, name="cancel-refresh", daemon=True)
        self._cancel_thread.start()
        self.root.after(250, self._poll_cancel)

    def _poll_cancel(self) -> None:
        if self._cancel_thread is not None and self._cancel_thread.is_alive():
            self.root.after(250, self._poll_cancel)
            return
        self._cancel_thread = None
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
        self.search_var.set("")
        if self.section == SEARCH:
            self.section = TOP
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
        self._changes_tab(nb, snap)
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
            line += f"; {sum(f.status == 'ok' for f in feeds)} of {len(feeds)} feeds delivered something"
        ttk.Label(frm, text=line + ")", font=w.f_bold).pack(anchor="w", pady=(0, w.px(6)))
        tree = self._tree(frm, [("name", "Channel / publisher feed", 250, "w"), ("status", "Status", 80, "w"),
                                ("collected", "Collected", 90, "e"), ("used", "Used", 60, "e"),
                                ("notes", "Notes", 360, "w")])
        labels = {"ok": "OK", "partial": "PARTIAL", "empty": "EMPTY", "failed": "FAILED"}
        for h in edition.source_health:
            failed = any(f.status == "failed" for f in h.feeds)
            note = feed_note(h) if h.feeds else friendly_error(h.error)
            node = tree.insert("", "end", text=h.name, open=failed,
                               values=(labels.get(h.status, h.status.upper()), h.item_count, h.used, note))
            for f in sorted(h.feeds, key=lambda f: (f.status == "ok", -f.used, f.name.lower())):
                tree.insert(node, "end", text=f.name, values=(labels.get(f.status, f.status.upper()), f.collected,
                                                              f.used, friendly_error(f.error) or (f.category or "")))
        ttk.Label(frm, text="Collected: items taken in this refresh. Used: items cited in this edition. PARTIAL: the "
                            "channel answered but some of it failed (for example a rate limit or a broken feed). Expand "
                            "a channel to see its feeds, YouTube channels or Google News sections.", style="Muted.TLabel",
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

    def _changes_tab(self, nb: ttk.Notebook, snap: Snapshot) -> None:
        """What changed since the last refresh (kept out of the reading view)."""
        rows: list[tuple[str, str]] = []
        edition = snap.shown
        ch = edition.changes if edition is not None else None
        if edition is None or edition.demo:
            rows.append(("", "No edition to compare."))
        elif ch is None:
            rows.append(("", "First edition: there is no earlier edition to compare with."))
        else:
            rows.append(("Compared with", f"the edition generated {format_central(ch.compared_generated_utc)}"
                                          + (f" (revision {ch.compared_revision})" if ch.compared_revision > 1 else "")))
            rows.append(("Summary", ch.summary() + (f"; {ch.unchanged} unchanged" if ch.unchanged else "")))
            names = {"new": "New", "updated": "Updated", "signals_up": "Growing", "signals_down": "Fading",
                     "gone": "No longer listed"}
            for c in [*ch.new, *ch.updated, *ch.signals_up, *ch.signals_down, *ch.gone]:
                detail = f" \u2014 {c.detail}" if c.detail and c.kind not in ("new", "gone") else ""
                rows.append((names[c.kind], c.headline + detail))
        self._text_tab(nb, "Changes", rows)

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
        from agent_reach.daily.feedhealth import failing_feeds, load_feed_health
        from agent_reach.daily.timeutil import utcnow

        # feed doctor: feeds that have failed in every refresh for 3+ days
        self.failing = {r.url.lower(): r for r in failing_feeds(load_feed_health(window.paths), utcnow())}
        nb = ttk.Notebook(top)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        self._sources_tab(nb)
        self._feeds_tab(nb)
        self._model_tab(nb)
        self._schedule_tab(nb)
        self._storage_tab(nb)
        self._topics_tab(nb)
        self._podcast_tab(nb)
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
        ttk.Label(frm, text="Collection channels. 'Publisher feeds' and 'YouTube' read the publishers and channels "
                            "on the next tab; the others are aggregators and trend lists. Tech-only channels are capped "
                            "in Top Stories.", wraplength=self.window.px(740)).grid(row=0, column=0, columnspan=2, sticky="w",
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
        cols = ("on", "kind", "category", "result")
        self.feed_tree = tree = ttk.Treeview(box, columns=cols, show="tree headings", height=12, selectmode="extended")
        tree.heading("#0", text="Publisher", anchor="w")
        tree.heading("on", text="On", anchor="w")
        tree.heading("kind", text="Type", anchor="w")
        tree.heading("category", text="Category", anchor="w")
        tree.heading("result", text="Last test", anchor="w")
        tree.column("#0", width=w.px(230), stretch=False)
        tree.column("on", width=w.px(40), stretch=False)
        tree.column("kind", width=w.px(70), stretch=False)
        tree.column("category", width=w.px(110), stretch=False)
        tree.column("result", width=w.px(260), stretch=True)
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
        self.off_failing_btn = ttk.Button(tests, text="Turn off failing feeds", command=self.turn_off_failing)
        if self.failing:
            self.off_failing_btn.pack(side="right", padx=(0, 4))
        ttk.Label(frm, text="Each feed (an RSS feed or a YouTube channel) has its own allowance and its own health "
                            "line in Details. A feed that stops working never blocks the edition; it shows as failed. "
                            "YouTube channels are read when 'YouTube' is on in Sources. Testing fetches the feed now "
                            "over the internet.", style="Muted.TLabel",
                  wraplength=w.px(740)).grid(row=4, column=0, sticky="w", pady=(6, 0))
        self._fill_feeds()

    def _fill_feeds(self, select: list[str] | None = None) -> None:
        tree = self.feed_tree
        tree.delete(*tree.get_children())
        for i, f in enumerate(self.feeds):
            note = self.feed_results.get(f.url, "")
            bad = self.failing.get(f.url.lower())
            if not note and bad is not None and bad.failing_since_utc is not None:
                note = (f"Failing since {format_short_date(bad.failing_since_utc.date())} "
                        f"({bad.failures_in_row} refreshes): {friendly_error(bad.last_error) or 'no articles'}")
            tree.insert("", "end", iid=str(i), text=f.name,
                        values=("yes" if f.enabled else "no", f.kind, f.category, note))
        if select:
            ids = [str(i) for i, f in enumerate(self.feeds) if f.url in select]
            tree.selection_set(ids)
            if ids:
                tree.see(ids[0])
        on = [f for f in self.feeds if f.enabled]
        videos = sum(f.kind == "YouTube" for f in on)
        self.feeds_summary.set(f"{len(on) - videos} feeds and {videos} YouTube channels on, from "
                               f"{len({f.publisher for f in on})} publishers. Double-click one to edit it.")

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

    def turn_off_failing(self) -> None:
        """Turn off every feed the feed doctor flags (they stay in the list and can be turned on again)."""
        hit = [f for f in self.feeds if f.enabled and f.url.lower() in self.failing]
        for f in hit:
            f.enabled = False
        self._fill_feeds(select=[f.url for f in hit])

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
        self._task_bg(self._task_text)

    def _storage_tab(self, nb) -> None:
        frm = self._tab(nb, "Storage")
        self.retention_var = tk.StringVar(value=str(self.prefs.retention_days))
        self.max_var = tk.StringVar(value=str(self.prefs.max_stories))
        self.age_var = tk.StringVar(value=f"{self.prefs.max_story_age_hours:g}")
        ttk.Label(frm, text="Keep editions for (days):").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Spinbox(frm, from_=1, to=3650, textvariable=self.retention_var, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(frm, text="Stories per section (Top Stories and each category):").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Spinbox(frm, from_=3, to=30, textvariable=self.max_var, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(frm, text="Leave out stories published more than (hours) ago:").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Spinbox(frm, from_=6, to=336, textvariable=self.age_var, width=8).grid(row=2, column=1, sticky="w")
        ttk.Label(frm, text=f"Data folder: {self.window.paths.root}", wraplength=560).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(12, 4))
        ttk.Button(frm, text="Open data folder",
                   command=lambda: DailyWindow._open_path(self.window.paths.root)).grid(row=4, column=0, sticky="w")
        ttk.Separator(frm).grid(row=5, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Button(frm, text="Delete all cached editions...", command=self._reset_cache).grid(row=6, column=0, sticky="w")
        ttk.Label(frm, text="Fewer, stronger stories are preferred to filler: a section can have fewer stories than "
                            "this. The newest edition is never deleted by retention, even after failed refreshes.",
                  wraplength=560, foreground=self.window.c["muted"]).grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _podcast_tab(self, nb) -> None:
        from agent_reach.daily.podcast import list_voices

        frm = self._tab(nb, "Podcast")
        self.podcast_auto_var = tk.BooleanVar(value=self.prefs.podcast_auto)
        self.podcast_voice_var = tk.StringVar(value=self.prefs.podcast_voice or "System default")
        self.podcast_rate_var = tk.StringVar(value=str(self.prefs.podcast_rate))
        self.podcast_stories_var = tk.StringVar(value=str(self.prefs.podcast_stories))
        self.podcast_keep_var = tk.StringVar(value=str(self.prefs.podcast_keep_days))
        ttk.Checkbutton(frm, text="Record a podcast of the top stories after every refresh",
                        variable=self.podcast_auto_var).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Label(frm, text="Voice:").grid(row=1, column=0, sticky="w", pady=3)
        self.voice_box = ttk.Combobox(frm, textvariable=self.podcast_voice_var, state="readonly", width=34,
                                      values=["System default"])
        self.voice_box.grid(row=1, column=1, sticky="w")
        ttk.Label(frm, text="Speed (-5 slower to 5 faster):").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Spinbox(frm, from_=-5, to=5, textvariable=self.podcast_rate_var, width=6).grid(row=2, column=1, sticky="w")
        ttk.Label(frm, text="Top stories told in full:").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Spinbox(frm, from_=3, to=15, textvariable=self.podcast_stories_var, width=6).grid(row=3, column=1,
                                                                                              sticky="w")
        ttk.Label(frm, text="Keep podcasts for (days):").grid(row=4, column=0, sticky="w", pady=3)
        ttk.Spinbox(frm, from_=1, to=60, textvariable=self.podcast_keep_var, width=6).grid(row=4, column=1, sticky="w")
        ttk.Label(frm, text="The podcast reads the edition's own headlines, summaries and 'why it matters' notes, then "
                            "a quick round of headlines from each section and the topics you follow (about 5 to 8 "
                            "minutes). It is spoken by the voices built into Windows - add more under Windows "
                            "Settings > Time & language > Speech - and saved as a .wav file with a transcript in "
                            "the podcasts folder. Nothing is sent anywhere.",
                  wraplength=self.window.px(740), style="Muted.TLabel").grid(row=5, column=0, columnspan=2,
                                                                             sticky="w", pady=(12, 0))

        def show(result) -> None:
            if not isinstance(result, Exception) and result:
                self.voice_box.configure(values=["System default", *result])

        self._bg(list_voices, show)

    def _topics_tab(self, nb) -> None:
        frm = self._tab(nb, "Topics")
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(2, weight=1)
        ttk.Label(frm, text="One topic per line: a name, team, company or phrase (whole words, any case). You can "
                            "also right-click any story to follow or mute its names.",
                  wraplength=self.window.px(740)).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(frm, text="Follow (starred, and gathered under Following)", font=self.window.f_bold).grid(
            row=1, column=0, sticky="w")
        ttk.Label(frm, text="Mute (hidden everywhere)", font=self.window.f_bold).grid(row=1, column=1, sticky="w",
                                                                                     padx=(12, 0))
        c = self.window.c
        self.follow_text = tk.Text(frm, height=10, width=30, bg=c["field"], fg=c["ink"], insertbackground=c["ink"],
                                   relief="solid", bd=1, font=self.window.f_base)
        self.follow_text.grid(row=2, column=0, sticky="nsew", pady=(4, 0))
        self.mute_text = tk.Text(frm, height=10, width=30, bg=c["field"], fg=c["ink"], insertbackground=c["ink"],
                                 relief="solid", bd=1, font=self.window.f_base)
        self.mute_text.grid(row=2, column=1, sticky="nsew", pady=(4, 0), padx=(12, 0))
        self.follow_text.insert("1.0", "\n".join(self.prefs.follow_topics))
        self.mute_text.insert("1.0", "\n".join(self.prefs.mute_topics))

    def _topic_lines(self, widget: tk.Text) -> list[str]:
        return [line.strip() for line in widget.get("1.0", "end").splitlines() if line.strip()]

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
                follow_topics=self._topic_lines(self.follow_text), mute_topics=self._topic_lines(self.mute_text),
                podcast_auto=self.podcast_auto_var.get(), podcast_rate=int(self.podcast_rate_var.get()),
                podcast_voice="" if self.podcast_voice_var.get() == "System default" else self.podcast_voice_var.get(),
                podcast_stories=int(self.podcast_stories_var.get()), podcast_keep_days=int(self.podcast_keep_var.get()),
            )
            prefs = DailyPrefs.model_validate(data)
            if "news_rss" in prefs.enabled_sources and not prefs.enabled_rss_feeds():
                raise ValueError("'Publisher feeds' is on but every publisher feed is turned off.")
        except (ValueError, TypeError) as exc:
            messagebox.showerror(APP_NAME, f"Please check the settings:\n\n{exc}", parent=self.top)
            return
        try:
            save_prefs(self.window.paths, prefs)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not save the settings: {exc}\n\nIs the settings file read-only "
                                           f"or open in another program?\n{self.window.paths.settings}", parent=self.top)
            return
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
        ttk.Label(frm, text="Address (RSS/Atom feed or\nYouTube channel)").grid(row=1, column=0, sticky="w", pady=3,
                                                                              padx=(0, 8))
        ttk.Entry(frm, textvariable=self.url_var, width=48).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(frm, text="Category").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Combobox(frm, textvariable=self.cat_var, state="readonly", values=all_categories(), width=18).grid(
            row=2, column=1, sticky="w", pady=3)
        self.result_var = tk.StringVar(value="Business and health feeds belong under News. For YouTube, paste the "
                                             "channel address (youtube.com/channel/UC...).")
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
