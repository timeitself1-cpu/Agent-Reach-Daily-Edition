"""Daily app: edition schema, balanced selection, publication gate, atomic store and HTML export."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agent_reach.daily import edition as E
from agent_reach.daily import fsutil
from agent_reach.daily.prefs import DailyPrefs
from agent_reach.daily.render_html import render_edition_html
from agent_reach.daily.store import EditionStore
from agent_reach.models import MacroCluster
from tests.daily_fakes import make_edition, make_story

UTC = timezone.utc
NOW = datetime(2026, 10, 1, 12, 5, tzinfo=UTC)


# ------------------------------------------------------------------ schema
def test_edition_round_trips_with_schema_version():
    ed = make_edition()
    data = json.loads(ed.model_dump_json())
    assert data["edition_schema"] == "agent_reach.daily_edition" and data["edition_schema_version"] == 1
    assert E.DailyEdition.model_validate(data) == ed
    data["edition_schema_version"] = 99
    with pytest.raises(ValidationError):
        E.DailyEdition.model_validate(data)


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("run_id"),
    lambda d: d.update(edition_date="2026-09-30"),  # must equal the Central date of the refresh start
    lambda d: d.update(generation_started_utc="2026-10-01T12:05:00"),  # naive
    lambda d: d.update(generation_completed_utc="2026-10-01T11:00:00Z"),  # before start
    lambda d: d["accounting"].update(balanced=False),
    lambda d: d["stories"][0].update(rank=5),  # ranks must be 1..n
    lambda d: d["stories"][0].update(evidence=[]),
])
def test_invalid_editions_are_rejected(mutate):
    data = json.loads(make_edition().model_dump_json())
    mutate(data)
    with pytest.raises(ValidationError):
        E.DailyEdition.model_validate(data)


def test_labels_only_with_comparable_history():
    def cl(**kw):
        base = dict(cluster_id="c", headline="H", category="News", relevance_score=5, summary="S. T.",
                    velocity_score=50.0, raw_item_count=2)
        return MacroCluster(**{**base, **kw})

    assert E.story_labels(cl(momentum="BASELINE", velocity_basis="cold_start")) == []
    assert E.story_labels(cl(momentum="RISING", velocity_basis="historical")) == ["Rising"]
    assert E.story_labels(cl(momentum="STEADY", velocity_basis="historical")) == ["Continuing"]
    assert E.story_labels(cl(momentum="NEW", velocity_basis="historical")) == ["New"]
    # uncertain momentum: no card label (rc10; said once in the edition notes instead)
    assert E.story_labels(cl(momentum="RISING", velocity_basis="historical", momentum_uncertain=True)) == []


def test_meta_sentences_are_not_story_text():
    assert E.body_sentences("Signals were observed on Reddit and X.") == []
    assert E.body_sentences("A quake struck. ArXiv is carrying 1 related signal about X.") == ["A quake struck."]


# ------------------------------------------------------------------ selection
def test_stale_stories_are_left_out_but_undated_ones_are_kept():
    fresh = make_story(headline="Fresh Ferry Strike News", hours_ago=3, now=NOW)
    stale = make_story(headline="Old Mayor Resigns After Audit", hours_ago=24 * 6, now=NOW)
    undated = make_story(headline="Lantern Film Trend", hours_ago=None, now=NOW, category="Entertainment")
    sel = E.select_stories([stale, fresh, undated], DailyPrefs(max_story_age_hours=48), now=NOW)
    assert [s.headline for s in sel.stories] == ["Fresh Ferry Strike News", "Lantern Film Trend"]
    assert sel.dropped_stale == 1


def test_repeats_of_the_same_story_are_left_out():
    a = make_story(headline="Corvid Labs Releases Open Model Corvid-3", category="Science & AI", now=NOW)
    same_entity = make_story(headline="Developers Benchmark the New Release", category="Science & AI",
                             entity_id=a.entity_id, now=NOW)
    same_url = make_story(headline="Totally Different Words Here", url=a.evidence[0].url, now=NOW)
    similar = make_story(headline="Corvid Labs Open Model Corvid-3 Released", category="Science & AI", now=NOW)
    other = make_story(headline="Port Calder Earthquake Damages Roads", now=NOW)
    sel = E.select_stories([a, same_entity, same_url, similar, other], DailyPrefs(), now=NOW)
    assert [s.headline for s in sel.stories] == [a.headline, other.headline]
    assert sel.dropped_duplicate == 3


def test_weak_single_trend_signals_are_left_out():
    weak = make_story(headline="Someone Trending", platforms=["x_trends24"], items=1, relevance=5, now=NOW)
    strong_trend = make_story(headline="Huge Trending Event", platforms=["x_trends24"], items=1, relevance=8, now=NOW)
    article = make_story(headline="Single Article Story", platforms=["news_rss"], items=1, relevance=5, now=NOW)
    sel = E.select_stories([weak, strong_trend, article], DailyPrefs(), now=NOW)
    assert [s.headline for s in sel.stories] == ["Huge Trending Event", "Single Article Story"]
    assert sel.dropped_weak == 1


def test_sections_keep_top_n_per_category_and_a_balanced_top_stories():
    prefs = DailyPrefs(max_stories=3, max_per_category=2, max_tech_only_share=0.34)
    tech = [make_story(headline=h, category="Tech", tech_only=True, relevance=9, now=NOW, platforms=["hackernews"])
            for h in ("Frostline Fridges Bricked by Update", "Halden Hospitals Hit by Ransomware",
                      "Rust Compiler Ships Faster Builds", "Quantum Chip Benchmark Published")]
    news = [make_story(headline=h, category="News", relevance=r, now=NOW)
            for h, r in (("Port Calder Earthquake Damages Roads", 9), ("Lumen Summit Agrees Methane Pledge", 8),
                         ("Norvale Ferry Strike Halts Service", 7), ("Oakdene Council Delays Budget Vote", 5))]
    sel = E.select_stories(tech + news, prefs, now=NOW)
    heads = [s.headline for s in sel.stories]
    assert [s.headline for s in sel.stories if s.category.value == "Tech"] == [s.headline for s in tech[:3]]
    assert [s.headline for s in sel.stories if s.category.value == "News"] == [s.headline for s in news[:3]]
    assert sel.held_back == 2  # the 4th of each category is beyond the section size
    assert heads == [h for h in [s.headline for s in tech + news] if h in heads]  # pipeline order kept
    top = [s.headline for s in sel.top]
    assert len(top) == 3 and sum(s.tech_only for s in sel.top) == 1  # int(3 * 0.34): tech stays a minority
    assert top == ["Frostline Fridges Bricked by Update", "Port Calder Earthquake Damages Roads",
                   "Lumen Summit Agrees Methane Pledge"]


def test_top_stories_fill_from_the_next_best_when_caps_leave_gaps():
    prefs = DailyPrefs(max_stories=4, max_per_category=1)
    news = [make_story(headline=h, category="News", relevance=7, now=NOW)
            for h in ("Port Calder Earthquake Damages Roads", "Lumen Summit Agrees Methane Pledge",
                      "Norvale Ferry Strike Halts Service")]
    sel = E.select_stories(news, prefs, now=NOW)
    assert len(sel.top) == 3 and sel.filled_from_held_back == 2  # only one category: no artificial gap


def test_edition_sections_and_top_stories_helpers():
    stories = [make_story(headline="Tech One Item", category="Tech", now=NOW),
               make_story(headline="News One Item", category="News", now=NOW),
               make_story(headline="Sports One Item", category="Sports", now=NOW)]
    ed = make_edition(stories)
    assert [s.headline for s in E.top_stories(ed)] == ["Tech One Item", "News One Item", "Sports One Item"]
    assert [c for c, _ in E.category_sections(ed)] == ["News", "Tech", "Sports"]  # reading order, empty ones skipped
    ed.top_ranks = [2]
    assert [s.headline for s in E.top_stories(ed)] == ["News One Item"]
    data = json.loads(ed.model_dump_json())
    data["top_ranks"] = [9]
    with pytest.raises(ValidationError):
        E.DailyEdition.model_validate(data)


def test_publication_gate_refuses_weak_editions():
    prefs = DailyPrefs(min_useful_stories=3, min_ok_sources=2)
    ed = make_edition()
    ed.coverage.sources_ok = 2
    assert E.evaluate_publication(ed, prefs).publishable
    two = make_edition([make_story(1, now=NOW), make_story(2, headline="Second Story Here", now=NOW)])
    two.coverage.sources_ok = 3
    decision = E.evaluate_publication(two, prefs)
    assert not decision.publishable and "Only 2 useful" in decision.reasons[0]
    ed.coverage.sources_ok = 1
    assert not E.evaluate_publication(ed, prefs).publishable
    ed.coverage.sources_ok = 2
    ed.model.summaries = "extractive"
    assert not E.evaluate_publication(ed, prefs).publishable
    assert E.evaluate_publication(ed, prefs, allow_extractive=True).publishable


@pytest.mark.parametrize("url,ok", [
    ("https://example.com/a?b=1", True), ("http://example.com", True), ("javascript:alert(1)", False),
    ("data:text/html,<script>", False), ("file:///C:/Windows", False), ("//example.com/x", False),
    ("https://", False), (None, False), ("vbscript:msgbox", False),
])
def test_only_absolute_http_links_are_allowed(url, ok):
    assert (E.safe_url(url) is not None) == ok


# ------------------------------------------------------------------ store
def test_publish_writes_dated_file_and_checksummed_pointer(daily_paths):
    store = EditionStore(daily_paths)
    final = store.publish(make_edition())
    path = daily_paths.editions_dir / "2026-10-01.json"
    pointer = json.loads(daily_paths.latest_pointer.read_text())
    assert pointer["edition_date"] == "2026-10-01" and pointer["revision"] == 1
    assert pointer["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    res = store.load_latest()
    assert res.pointer_ok and res.edition == final


def test_same_day_refresh_becomes_a_revision(daily_paths):
    store = EditionStore(daily_paths)
    store.publish(make_edition(run_id="first"))
    second = store.publish(make_edition(run_id="second", started=NOW + timedelta(hours=3)))
    assert second.revision == 2
    assert [r.run_id for r in second.previous_revisions] == ["first"]
    third = store.publish(make_edition(run_id="third", started=NOW + timedelta(hours=4)))
    assert third.revision == 3 and [r.revision for r in third.previous_revisions] == [1, 2]
    assert store.list_dates() == [date(2026, 10, 1)]


def test_demo_editions_never_enter_the_cache(daily_paths):
    with pytest.raises(ValueError):
        EditionStore(daily_paths).publish(make_edition(demo=True))


def test_corrupt_latest_falls_back_to_the_previous_good_edition(daily_paths):
    store = EditionStore(daily_paths)
    store.publish(make_edition(run_id="yesterday", started=NOW - timedelta(days=1)))
    store.publish(make_edition(run_id="today"))
    (daily_paths.editions_dir / "2026-10-01.json").write_text('{"truncated": ', encoding="utf-8")
    res = store.load_latest()
    assert res.edition.run_id == "yesterday" and not res.pointer_ok
    assert res.corrupt and "2026-10-01.json" in res.corrupt[0]
    actions = store.repair()
    assert any("quarantined 2026-10-01.json" in a for a in actions)
    assert any("pointer repaired" in a for a in actions)
    assert list(daily_paths.quarantine_dir.glob("2026-10-01.json.*.corrupt"))
    res = store.load_latest()
    assert res.pointer_ok and res.edition.run_id == "yesterday" and not res.corrupt


def test_crash_between_file_and_pointer_is_detected_and_repaired(daily_paths):
    store = EditionStore(daily_paths)
    store.publish(make_edition(run_id="old"))
    newer = make_edition(run_id="newer", started=NOW + timedelta(days=1))
    fsutil.atomic_write_text(store.edition_path(newer.edition_date), newer.model_dump_json(indent=2))  # no pointer
    res = store.load_latest()
    assert res.edition.run_id == "newer" and not res.pointer_ok
    store.repair()
    assert store.load_latest().pointer_ok


def test_file_name_must_match_edition_date(daily_paths):
    store = EditionStore(daily_paths)
    ed = make_edition()
    fsutil.atomic_write_text(daily_paths.editions_dir / "2026-09-01.json", ed.model_dump_json())
    edition, problem = store.load_date(date(2026, 9, 1))
    assert edition is None and "does not match" in problem


def test_interrupted_write_keeps_the_old_file_and_no_temp_files(daily_paths, monkeypatch):
    store = EditionStore(daily_paths)
    store.publish(make_edition(run_id="good"))
    before = (daily_paths.editions_dir / "2026-10-01.json").read_bytes()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(fsutil.os, "replace", boom)
    with pytest.raises(OSError):
        store.publish(make_edition(run_id="never"))
    monkeypatch.undo()
    assert (daily_paths.editions_dir / "2026-10-01.json").read_bytes() == before
    assert not list(daily_paths.editions_dir.glob(".*.tmp"))
    assert store.load_latest().edition.run_id == "good"


def test_progress_file_is_deleted_even_while_the_window_reads_it(daily_paths, monkeypatch):
    """October 7, PC: Windows refused to delete progress.json while the window read it, so the file outlived
    its refresh. The delete is retried; a file that stays locked is given up on without an error."""
    from datetime import datetime, timezone
    from pathlib import Path

    from agent_reach.daily.refresh import ProgressWriter

    writer = ProgressWriter(daily_paths, "manual", datetime(2026, 10, 7, tzinfo=timezone.utc))
    writer("start", "Starting refresh")
    real_unlink, refusals = Path.unlink, [3]

    def busy_unlink(self, *a, **k):
        if self.name == "progress.json" and refusals[0] > 0:
            refusals[0] -= 1
            raise PermissionError(32, "The process cannot access the file because it is being used")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(fsutil.Path, "unlink", busy_unlink)
    writer.clear()
    assert refusals == [0] and not daily_paths.progress_file.exists()
    writer("start", "Starting refresh")
    refusals[0] = 10**6
    assert not fsutil.unlink_with_retry(daily_paths.progress_file, attempts=3, delay_s=0)
    assert daily_paths.progress_file.exists()
    refusals[0] = 0
    assert fsutil.unlink_with_retry(daily_paths.progress_file) and fsutil.unlink_with_retry(daily_paths.progress_file)


def test_stale_temp_files_are_cleaned(daily_paths):
    tmp = daily_paths.editions_dir / ".2026-10-01.json.abc.tmp"
    tmp.write_text("partial")
    old = tmp.stat().st_mtime - 7200
    os.utime(tmp, (old, old))
    EditionStore(daily_paths).repair()
    assert not tmp.exists()


def test_retention_keeps_the_newest_edition_even_when_old(daily_paths):
    store = EditionStore(daily_paths)
    for days in (60, 45, 40):
        store.publish(make_edition(run_id=f"d{days}", started=NOW - timedelta(days=days)))
    removed = store.purge(30, date(2026, 10, 1))
    assert len(removed) == 2
    assert store.load_latest().edition.run_id == "d40"  # failed refreshes never cost the last edition
    store.publish(make_edition(run_id="today"))
    assert store.purge(30, date(2026, 10, 1)) == [(NOW - timedelta(days=40)).date()]


def test_reset_deletes_editions_only(daily_paths):
    store = EditionStore(daily_paths)
    store.publish(make_edition())
    daily_paths.settings.write_text("{}")
    assert store.reset() == 1
    assert store.load_latest().edition is None and daily_paths.settings.exists()


# ------------------------------------------------------------------ HTML export
EVIL = '<script>alert("x")</script><img src=x onerror=alert(1)> & "quotes"'


def test_html_escapes_every_untrusted_field_and_blocks_unsafe_links():
    s = make_story(headline="Headline " + EVIL, why="Why " + EVIL, sentences=["Summary " + EVIL])
    s.evidence[0].title = "Title " + EVIL
    s.evidence[0].publisher = "Pub " + EVIL
    s.evidence[0].excerpt = "Excerpt " + EVIL
    s.evidence[0].url = "javascript:alert(document.cookie)"
    ed = make_edition([s, make_story(headline="Safe Link Story")])
    ed.source_health[0].error = "error " + EVIL
    ed.coverage.warnings = ["warn " + EVIL]
    page = render_edition_html(ed)
    assert "<script" not in page.lower() and "onerror=alert" not in page.replace("onerror=alert(1)&gt;", "")
    assert "<img" not in page and "javascript:" not in page
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in page
    assert '<a href="https://wire-one.test/safe-link-story" rel="noopener noreferrer nofollow"' in page
    assert re.search(r"Content-Security-Policy.*default-src 'none'", page)


def test_html_is_self_contained_and_dated():
    page = render_edition_html(make_edition())
    assert "<link" not in page and " src=" not in page and "@import" not in page  # no remote CSS/JS/images
    assert "Trending news for October 1, 2026" in page
    assert "Updated October 1, 2026 at 7:20 AM CDT" in page
    assert "Wire One" in page and "published October 1, 2026 at 4:05 AM CDT" in page
    assert "DEMO" not in page


def test_html_marks_demo_and_unknown_publication_times():
    s = make_story(hours_ago=None)
    page = render_edition_html(make_edition([s, make_story(headline="Other One")], demo=True))
    assert "<title>DEMO - " in page and "These are not real news stories" in page
    assert "publication time not stated" in page
