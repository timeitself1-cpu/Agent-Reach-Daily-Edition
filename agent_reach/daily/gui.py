"""Agent Reach Daily desktop window (tkinter/ttk, no extra dependencies).

Run with ``pythonw -m agent_reach.daily.gui`` (no console window). The window renders cached
editions only; refreshes run in a background worker process and report progress through
the data folder, polled once per second while a refresh runs.
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

from agent_reach.daily import APP_NAME
from agent_reach.daily.app import AppController, Snapshot, filter_stories
from agent_reach.daily.edition import DailyEdition, Story, all_categories, safe_url
from agent_reach.daily.paths import DataPaths
from agent_reach.daily.prefs import DailyPrefs, SOURCE_NOTES, save_prefs
from agent_reach.daily.timeutil import format_central, format_short_date

log = logging.getLogger(__name__)

CATEGORY_COLORS = {
    "News": ("#e8f0fe", "#1a4fa0"), "Sports": ("#e6f4ea", "#137333"), "Entertainment": ("#fce8f3", "#a1145c"),
    "Tech": ("#eceff1", "#37474f"), "Science & AI": ("#fef7e0", "#7a4f00"), "Internet Culture": ("#f3e8fd", "#6a1b9a"),
}
LABEL_COLORS = {
    "Hot": ("#fde2e1", "#a50e0e"), "Rising": ("#fef0d9", "#8a4b00"), "New": ("#e0f2f1", "#00695c"),
    "Uncertain trend": ("#eceff1", "#455a64"), "Steady": ("#f1f3f4", "#5f6368"), "Cooling": ("#f1f3f4", "#5f6368"),
    "Fading": ("#f1f3f4", "#5f6368"),
}
BANNER_COLORS = {"info": ("#e8f0fe", "#174ea6"), "warn": ("#fff4d6", "#6b4e00"),
                 "error": ("#fce8e6", "#a50e0e"), "demo": ("#ffd7d7", "#8a1010")}
BG = "#f6f5f2"
CARD = "#ffffff"
INK = "#1d1d1f"
MUTED = "#5f6368"
LINK = "#1a5fb4"
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
        self._links: dict[str, str] = {}
        self._date_values: list[date] = []
        self._prereq_q: queue.Queue = queue.Queue()
        self._prereq_text: str | None = None  # None until the first-run screen starts a check
        self._poll_job: str | None = None

        root.title(APP_NAME)
        root.geometry("1040x780")
        root.minsize(720, 520)
        root.configure(bg=BG)
        self._fonts()
        self._style()
        self._build_menu()
        self._build()
        self.refresh_view(force=True)
        if auto_refresh:
            root.after(1200, self._launch_check)
        self._schedule_poll()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------ setup
    def _fonts(self) -> None:
        family = "Segoe UI" if sys.platform == "win32" else "TkDefaultFont"
        self.f_base = tkfont.Font(family=family, size=11)
        self.f_small = tkfont.Font(family=family, size=9)
        self.f_heading = tkfont.Font(family=family, size=20, weight="bold")
        self.f_sub = tkfont.Font(family=family, size=11)
        self.f_title = tkfont.Font(family=family, size=14, weight="bold")
        self.f_bold = tkfont.Font(family=family, size=11, weight="bold")
        self.f_chip = tkfont.Font(family=family, size=9, weight="bold")
        self.f_overview = tkfont.Font(family=family, size=12)
        self.f_link = tkfont.Font(family=family, size=10, underline=True)
        self.f_tiny = tkfont.Font(family=family, size=2)

    def _style(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Header.TFrame", background=BG)
        style.configure("Header.TLabel", background=BG, foreground=INK)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=self.f_small)
        style.configure("Accent.TButton", font=self.f_bold)

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
        m_view.add_command(label="Latest edition", command=self.show_latest)
        m_view.add_command(label="Source health...", command=self.show_sources)
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
            APP_NAME, f"{APP_NAME}\nLocal daily news from public feeds, summarized on this PC by Ollama.\n\n"
                      f"Data folder:\n{self.paths.root}", parent=self.root))
        menubar.add_cascade(label="Help", menu=m_help)
        self.root.config(menu=menubar)
        self.root.bind("<F5>", lambda e: self.refresh_now())
        self.root.bind("<Control-e>", lambda e: self.export_html())
        self.root.bind("<Control-f>", lambda e: self.search_entry.focus_set())

    def _build(self) -> None:
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        header = ttk.Frame(root, style="Header.TFrame", padding=(18, 14, 18, 6))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.heading_var = tk.StringVar()
        self.updated_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.times_var = tk.StringVar()
        ttk.Label(header, textvariable=self.heading_var, style="Header.TLabel", font=self.f_heading).grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.updated_var, style="Header.TLabel", font=self.f_sub).grid(row=1, column=0, sticky="w")
        status_row = ttk.Frame(header, style="Header.TFrame")
        status_row.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        status_row.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(status_row, textvariable=self.status_var, style="Header.TLabel", font=self.f_bold)
        self.status_label.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(status_row, mode="indeterminate", length=160)
        self.cancel_btn = ttk.Button(status_row, text="Cancel refresh", command=self.cancel_refresh)
        ttk.Label(header, textvariable=self.times_var, style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=(2, 0))

        bar = ttk.Frame(root, style="Header.TFrame", padding=(18, 4, 18, 6))
        bar.grid(row=1, column=0, sticky="ew")
        self.refresh_btn = ttk.Button(bar, text="Refresh now", style="Accent.TButton", command=self.refresh_now)
        self.refresh_btn.pack(side="left")
        ttk.Label(bar, text="  Edition:", style="Header.TLabel").pack(side="left")
        self.date_var = tk.StringVar()
        self.date_box = ttk.Combobox(bar, textvariable=self.date_var, state="readonly", width=22)
        self.date_box.pack(side="left", padx=(4, 10))
        self.date_box.bind("<<ComboboxSelected>>", self._on_date)
        ttk.Label(bar, text="Category:", style="Header.TLabel").pack(side="left")
        self.cat_var = tk.StringVar(value="All")
        self.cat_box = ttk.Combobox(bar, textvariable=self.cat_var, state="readonly", width=16,
                                    values=["All", *all_categories()])
        self.cat_box.pack(side="left", padx=(4, 10))
        self.cat_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_view(force=True))
        ttk.Label(bar, text="Search:", style="Header.TLabel").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(bar, textvariable=self.search_var, width=22)
        self.search_entry.pack(side="left", padx=(4, 4))
        self.search_var.trace_add("write", lambda *a: self.refresh_view(force=True))
        ttk.Button(bar, text="Clear", command=self._clear_filters).pack(side="left")
        ttk.Button(bar, text="Settings", command=self.open_settings).pack(side="right")
        ttk.Button(bar, text="Export HTML", command=self.export_html).pack(side="right", padx=(0, 6))
        ttk.Button(bar, text="Sources", command=self.show_sources).pack(side="right", padx=(0, 6))

        self.banner_frame = tk.Frame(root, bg=BG, padx=18)
        self.banner_frame.grid(row=2, column=0, sticky="ew")

        body = tk.Frame(root, bg=BG, padx=18, pady=6)
        body.grid(row=3, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.text = tk.Text(body, wrap="word", bg=CARD, fg=INK, relief="flat", bd=0, padx=22, pady=16,
                            font=self.f_base, cursor="arrow", highlightthickness=1, highlightbackground="#e2e0da",
                            spacing1=2, spacing3=2)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self._text_tags()

        footer = ttk.Frame(root, style="Header.TFrame", padding=(18, 2, 18, 8))
        footer.grid(row=4, column=0, sticky="ew")
        self.health_var = tk.StringVar()
        ttk.Label(footer, textvariable=self.health_var, style="Muted.TLabel").pack(side="left")
        self.root.bind("<Configure>", self._on_resize)

    def _text_tags(self) -> None:
        t = self.text
        t.tag_configure("overview", font=self.f_overview, spacing3=10)
        t.tag_configure("rank", font=self.f_title, foreground=MUTED)
        t.tag_configure("headline", font=self.f_title, spacing1=6)
        t.tag_configure("meta", font=self.f_small, foreground=MUTED)
        t.tag_configure("body", font=self.f_base, spacing1=4, lmargin1=2, lmargin2=2)
        t.tag_configure("why_label", font=self.f_bold)
        t.tag_configure("src_head", font=self.f_small, foreground=MUTED, spacing1=6)
        t.tag_configure("evidence", font=self.f_small, lmargin1=14, lmargin2=26)
        t.tag_configure("excerpt", font=self.f_small, foreground=MUTED, lmargin1=26, lmargin2=26)
        t.tag_configure("link", font=self.f_link, foreground=LINK)
        t.tag_bind("link", "<Enter>", lambda e: t.configure(cursor="hand2"))
        t.tag_bind("link", "<Leave>", lambda e: t.configure(cursor="arrow"))
        t.tag_configure("sep", font=self.f_tiny, background="#e8e6e0", spacing1=10, spacing3=10)
        t.tag_configure("h2", font=self.f_title, spacing1=6, spacing3=6)
        t.tag_configure("muted", foreground=MUTED)
        t.tag_configure("ok", foreground="#137333", font=self.f_bold)
        t.tag_configure("bad", foreground="#a50e0e", font=self.f_bold)
        for name, (bg, fg) in {**CATEGORY_COLORS, **LABEL_COLORS}.items():
            t.tag_configure(f"chip:{name}", background=bg, foreground=fg, font=self.f_chip)

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
        self.updated_var.set(snap.updated)
        self.status_var.set(snap.status)
        self.times_var.set(f"{snap.last_success}     {snap.next_refresh}")
        if snap.activity.running:
            self.refresh_btn.state(["disabled"])
            self.progress.grid(row=0, column=1, padx=8)
            self.cancel_btn.grid(row=0, column=2)
            self.progress.start(12)
            if not was_running:
                self._schedule_poll()
        else:
            self.refresh_btn.state(["!disabled"])
            self.progress.stop()
            self.progress.grid_remove()
            self.cancel_btn.grid_remove()
        self._render_banners(snap)
        self._update_dates(snap)
        shown = snap.shown
        if shown is not None:
            ok = sum(1 for h in shown.source_health if h.status in ("ok", "partial"))
            bad = [h.name for h in shown.source_health if h.status == "failed"]
            self.health_var.set(f"Sources: {ok} of {len(shown.source_health)} responded"
                                + (f" - unavailable: {', '.join(bad)}" if bad else "")
                                + f"   |   Model: {shown.model.llm_model} ({shown.model.summaries.replace('_', ' ')})")
        else:
            self.health_var.set(f"Data folder: {self.paths.root}")
        key = (shown.edition_date, shown.revision, shown.demo, shown.run_id) if shown else ("none", snap.first_run,
                                                                                          snap.activity.running)
        key = key + (self.cat_var.get(), self.search_var.get(), self._prereq_text if snap.first_run else "")
        if force or key != self._rendered_key:
            self._rendered_key = key
            self._render_body(snap)

    def _render_banners(self, snap: Snapshot) -> None:
        for child in self.banner_frame.winfo_children():
            child.destroy()
        width = max(400, self.root.winfo_width() - 60)
        for b in snap.banners[:8]:
            bg, fg = BANNER_COLORS.get(b.kind, BANNER_COLORS["info"])
            tk.Label(self.banner_frame, text=b.text, bg=bg, fg=fg, anchor="w", justify="left", wraplength=width,
                     font=self.f_bold if b.kind in ("demo", "error") else self.f_small,
                     padx=10, pady=5).pack(fill="x", pady=2)

    def _on_resize(self, event) -> None:
        if event.widget is self.root:
            width = max(400, event.width - 60)
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
            i = dates.index(shown.edition_date)
            self.date_box.current(i)
        elif shown is not None and shown.demo:
            self.date_var.set("DEMO")
        else:
            self.date_var.set("")

    def _insert_chip(self, name: str) -> None:
        self.text.insert("end", f" {name} ", (f"chip:{name}",))
        self.text.insert("end", " ")

    def _render_body(self, snap: Snapshot) -> None:
        t = self.text
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
            self._render_edition(snap.shown)
        t.configure(state="disabled")
        t.yview_moveto(0)

    def _render_collecting(self, snap: Snapshot) -> None:
        t = self.text
        t.insert("end", "Collecting today's news\n", ("h2",))
        t.insert("end", f"{snap.activity.message}\n\n", ("body",))
        t.insert("end", "Sources are fetched over the internet, then the local model on this PC groups and summarizes "
                        "them. On a computer without a graphics card this can take 10 to 40 minutes. You can close "
                        "this window; the refresh keeps running in the background.\n", ("body", "muted"))

    def _render_first_run(self, snap: Snapshot) -> None:
        t = self.text
        if snap.state.last_attempt_outcome:
            t.insert("end", "No edition yet\n", ("h2",))
            t.insert("end", "The last refresh did not produce an edition. Details are shown above. Check the items "
                            "below, then use Refresh now.\n\n", ("body",))
        else:
            t.insert("end", "Welcome to Agent Reach Daily\n", ("h2",))
            t.insert("end", "No news has been collected on this computer yet. Agent Reach Daily fetches public news "
                            "feeds, then a local AI model (Ollama) on this PC groups and summarizes them into a daily "
                            "edition. Nothing is sent to a cloud AI service.\n\n", ("body",))
        t.insert("end", "Before the first refresh\n", ("why_label",))
        t.insert("end", "\n1. Python environment: ", ("body",))
        t.insert("end", "ready", ("ok",))
        t.insert("end", " (this window is running).\n2. Local model: ", ("body",))
        if self._prereq_text is None:
            self._start_prereq_check()
        t.insert("end", (self._prereq_text or "") + "\n", ("body",))
        t.insert("end", "3. Internet access for the news sources. Some sources (X, Reddit, TikTok) are often "
                        "blocked; the edition shows which sources were missing.\n\n", ("body",))
        btn = ttk.Button(t, text="Collect today's news now", style="Accent.TButton", command=self.refresh_now)
        t.window_create("end", window=btn)
        t.insert("end", "\n\nThe first edition is a baseline: stories are not labelled hot or rising until there is "
                        "an earlier edition to compare with. After that, the app refreshes every 24 hours while "
                        "your PC is on (see Help > How refreshing works). Prefer to look first? View > Demo "
                        "edition shows the layout with clearly marked sample content.\n", ("body", "muted"))

    def _render_edition(self, edition: DailyEdition) -> None:
        t = self.text
        stories = filter_stories(edition.stories, self.cat_var.get(), self.search_var.get())
        if edition.overview and not self.search_var.get().strip() and self.cat_var.get() in ("", "All"):
            t.insert("end", edition.overview + "\n", ("overview",))
        if not edition.stories:
            t.insert("end", "This edition has no stories.\n", ("body",))
        elif not stories:
            t.insert("end", "No stories match the current category and search filters. ", ("body",))
            t.insert("end", "Clear filters", self._link_tag("action:clear"))
            t.insert("end", "\n")
        for s in stories:
            self._render_story(s)

    def _link_tag(self, target: str) -> tuple[str, str]:
        name = f"link{len(self._links)}"
        self._links[name] = target
        self.text.tag_bind(name, "<Button-1>", lambda e, n=name: self._click(n))
        return ("link", name)

    def _click(self, name: str) -> None:
        target = self._links.get(name, "")
        if target == "action:clear":
            self._clear_filters()
            return
        url = safe_url(target)
        if url:
            webbrowser.open(url)

    def _render_story(self, s: Story) -> None:
        t = self.text
        t.insert("end", "\n", ("sep",))
        t.insert("end", f"{s.rank}  ", ("rank",))
        t.insert("end", s.headline + "\n", ("headline",))
        self._insert_chip(s.category.value)
        for label in s.labels:
            self._insert_chip(label)
        platforms = ", ".join(sorted({e.source_name for e in s.evidence}))
        t.insert("end", f"  {s.raw_item_count} signal{'s' if s.raw_item_count != 1 else ''} from {platforms}\n", ("meta",))
        t.insert("end", " ".join(s.sentences) + "\n", ("body",))
        if s.why_it_matters:
            t.insert("end", "Why it matters: ", ("body", "why_label"))
            t.insert("end", s.why_it_matters + "\n", ("body",))
        t.insert("end", "Sources\n", ("src_head",))
        for ev in s.evidence:
            t.insert("end", f"• {ev.source_name}: ", ("evidence",))
            if ev.url:
                t.insert("end", ev.title, ("evidence",) + self._link_tag(ev.url))
            else:
                t.insert("end", ev.title, ("evidence",))
            extra = []
            if ev.publisher:
                extra.append(ev.publisher)
            if ev.published_at_utc:
                extra.append("published " + format_central(ev.published_at_utc))
            else:
                extra.append("publication time not stated")
            t.insert("end", f"  ({'; '.join(extra)})\n", ("evidence", "muted"))
            if ev.excerpt:
                t.insert("end", ev.excerpt + "\n", ("excerpt",))

    # ------------------------------------------------------------ actions
    def _launch_check(self) -> None:
        try:
            if self.ctrl.maybe_auto_refresh():
                self.refresh_view(force=True)
        except Exception:  # noqa: BLE001
            log.exception("launch check failed")

    def refresh_now(self) -> None:
        snap = self.snap or self.ctrl.snapshot()
        if snap.activity.running:
            messagebox.showinfo(APP_NAME, "A refresh is already running.", parent=self.root)
            return
        allow = False
        st = snap.state
        if st.last_attempt_outcome == "failed" and "Ollama" in (st.last_attempt_message or "") and snap.prefs.require_llm:
            allow = messagebox.askyesno(
                APP_NAME, "The last refresh could not use the local model (Ollama).\n\nYes: try again, and if "
                          "Ollama is still unavailable build an edition WITHOUT AI summaries (lead sentences "
                          "from the sources).\nNo: try again with the local model only.", parent=self.root)
        if self.ctrl.start_refresh(manual=True, allow_extractive=allow):
            self.refresh_view(force=True)

    def cancel_refresh(self) -> None:
        if not messagebox.askyesno(APP_NAME, "Stop the running refresh? The current edition stays as it is.",
                                   parent=self.root):
            return
        self.ctrl.cancel_refresh()
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
            messagebox.showerror(APP_NAME, f"Demo edition unavailable: {exc}", parent=self.root)
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
        Path(target).write_text(render_edition_html(edition), encoding="utf-8")
        if messagebox.askyesno(APP_NAME, f"Saved {target}\n\nOpen it in your browser?", parent=self.root):
            webbrowser.open(Path(target).as_uri())

    def show_sources(self) -> None:
        snap = self.snap or self.ctrl.snapshot()
        edition = snap.shown
        win = tk.Toplevel(self.root)
        win.title("Source health")
        win.geometry("820x380")
        win.transient(self.root)
        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)
        if edition is None:
            ttk.Label(frm, text="No edition yet: source health appears after the first refresh.").pack(anchor="w")
            return
        cov = edition.coverage
        ttk.Label(frm, text=f"Edition {edition.edition_date.isoformat()}: {cov.sources_ok} of {cov.sources_attempted} "
                            f"sources responded. Coverage balanced: {'yes' if cov.balanced else 'no'}.",
                  font=self.f_bold).pack(anchor="w", pady=(0, 6))
        tree = ttk.Treeview(frm, columns=("status", "items", "ms", "notes"), show="tree headings", height=12)
        tree.heading("#0", text="Source")
        tree.heading("status", text="Status")
        tree.heading("items", text="Items")
        tree.heading("ms", text="Time (ms)")
        tree.heading("notes", text="Notes")
        tree.column("#0", width=150)
        tree.column("status", width=80)
        tree.column("items", width=60, anchor="e")
        tree.column("ms", width=80, anchor="e")
        tree.column("notes", width=420)
        for h in edition.source_health:
            tree.insert("", "end", text=h.name, values=(h.status, h.item_count, h.latency_ms, h.error or ""))
        tree.pack(fill="both", expand=True)
        ttk.Label(frm, text="Blocked or failed sources are skipped; the edition is built from the rest. Publisher "
                            "hosts are a rough diversity indicator, not proof of independent reporting.",
                  style="Muted.TLabel", wraplength=780).pack(anchor="w", pady=(6, 0))

    def show_help(self) -> None:
        messagebox.showinfo(APP_NAME, (
            "How refreshing works\n\n"
            "- A new edition is collected 24 hours after the start of the last successful refresh (or daily at a "
            "fixed Central time, if chosen in Settings). Refresh now collects one immediately.\n"
            "- The optional scheduled task checks every hour and at logon. It only runs while you are logged on. "
            "A PC that is off or asleep cannot collect news; the refresh happens at the next chance.\n"
            "- Ollama must be running. The app tries to start the installed Ollama app if it is not.\n"
            "- If a refresh fails or finds too little news, the previous edition is kept and the app retries "
            "later (30 minutes, then longer).\n"
            "- Editions are dated by the Central-time day the refresh started and kept for 30 days by default."),
            parent=self.root)

    def _start_prereq_check(self) -> None:
        prefs = (self.snap.prefs if self.snap else DailyPrefs())

        def work() -> None:
            from agent_reach.daily.prereqs import check_ollama

            status = check_ollama(prefs.ollama_host, [prefs.ollama_model, prefs.embed_model])
            prefix = "ready - " if status.ready else "NOT ready - "
            self._prereq_q.put(prefix + status.describe())

        self._prereq_text = "checking the local model (Ollama)..."
        threading.Thread(target=work, name="prereq-check", daemon=True).start()
        self.root.after(300, self._poll_prereq_soon)

    def _drain_prereq(self) -> bool:
        got = False
        try:
            while True:
                self._prereq_text = self._prereq_q.get_nowait()
                got = True
        except queue.Empty:
            pass
        return got

    def _poll_prereq_soon(self, tries: int = 0) -> None:
        if self._drain_prereq():
            self.refresh_view(force=True)
            if self.snap is not None and self.snap.shown is not None:
                messagebox.showinfo(APP_NAME, f"Local model: {self._prereq_text}", parent=self.root)
        elif tries < 30:
            self.root.after(300, lambda: self._poll_prereq_soon(tries + 1))

    def open_settings(self) -> None:
        SettingsDialog(self, (self.snap or self.ctrl.snapshot()).prefs)

    @staticmethod
    def _open_path(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            webbrowser.open(path.as_uri())

    def _on_close(self) -> None:
        if self.snap and self.snap.activity.running:
            messagebox.showinfo(APP_NAME, "The refresh continues in the background. The new edition will be "
                                          "shown the next time you open Agent Reach Daily.", parent=self.root)
        self.root.destroy()


class SettingsDialog:
    def __init__(self, window: DailyWindow, prefs: DailyPrefs) -> None:
        self.window = window
        self.prefs = prefs
        self.top = top = tk.Toplevel(window.root)
        top.title("Settings")
        top.geometry("640x560")
        top.transient(window.root)
        top.grab_set()
        nb = ttk.Notebook(top)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        self._sources_tab(nb)
        self._model_tab(nb)
        self._schedule_tab(nb)
        self._storage_tab(nb)
        btns = ttk.Frame(top, padding=(10, 0, 10, 10))
        btns.pack(fill="x")
        ttk.Button(btns, text="Save", style="Accent.TButton", command=self.save).pack(side="right")
        ttk.Button(btns, text="Cancel", command=top.destroy).pack(side="right", padx=6)

    def _tab(self, nb: ttk.Notebook, title: str) -> ttk.Frame:
        frm = ttk.Frame(nb, padding=12)
        nb.add(frm, text=title)
        return frm

    def _sources_tab(self, nb) -> None:
        from agent_reach.ingestion import INGESTER_REGISTRY

        frm = self._tab(nb, "Sources")
        ttk.Label(frm, text="Sources to collect from (general news first; tech-only sources are capped in the "
                            "edition):", wraplength=580).pack(anchor="w", pady=(0, 6))
        self.source_vars: dict[str, tk.BooleanVar] = {}
        for name in INGESTER_REGISTRY:
            var = tk.BooleanVar(value=name in self.prefs.enabled_sources)
            self.source_vars[name] = var
            ttk.Checkbutton(frm, text=f"{SOURCE_NOTES.get(name, name)}  [{name}]", variable=var).pack(anchor="w")

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
                  wraplength=560, foreground=MUTED).grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 0))

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
                  wraplength=560, foreground=MUTED).grid(row=9, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self._task_bg(lambda: self._task_text())

    def _storage_tab(self, nb) -> None:
        frm = self._tab(nb, "Storage")
        self.retention_var = tk.StringVar(value=str(self.prefs.retention_days))
        self.max_var = tk.StringVar(value=str(self.prefs.max_stories))
        ttk.Label(frm, text="Keep editions for (days):").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Spinbox(frm, from_=1, to=3650, textvariable=self.retention_var, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(frm, text="Stories per edition:").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Spinbox(frm, from_=3, to=50, textvariable=self.max_var, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(frm, text=f"Data folder: {self.window.paths.root}", wraplength=560).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(12, 4))
        ttk.Button(frm, text="Open data folder",
                   command=lambda: DailyWindow._open_path(self.window.paths.root)).grid(row=3, column=0, sticky="w")
        ttk.Separator(frm).grid(row=4, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Button(frm, text="Delete all cached editions...", command=self._reset_cache).grid(row=5, column=0, sticky="w")
        ttk.Label(frm, text="The newest edition is never deleted by retention, even after failed refreshes.",
                  wraplength=560, foreground=MUTED).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))

    # ......................................................... task helpers
    def _task_bg(self, fn) -> None:
        def work():
            try:
                text = fn()
            except Exception as exc:  # noqa: BLE001
                text = f"Could not query Task Scheduler: {exc}"
            self.top.after(0, lambda: self.task_var.set(text) if self.top.winfo_exists() else None)

        threading.Thread(target=work, daemon=True).start()

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
            )
            prefs = DailyPrefs.model_validate(data)
        except (ValueError, TypeError) as exc:
            messagebox.showerror(APP_NAME, f"Please check the settings:\n\n{exc}", parent=self.top)
            return
        save_prefs(self.window.paths, prefs)
        self.top.destroy()
        self.window.refresh_view(force=True)


def run_gui(paths: DataPaths | None = None) -> int:
    from agent_reach.daily.logs import setup_logging

    paths = (paths or DataPaths.resolve()).ensure()
    setup_logging(paths, "gui")
    _enable_dpi_awareness()
    root = tk.Tk()
    try:
        DailyWindow(root, paths)
        root.mainloop()
    except Exception:  # noqa: BLE001
        log.exception("GUI crashed")
        try:
            messagebox.showerror(APP_NAME, f"Agent Reach Daily hit an error. Details are in\n{paths.logs_dir}")
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
