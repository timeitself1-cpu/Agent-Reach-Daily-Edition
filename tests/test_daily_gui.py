"""Daily app: real tkinter window smoke tests (skipped when no display is available)."""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")

from agent_reach.daily.app import AppController  # noqa: E402
from agent_reach.daily.store import EditionStore  # noqa: E402
from tests.daily_fakes import make_edition, make_story  # noqa: E402


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    r.withdraw()
    yield r
    r.destroy()


class NoSpawn:
    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)

        class C:
            def poll(self):
                return 0

        return C()


def _window(root, paths):
    from agent_reach.daily.gui import DailyWindow

    spawner = NoSpawn()
    w = DailyWindow(root, paths, controller=AppController(paths, spawner=spawner), auto_refresh=False)
    root.update()
    return w, spawner


def _text(w) -> str:
    return w.text.get("1.0", "end")


def test_first_run_window_and_demo(root, daily_paths):
    w, _ = _window(root, daily_paths)
    assert "Welcome to Agent Reach" in _text(w) and w.heading_var.get() == "Today's Reach"
    assert str(w.refresh_btn["state"]) != "disabled"
    w.show_demo()
    root.update()
    body = _text(w)
    assert w.heading_var.get() == "DEMO Edition" and "WHY IT MATTERS" in body
    assert "Norvale Ferry Strike Halts Service to Three Islands" in body
    assert w.banner_frame.winfo_children() and "NOT real news" in w.banner_frame.winfo_children()[0]["text"]
    w.show_latest()
    root.update()
    assert "Welcome to Agent Reach" in _text(w)


def test_edition_rendering_is_plain_text_with_safe_links(root, daily_paths):
    evil = make_story(headline="<b>Bold</b> & <script>x()</script> Headline")
    evil.evidence[0].url = "javascript:alert(1)"
    EditionStore(daily_paths).publish(make_edition([evil, make_story(headline="Second Story Today")]))
    w, _ = _window(root, daily_paths)
    body = _text(w)
    assert "1\t<b>Bold</b> & <script>x()</script> Headline" in body  # shown literally, never interpreted
    toggles = [n for n, t in w._links.items() if t.startswith("toggle:")]
    for name in toggles:  # sources are collapsed by default; links appear when expanded
        w._click(name)
        root.update()
    assert all(not t.startswith("javascript:") for t in w._links.values())
    assert any(t.startswith("https://wire-one.test/") for t in w._links.values())
    assert "publication time not stated" in _text(w) or "published " in _text(w)
    w.search_var.set("second story")
    root.update()
    assert "Second Story Today" in _text(w) and "Bold" not in _text(w)
    w._clear_filters()
    assert "Bold" in _text(w)


def test_refresh_button_starts_one_worker(root, daily_paths):
    w, spawner = _window(root, daily_paths)
    w.refresh_now()
    root.update()
    assert len(spawner.calls) == 1 and "--refresh-now" in spawner.calls[0]


def test_window_survives_small_sizes(root, daily_paths):
    EditionStore(daily_paths).publish(make_edition())
    w, _ = _window(root, daily_paths)
    root.deiconify()
    root.geometry("760x540")
    root.update()
    bar_right = w.search_entry.winfo_rootx() + w.search_entry.winfo_width()
    assert bar_right <= root.winfo_rootx() + root.winfo_width()  # controls are not pushed off-screen


def test_dark_mode_and_live_theme_switch(root, daily_paths):
    from agent_reach.daily.gui import PALETTES
    from agent_reach.daily.prefs import DailyPrefs, save_prefs

    save_prefs(daily_paths, DailyPrefs(appearance="dark"))
    EditionStore(daily_paths).publish(make_edition())
    w, _ = _window(root, daily_paths)
    assert w.mode == "dark" and w.text["background"] == PALETTES["dark"]["card"]
    assert w.text.tag_cget("chip:News", "foreground") == PALETTES["dark"]["categories"]["News"][1]
    assert w.sidebar["bg"] == PALETTES["dark"]["sidebar"]
    w.apply_theme("light")
    root.update()
    assert w.text["background"] == PALETTES["light"]["card"] and w.status_label["bg"] == PALETTES["light"]["sidebar"]


def test_details_show_publisher_feeds_and_settings_manage_them(root, daily_env):
    from agent_reach.daily.feeds import FeedSpec
    from agent_reach.daily.gui import DetailsWindow, SettingsDialog
    from agent_reach.daily.prefs import load_prefs
    from agent_reach.daily.refresh import refresh
    from tests.daily_fakes import OllamaUp

    refresh(daily_env.paths, trigger="manual", force=True, ollama_probe=lambda p: OllamaUp())
    w, _ = _window(root, daily_env.paths)
    details = DetailsWindow(w)
    root.update()
    trees = [c for c in _walk(root) if c.winfo_class() == "Treeview"]
    channel_tree = trees[0]
    rss = next(i for i in channel_tree.get_children() if channel_tree.item(i, "text") == "News feeds")
    children = [channel_tree.item(c, "text") for c in channel_tree.get_children(rss)]
    assert "Wire One - World" in children and "Tech Seven" in children and len(children) == 6
    assert channel_tree.item(rss, "values")[0] == "OK"
    publishers = [trees[1].item(i, "text") for i in trees[1].get_children()]
    assert "Wire One - World" in publishers and "Daily Two" in publishers
    del details

    dialog = SettingsDialog(w, load_prefs(daily_env.paths)[0])
    root.update()
    assert len(dialog.feed_tree.get_children()) == 6
    assert dialog.save_feed(None, FeedSpec(name="Local Paper", url="https://local.test/rss")) is None
    assert dialog.save_feed(None, FeedSpec(name="Dup", url="https://LOCAL.test/rss")) is not None
    dialog.feed_tree.selection_set("0")
    dialog._toggle_feeds()
    dialog.appearance_var.set("dark")
    dialog.save()
    root.update()
    prefs, _ = load_prefs(daily_env.paths)
    assert [f.name for f in prefs.feeds][-1] == "Local Paper" and not prefs.feeds[0].enabled
    assert prefs.appearance == "dark" and w.mode == "dark"


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def test_window_shows_evidence_strength_and_changes(root, daily_env):
    from agent_reach.daily.refresh import refresh
    from tests.daily_fakes import OllamaUp

    refresh(daily_env.paths, trigger="manual", force=True, ollama_probe=lambda p: OllamaUp())
    w, _ = _window(root, daily_env.paths)
    body = _text(w)
    assert "Strong evidence" in body or "Moderate evidence" in body
    assert "What changed" not in body and "WHAT CHANGED" not in body
    daily_env.net.down.add("sports")
    refresh(daily_env.paths, trigger="manual", force=True, ollama_probe=lambda p: OllamaUp())
    w.refresh_view(force=True)
    root.update()
    assert "What changed" not in _text(w) and "No longer listed" not in _text(w)  # kept out of the reading view
    from agent_reach.daily.gui import DetailsWindow

    DetailsWindow(w)
    root.update()
    texts = [c.get("1.0", "end") for c in _walk(root) if c.winfo_class() == "Text" and c is not w.text]
    changes = next(t for t in texts if "No longer listed" in t)
    assert "Riverton Hawks Win Championship Final in Overtime" in changes


def test_sidebar_sections_top_stories_and_categories(root, daily_env):
    from agent_reach.daily.gui import TOP
    from agent_reach.daily.refresh import refresh
    from tests.daily_fakes import OllamaUp

    refresh(daily_env.paths, trigger="manual", force=True, ollama_probe=lambda p: OllamaUp())
    w, _ = _window(root, daily_env.paths)
    keys = [k for k, _, _ in w.sections(w.snap.shown)]
    assert keys[0] == TOP and {"News", "Tech", "Science & AI", "Sports"} <= set(keys)
    assert _text(w).startswith("Top Stories\n")
    w.show_section("Tech")
    root.update()
    body = _text(w)
    assert body.startswith("Tech\n") and "Nimbus Phone 5 Adds Satellite Messaging" in body
    assert "Ferry" not in body  # a category view lists only that category
    w.search_var.set("satellite")
    root.update()
    assert _text(w).startswith("Search\n") and "Nimbus Phone 5" in _text(w)
    w._clear_filters()
    root.update()
    assert _text(w).startswith("Top Stories\n")


def test_clean_toolbar_menu_search_hint_and_reading_column(root, daily_paths):
    EditionStore(daily_paths).publish(make_edition())
    w, _ = _window(root, daily_paths)
    assert not root.cget("menu")  # no classic menu bar: the "..." menu holds the commands
    labels = [w.menu.entrycget(i, "label") for i in range(w.menu.index("end") + 1) if w.menu.type(i) == "command"]
    assert {"Settings...", "Export as web page...", "Demo edition (not real news)", "Quit"} <= set(labels)
    assert w.search_hint.winfo_manager() == "place"  # 'Search' placeholder in the empty box
    w.search_var.set("ferry")
    root.update()
    assert w.search_hint.winfo_manager() == "" and w.search_var.get() == "ferry"  # never written into the box
    w._clear_filters()
    root.deiconify()
    root.geometry("1500x800")
    root.update()
    assert int(str(w.text.cget("padx"))) > w.px(36)  # wide window: the text column stays readable and centred


def test_headline_opens_the_main_article_and_j_k_move_between_stories(root, daily_paths, monkeypatch):
    from agent_reach.daily import gui as G
    from agent_reach.daily.edition import EvidenceLink, primary_url

    first = make_story(headline="Story With A Redirect First")
    first.evidence.insert(0, EvidenceLink(item_id=9, source="google_news", source_name="Google News",
                                          title="Redirect", url="https://news.google.com/rss/articles/abc"))
    stories = [first] + [make_story(headline=f"Another Story Number {i}") for i in range(2, 9)]
    EditionStore(daily_paths).publish(make_edition(stories))
    assert primary_url(first).startswith("https://wire-one.test/")  # the publisher article, not the redirect
    opened = []
    monkeypatch.setattr(G.webbrowser, "open", lambda url, new=0: opened.append(url))
    w, _ = _window(root, daily_paths)
    name = next(n for n, t in w._links.items() if t == primary_url(first))
    w._click(name)
    assert opened == [primary_url(first)]
    root.deiconify()
    root.geometry("900x500")
    root.update()
    w.text.yview_moveto(0)
    root.update()
    w.jump_story(1)
    root.update()
    second = int(w.text.index("story2").split(".")[0])
    assert int(w.text.index("@0,0").split(".")[0]) == second
    w.jump_story(-1)
    root.update()
    assert int(w.text.index("@0,0").split(".")[0]) == int(w.text.index("story1").split(".")[0])


def test_feed_doctor_banner_and_turn_off_failing_feeds(root, daily_paths):
    from datetime import datetime, timedelta, timezone

    from agent_reach.daily.feedhealth import FeedHealthLog, FeedRecord, _path
    from agent_reach.daily.fsutil import atomic_write_json
    from agent_reach.daily.gui import SettingsDialog
    from agent_reach.daily.prefs import load_prefs

    prefs, _ = load_prefs(daily_paths)
    url = prefs.feeds[0].url
    since = datetime.now(timezone.utc) - timedelta(days=5)
    log = FeedHealthLog(feeds={url: FeedRecord(name=prefs.feeds[0].name, url=url, source="news_rss",
                                               failures_in_row=6, failing_since_utc=since, last_error="HTTP 404")})
    atomic_write_json(_path(daily_paths), log.model_dump(mode="json"))
    EditionStore(daily_paths).publish(make_edition())
    w, _ = _window(root, daily_paths)
    texts = [c["text"] for c in w.banner_frame.winfo_children()]
    assert any("not worked for 3 days or more" in t and prefs.feeds[0].name in t for t in texts)
    dialog = SettingsDialog(w, prefs)
    root.update()
    assert "Failing since" in dialog.feed_tree.item("0", "values")[3]
    dialog.turn_off_failing()
    assert not dialog.feeds[0].enabled and dialog.feeds[1].enabled
