"""Daily app: real tkinter window smoke tests (skipped when no display is available)."""

from __future__ import annotations

import time

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
        # once on Windows (October 7, PC) one of the window tests could not read tk.tcl, which every other test
        # and the launchers read fine: a file briefly held by another program. A second try settles that.
        if "couldn't read file" not in str(exc):
            pytest.skip(f"no display: {exc}")
        time.sleep(1.0)
        try:
            r = tk.Tk()
        except tk.TclError as exc2:
            pytest.skip(f"no display: {exc2}")
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
    name = next(n for n, t in w._links.items() if t.startswith("open:") and t.endswith(primary_url(first)))
    w._click(name)
    assert opened == [primary_url(first)] and first.story_id in w._read  # opening a story marks it read
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


def test_in_brief_follow_mute_read_state_and_story_menu(root, daily_paths, monkeypatch):
    from agent_reach.daily import gui as G
    from agent_reach.daily.prefs import load_prefs

    heads = ["Norvale Ferry Strike Halts Island Service", "Port Calder Earthquake Damages Roads",
             "Riverton Hawks Win Championship Final", "Lumen Summit Agrees Methane Pledge",
             "Corvid Labs Releases Open Model"]
    stories = [make_story(headline=h, sentences=[f"{h.split()[0]} lead sentence for the brief."]) for h in heads]
    stories[0].entities = ["Norvale", "Norvale Port Authority"]
    EditionStore(daily_paths).publish(make_edition(stories))
    monkeypatch.setattr(G.webbrowser, "open", lambda url, new=0: None)
    w, _ = _window(root, daily_paths)
    body = _text(w)
    assert "IN BRIEF" in body and "Norvale lead sentence for the brief." in body
    assert body.index("IN BRIEF") < body.index("1\tNorvale Ferry Strike")
    top_row = [c for c in w.section_box.winfo_children() if c.winfo_class() == "Frame"][0]
    assert [c.cget("text") for c in top_row.winfo_children() if c.winfo_class() == "Label"][-1] == "5"  # unread

    # right-click menu: follow a key name, then mute another story
    items = [label for label, _ in w.story_menu_items(stories[0])]
    assert "Open article" in items and "Mark as read" in items and "Follow \u201cNorvale\u201d" in items
    w.set_topic("Norvale", "follow", True)
    assert load_prefs(daily_paths)[0].follow_topics == ["Norvale"]
    keys = [k for k, _, _ in w.sections(w.snap.shown)]
    assert keys[:2] == ["top", "following"]
    assert "\u2605 NORVALE" in _text(w)
    w.set_topic("Riverton", "mute", True)
    assert "Riverton Hawks" not in _text(w) and "1 muted" in _text(w)

    # read state: dimmed headline, unread count drops, Mark all as read clears the badge
    w.mark_read([stories[1].story_id])
    ranges = w.text.tag_ranges("read")
    assert ranges and "Port Calder" in w.text.get(ranges[0], ranges[1])
    w.mark_all_read()
    top_row = [c for c in w.section_box.winfo_children() if c.winfo_class() == "Frame"][0]
    assert [c.cget("text") for c in top_row.winfo_children() if c.winfo_class() == "Label"][-1] == ""
    assert w.story_at("story2") is not None


def test_topics_tab_saves_follow_and_mute(root, daily_paths):
    from agent_reach.daily.gui import SettingsDialog
    from agent_reach.daily.prefs import load_prefs

    w, _ = _window(root, daily_paths)
    dialog = SettingsDialog(w, load_prefs(daily_paths)[0])
    root.update()
    dialog.follow_text.insert("1.0", "Packers\n  Jordan Love \n\npackers")
    dialog.mute_text.insert("1.0", "Crypto")
    dialog.save()
    prefs, _ = load_prefs(daily_paths)
    assert prefs.follow_topics == ["Packers", "Jordan Love"] and prefs.mute_topics == ["Crypto"]


def test_o_and_s_keys_act_on_the_current_story(root, daily_paths, monkeypatch):
    from agent_reach.daily import gui as G

    stories = [make_story(headline=f"Story Number {n} Happens Today", url=f"https://wire-one.test/{n}")
               for n in ("one", "two", "three")]
    EditionStore(daily_paths).publish(make_edition(stories))
    opened = []
    monkeypatch.setattr(G.webbrowser, "open", lambda url, new=0: opened.append(url))
    w, _ = _window(root, daily_paths)
    w.open_current()
    assert opened == ["https://wire-one.test/one"] and stories[0].story_id in w._read
    w.toggle_current_sources()
    assert stories[0].story_id in w._expanded and "Hide sources" in _text(w)


def test_listen_records_then_plays_the_podcast(root, daily_paths, monkeypatch):
    import wave

    from agent_reach.daily import podcast as P

    def engine(ssml, text, out, voice, rate):
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00\x00" * 800)

    monkeypatch.setattr(P, "default_synthesizer", lambda: engine)
    EditionStore(daily_paths).publish(make_edition())
    w, _ = _window(root, daily_paths)
    played = []
    monkeypatch.setattr(w, "play", lambda audio: played.append(audio))
    w.record_podcast(then_open=True)
    for _ in range(100):
        root.update()
        if played:
            break
        root.after(50)
    assert played and played[0].name.endswith(".wav") and not w._podcast_busy
    w.listen()  # it exists now: plays straight away, without recording again
    assert len(played) == 2
    from agent_reach.daily.gui import SettingsDialog
    from agent_reach.daily.prefs import load_prefs

    dialog = SettingsDialog(w, load_prefs(daily_paths)[0])
    root.update()
    dialog.podcast_auto_var.set(False)
    dialog.podcast_rate_var.set("-2")
    dialog.save()
    prefs, _ = load_prefs(daily_paths)
    assert prefs.podcast_auto is False and prefs.podcast_rate == -2 and prefs.podcast_voice == ""


def test_follow_and_mute_edge_cases_and_persistence(root, daily_paths, monkeypatch):
    from agent_reach.daily import gui as G
    from agent_reach.daily.gui import SettingsDialog
    from agent_reach.daily.prefs import load_prefs

    EditionStore(daily_paths).publish(make_edition([make_story(headline="Norvale Ferry Strike Halts Island Service"),
                                                    make_story(headline="Riverton Hawks Win Championship Final")]))
    w, _ = _window(root, daily_paths)
    w.set_topic("Norvale", "follow", True)
    w.set_topic("NORVALE", "follow", True)  # the same topic in other capitals replaces it
    w.set_topic("  ", "follow", True)  # blank: ignored
    w.set_topic("x" * 90, "mute", True)  # over-long: kept at 60 characters
    prefs, _ = load_prefs(daily_paths)
    assert prefs.follow_topics == ["NORVALE"] and prefs.mute_topics == ["x" * 60]
    assert "★ NORVALE" in _text(w)  # matching ignores capitals
    w.set_topic("NORVALE", "follow", False)
    w.set_topic("riverton hawks", "mute", True)
    assert "Riverton Hawks" not in _text(w) and "★" not in _text(w)
    dialog = SettingsDialog(w, load_prefs(daily_paths)[0])  # unmute in Settings > Topics
    root.update()
    assert dialog.mute_text.get("1.0", "end").splitlines()[1] == "riverton hawks"
    dialog.mute_text.delete("1.0", "end")
    dialog.save()
    root.update()
    assert "Riverton Hawks" in _text(w)
    assert load_prefs(daily_paths)[0].mute_topics == []  # saved: a restarted window reads the same file

    def read_only(*a, **k):
        raise PermissionError("[Errno 13] Permission denied: 'settings.json'")

    shown = []
    monkeypatch.setattr(G, "save_prefs", read_only)
    monkeypatch.setattr(G.messagebox, "showerror", lambda *a, **k: shown.append(a[1]))
    w.set_topic("Norvale", "follow", True)  # a read-only settings file: a message, never a crash
    assert shown and "Could not save your topics" in shown[0]


def test_cancel_returns_the_window_to_normal(root, daily_paths, monkeypatch):
    import time as _time

    from agent_reach.daily import gui as G

    w, _ = _window(root, daily_paths)
    monkeypatch.setattr(G.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(w.ctrl, "cancel_refresh", lambda: _time.sleep(0.3) or True)
    w.cancel_refresh()
    root.update()
    assert w._cancelling and w.refresh_btn.cget("text") == "Refreshing..."
    end = _time.monotonic() + 5
    while w._cancelling and _time.monotonic() < end:
        root.update()
        _time.sleep(0.05)
    assert not w._cancelling and w.refresh_btn.cget("text") == "Refresh"


def _wait_idle(root, dialog, limit=20.0):
    # A deadline, not a count of loop turns: the background publish took over 4 s on a busy CI runner (Oct 8).
    end = time.monotonic() + limit
    while time.monotonic() < end:
        root.update()
        if not dialog.busy:
            return
        time.sleep(0.02)


def test_website_publishing_dialog_and_story_correction(root, daily_paths, monkeypatch, tmp_path):
    from agent_reach.daily import gui as G, publish

    monkeypatch.delenv(publish.TOKEN_ENV, raising=False)
    monkeypatch.setattr(publish, "live_edition", lambda site_url=publish.SITE_URL, client=None: (None, None))
    stories = [make_story(headline="Norvale Ferry Strike Halts Island Service"),
               make_story(2, headline="Port Calder Earthquake Damages Roads")]
    EditionStore(daily_paths).publish(make_edition(stories))
    w, _ = _window(root, daily_paths)
    assert "Remove from the website..." not in [label for label, _ in w.story_menu_items(stories[0])]  # not set up
    d = G.PublishDialog(w)
    root.update()
    assert d.headline_var.get().startswith("Not set up") and str(d.publish_btn.cget("state")) == "disabled"
    d.auto_var.set(True)
    d._toggle_auto()
    assert publish.load_settings(daily_paths).enabled and "Save an access key" in d.message_var.get()
    monkeypatch.setattr(publish, "github_target", lambda paths, settings=None, client=None: publish.FolderTarget(tmp_path / "site"))
    d.key_var.set("github_pat_example")
    d.save_key()
    _wait_idle(root, d)
    assert d.key_var.get() == "" and "Connected" in d.message_var.get()
    d.publish_now()
    _wait_idle(root, d)
    assert d.headline_var.get() == "Published successfully", d.message_var.get()
    assert (tmp_path / "site/editions/index.json").exists()
    d.top.destroy()
    assert "Remove from the website..." in [label for label, _ in w.story_menu_items(stories[0])]
