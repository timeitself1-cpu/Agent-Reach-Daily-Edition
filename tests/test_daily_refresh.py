"""Daily app: the refresh worker end to end on deterministic fakes (real pipeline, no network, no Ollama).

Every test runs the REAL ingest -> clean -> enrich -> density clustering -> scoring -> edition ->
publication path against fake publisher feeds and a fake local model (tests/daily_fakes.py).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from agent_reach.daily import refresh as R
from agent_reach.daily.prefs import DailyPrefs, load_prefs, save_prefs
from agent_reach.daily.render_html import render_edition_html
from agent_reach.daily.state import load_state, save_state
from agent_reach.daily.store import EditionStore
from tests.daily_fakes import OllamaDown, OllamaUp


def _refresh(env, **kw):
    kw.setdefault("trigger", "manual")
    kw.setdefault("force", True)
    kw.setdefault("ollama_probe", lambda p: OllamaUp())
    return R.refresh(env.paths, **kw)


def test_successful_refresh_publishes_a_complete_grounded_edition(daily_env):
    out = _refresh(daily_env)
    assert out.code == R.EXIT_PUBLISHED, out.message
    ed = EditionStore(daily_env.paths).load_latest().edition
    assert ed is not None and ed == out.edition and not ed.demo
    heads = [s.headline for s in ed.stories]
    assert len(heads) >= 8
    assert {s.category.value for s in ed.stories} >= {"News", "Sports", "Entertainment", "Science & AI", "Tech"}
    assert "Mayor of Oakdene Resigns After Audit" not in heads  # a week-old story is not today's news
    assert any("left out because every source was published more than 48 hours" in n for n in ed.notes)
    assert all(s.labels == [] for s in ed.stories)  # first run = baseline: no trend labels
    why = {s.headline: s.why_it_matters for s in ed.stories}
    assert why["Norvale Harbor Ferry Strike Halts Island Service"].startswith("Island residents")
    assert why["Ransomware Attack Disrupts Halden Hospital Network"].startswith("Patients")
    for invented in ("Riverton Hawks Win Championship Final in Overtime",  # invented coach + $5 million
                     "Halcyon Studio Film Northern Lantern Tops Box Office",  # generic filler
                     "Astronomers Detect Water Vapour on Exoplanet Tessa-9b"):  # speculation
        assert why[invented] is None
    assert ed.model.summaries == "local_model" and ed.coverage.sources_ok == 3
    assert ed.accounting.balanced and ed.config_fingerprint


def test_time_semantics_are_kept_apart(daily_env):
    started = datetime.now(timezone.utc)
    out = _refresh(daily_env)
    ed = out.edition
    st, _ = load_state(daily_env.paths)
    assert st.last_attempt_outcome == "success" and st.consecutive_failures == 0
    assert st.last_attempt_started_utc == st.last_success_started_utc == ed.generation_started_utc
    assert st.last_success_utc == ed.generation_completed_utc >= ed.generation_started_utc >= started
    evidence = [e for s in ed.stories for e in s.evidence]
    assert all(e.retrieved_at_utc is not None for e in evidence)
    stated = [e for e in evidence if e.published_at_utc is not None]
    assert stated and all(e.published_at_utc < e.retrieved_at_utc for e in stated)
    lantern = next(e for e in evidence if e.title.startswith("Halcyon Studio drama Northern Lantern"))
    assert lantern.published_at_utc is None  # the feed gave no pubDate: never shown as newly published


def test_exported_html_of_a_real_edition(daily_env):
    ed = _refresh(daily_env).edition
    page = render_edition_html(ed)
    assert ed.stories[0].headline in page and "https://wire-one.test/" in page
    assert "<script" not in page.lower()


def test_not_due_exits_quickly_without_network_or_model(daily_env):
    assert _refresh(daily_env).code == R.EXIT_PUBLISHED
    daily_env.net.requests.clear()
    calls = dict(daily_env.model.calls)
    out = R.refresh(daily_env.paths, trigger="scheduled", force=False, ollama_probe=lambda p: OllamaUp())
    assert out.code == R.EXIT_NOT_DUE and "Next refresh is due" in out.message
    assert daily_env.net.requests == [] and daily_env.model.calls == calls


def test_ollama_unavailable_keeps_the_previous_edition_and_backs_off(daily_env):
    first = _refresh(daily_env).edition
    daily_env.net.requests.clear()
    out = _refresh(daily_env, ollama_probe=lambda p: OllamaDown())
    assert out.code == R.EXIT_PREREQ and "Ollama is not running" in out.message
    assert daily_env.net.requests == []  # nothing fetched without the model
    store = EditionStore(daily_env.paths)
    assert store.load_latest().edition == first
    st, _ = load_state(daily_env.paths)
    assert st.last_attempt_outcome == "failed" and st.consecutive_failures == 1
    assert st.last_success_run_id == first.run_id and st.next_retry_utc is not None
    diag = sorted(daily_env.paths.diagnostics_dir.glob("*-failed.json"))
    assert diag and json.loads(diag[-1].read_text())["ollama_error"]


def test_extractive_edition_only_when_explicitly_allowed(daily_env):
    out = _refresh(daily_env, ollama_probe=lambda p: OllamaDown(), allow_extractive=True)
    assert out.code == R.EXIT_PUBLISHED, out.message
    ed = out.edition
    assert ed.model.summaries == "extractive"
    assert any("extractive" in n for n in ed.notes)
    assert all(s.why_it_matters is None for s in ed.stories)
    assert daily_env.model.calls["chat"] == 0 and daily_env.model.calls["embed"] == 0


def test_one_source_failing_still_publishes_with_visible_coverage(daily_env):
    daily_env.net.down.update({"hn.algolia.com", "sports"})  # one whole source + one feed of another
    out = _refresh(daily_env)
    assert out.code == R.EXIT_PUBLISHED, out.message
    health = {h.source: h for h in out.edition.source_health}
    assert health["hackernews"].status == "failed"
    assert health["news_rss"].status == "partial" and "feeds failed" in health["news_rss"].error
    cov = out.edition.coverage
    assert cov.failed == ["Hacker News"] and "News feeds" in cov.partial
    assert any("Unavailable this run: Hacker News" in w for w in cov.warnings)
    assert "Sports" not in {s.category.value for s in out.edition.stories}


def test_internet_down_publishes_nothing_and_keeps_the_last_edition(daily_env):
    first = _refresh(daily_env).edition
    daily_env.net.offline = True
    out = _refresh(daily_env)
    assert out.code == R.EXIT_NO_UPDATE and "No news source responded" in out.message
    assert "previous edition is kept" in out.message
    assert EditionStore(daily_env.paths).load_latest().edition == first
    st, _ = load_state(daily_env.paths)
    assert st.last_attempt_outcome == "no_update" and st.last_success_run_id == first.run_id


def test_too_few_stories_is_refused(daily_env):
    prefs, _ = load_prefs(daily_env.paths)
    save_prefs(daily_env.paths, prefs.model_copy(update={"news_rss_feeds": ["Sports|https://feeds.test/sports.xml"],
                                                         "enabled_sources": ["news_rss", "google_news"]}))
    daily_env.net.down.add("news.google.com")
    out = _refresh(daily_env)
    assert out.code == R.EXIT_NO_UPDATE
    assert "useful stor" in out.message or "responded; at least" in out.message
    assert EditionStore(daily_env.paths).load_latest().edition is None


def test_model_failing_during_the_brief_pass_does_not_cost_the_edition(daily_env):
    daily_env.model.brief_raises = True
    out = _refresh(daily_env)
    assert out.code == R.EXIT_PUBLISHED
    assert all(s.why_it_matters is None for s in out.edition.stories)
    daily_env.model.brief_raises, daily_env.model.brief_garbage = False, True
    out = _refresh(daily_env)
    assert out.code == R.EXIT_PUBLISHED and out.edition.revision == 2


def test_failure_backoff_blocks_scheduled_retries_then_allows_one(daily_env):
    t0 = datetime.now(timezone.utc)
    _refresh(daily_env, ollama_probe=lambda p: OllamaDown(), now_fn=lambda: t0)
    out = R.refresh(daily_env.paths, trigger="scheduled", force=False, now_fn=lambda: t0 + timedelta(minutes=10),
                    ollama_probe=lambda p: OllamaUp())
    assert out.code == R.EXIT_BACKOFF and daily_env.net.requests == []
    out = R.refresh(daily_env.paths, trigger="scheduled", force=False, now_fn=lambda: t0 + timedelta(minutes=31),
                    ollama_probe=lambda p: OllamaUp())
    assert out.code == R.EXIT_PUBLISHED
    st, _ = load_state(daily_env.paths)
    assert st.consecutive_failures == 0 and st.last_attempt_trigger == "scheduled"


def test_crashed_attempt_is_recorded_as_interrupted(daily_env):
    st, _ = load_state(daily_env.paths)
    st.last_attempt_outcome, st.last_attempt_started_utc = "running", datetime.now(timezone.utc) - timedelta(hours=2)
    save_state(daily_env.paths, st)
    out = R.refresh(daily_env.paths, trigger="scheduled", force=False, ollama_probe=lambda p: OllamaDown())
    assert out.code == R.EXIT_PREREQ  # the dead attempt was recovered, then this attempt ran
    st, _ = load_state(daily_env.paths)
    assert st.consecutive_failures == 2  # interrupted + this failure
    assert not daily_env.paths.progress_file.exists() and not daily_env.paths.lock_info.exists()


def test_same_day_second_refresh_is_a_revision_and_reuses_history(daily_env):
    first = _refresh(daily_env).edition
    second = _refresh(daily_env).edition
    assert second.edition_date == first.edition_date and second.revision == 2
    assert second.previous_revisions[0].run_id == first.run_id
    assert EditionStore(daily_env.paths).list_dates() == [first.edition_date]


def test_status_payload_reports_without_network(daily_env):
    _refresh(daily_env)
    daily_env.net.requests.clear()
    payload = R.status_payload(daily_env.paths)
    assert payload["latest_edition"] and payload["due"] is False and payload["consecutive_failures"] == 0
    assert daily_env.net.requests == []


def test_prefs_changes_take_effect_on_the_next_refresh(daily_env):
    prefs, _ = load_prefs(daily_env.paths)
    save_prefs(daily_env.paths, prefs.model_copy(update={"max_stories": 3}))  # stories per section
    out = _refresh(daily_env)
    assert out.code == R.EXIT_PUBLISHED and len(out.edition.top_ranks) == 3
    from collections import Counter

    assert max(Counter(s.category.value for s in out.edition.stories).values()) == 3
    assert isinstance(load_prefs(daily_env.paths)[0], DailyPrefs)


def test_youtube_channel_videos_join_the_matching_story(daily_env):
    from agent_reach.daily.feeds import FeedSpec
    from agent_reach.ingestion.video import youtube_feed_url

    prefs, _ = load_prefs(daily_env.paths)
    channel = FeedSpec(name="Wire One", url=youtube_feed_url("UCwireonewireonewireone1"), category="News")
    save_prefs(daily_env.paths, prefs.model_copy(update={"feeds": [*prefs.feeds, channel],
                                                         "enabled_sources": [*prefs.enabled_sources, "youtube"]}))
    out = _refresh(daily_env)
    assert out.code == R.EXIT_PUBLISHED, out.message
    health = {h.source: h for h in out.edition.source_health}
    assert health["youtube"].status == "ok" and health["youtube"].feeds[0].collected == 1  # the old video is skipped
    ferry = next(s for s in out.edition.stories if "Ferry" in s.headline)
    video = next(e for e in ferry.evidence if e.source == "youtube")
    assert video.publisher == "Wire One" and video.source_name == "YouTube" and video.published_at_utc is not None
    assert "|" not in video.title and health["youtube"].used == 1
    # the channel belongs to a publisher already in the story: it is not counted as another independent report
    from agent_reach.daily.strength import origin

    assert origin(video.publisher, video.url) in {origin(e.publisher, e.url) for e in ferry.evidence
                                                  if e.source == "news_rss"}
    assert ferry.evidence_strength.duplicates_collapsed >= 1


def test_social_and_wikipedia_channels_join_stories_without_inflating_evidence(daily_env):
    prefs, _ = load_prefs(daily_env.paths)
    save_prefs(daily_env.paths, prefs.model_copy(update={
        "enabled_sources": [*prefs.enabled_sources, "mastodon", "bluesky", "wikipedia"]}))
    out = _refresh(daily_env)
    assert out.code == R.EXIT_PUBLISHED, out.message
    health = {h.source: h for h in out.edition.source_health}
    assert {"mastodon", "bluesky", "wikipedia"} <= set(health)
    assert all(health[k].status == "ok" for k in ("mastodon", "bluesky", "wikipedia"))
    assert out.edition.accounting.balanced
    ferry = next(s for s in out.edition.stories if "Ferry" in s.headline)
    assert "mastodon" in ferry.platforms  # the shared article joins its story...
    assert sum(e.url == "https://wire-one.test/norvale-ferry-strike" for e in ferry.evidence) == 1  # ...cited once
    strength = ferry.evidence_strength
    # a shared copy of Wire One's own article and a Bluesky topic add no independent report
    assert sorted(strength.publishers) == ["Daily Two", "Wire One"]


def test_refresh_records_feed_health_for_the_feed_doctor(daily_env):
    from agent_reach.daily.feedhealth import load_feed_health

    daily_env.net.down.add("arts")
    assert _refresh(daily_env).code == R.EXIT_PUBLISHED
    health = load_feed_health(daily_env.paths)
    arts = next(r for r in health.feeds.values() if r.name == "Arts Four")
    world = next(r for r in health.feeds.values() if r.name == "Wire One - World")
    assert arts.failures_in_row == 1 and arts.failing_since_utc is not None and "503" in arts.last_error
    assert world.failures_in_row == 0 and world.last_ok_utc is not None


def test_a_cache_repair_error_does_not_stop_the_refresh(daily_env, monkeypatch):
    """Windows can refuse to move a damaged file (a virus scanner holds it open): the refresh still runs."""
    def locked(self):
        raise PermissionError("[WinError 32] The process cannot access the file")

    monkeypatch.setattr(EditionStore, "repair", locked)
    out = _refresh(daily_env)
    assert out.code == R.EXIT_PUBLISHED, out.message
    assert load_state(daily_env.paths)[0].last_attempt_outcome == "success"


def test_settings_or_history_held_by_another_program_are_never_reset(daily_env, monkeypatch):
    """A virus scanner, OneDrive or a backup tool can hold settings.json for a moment. Earlier versions
    renamed it to .corrupt and ran on default settings (the reader's feeds and topics were lost)."""
    from agent_reach.daily import fsutil
    from agent_reach.daily.prefs import load_prefs as lp

    assert _refresh(daily_env).code == R.EXIT_PUBLISHED
    settings_before = daily_env.paths.settings.read_bytes()
    state_before = daily_env.paths.state_file.read_bytes()
    real_read = fsutil.read_json
    held = {daily_env.paths.settings}

    def read_json(path):
        if path in held:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real_read(path)

    monkeypatch.setattr(fsutil, "READ_RETRY_S", 0.1)
    for mod in ("agent_reach.daily.prefs", "agent_reach.daily.state"):
        monkeypatch.setattr(f"{mod}.read_json", read_json)
    prefs, warn = lp(daily_env.paths)
    assert warn and "could not be read just now" in warn and "not changed" in warn
    out = _refresh(daily_env)
    assert out.code == R.EXIT_FAILED and "could not be read" in out.message
    held.add(daily_env.paths.state_file)
    out = _refresh(daily_env)
    assert out.code == R.EXIT_FAILED
    held.clear()
    assert daily_env.paths.settings.read_bytes() == settings_before  # untouched, never renamed
    assert daily_env.paths.state_file.read_bytes() == state_before
    assert not list(daily_env.paths.root.glob("settings.json.corrupt-*"))
    assert not list(daily_env.paths.state_dir.glob("refresh_state.json.corrupt-*"))
    assert _refresh(daily_env).code == R.EXIT_PUBLISHED


def test_an_edition_file_held_open_fails_the_refresh_in_plain_words(daily_env, monkeypatch):
    from agent_reach.daily import store as S

    first = _refresh(daily_env).edition

    def held(path, text):
        raise PermissionError(13, "The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(S, "atomic_write_text", held)
    out = _refresh(daily_env)
    assert out.code == R.EXIT_FAILED and "could not be saved" in out.message and "open in another program" in out.message
    assert "Unexpected error" not in out.message
    assert EditionStore(daily_env.paths).load_latest().edition.run_id == first.run_id
