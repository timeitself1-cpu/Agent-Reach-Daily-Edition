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
    assert "01\t<b>Bold</b> & <script>x()</script> Headline" in body  # shown literally, never interpreted
    assert all(not t.startswith("javascript:") for t in w._links.values())
    assert any(t.startswith("https://wire-one.test/") for t in w._links.values())
    toggle = next(n for n, t in w._links.items() if t.startswith("toggle:"))
    w._click(toggle)
    root.update()
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
