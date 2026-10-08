"""Regression fixtures from REAL editions made on the user's Windows PC (llama3.1:8b on an RTX 4070 Super).

``tests/fixtures/real/2026-10-07-selftest-r1.json`` and ``-r2.json`` are the two editions the rc11 self-test
made on October 7, 2026, 9 minutes apart (r2 after changing the section size to 8). Each test names the story
it comes from. Tests marked ``xfail`` record problems seen in those editions that are NOT fixed yet (the
event layer is the next phase); they turn into failures ('XPASS', strict) once fixed, so the mark is removed
then. Nothing here tunes thresholds blindly: every case is a real sentence or a real pair of stories.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_reach.daily.edition import DailyEdition, Selection, build_coverage, same_topic, without_unstated
from agent_reach.daily.prefs import DailyPrefs

FIXTURES = Path(__file__).parent / "fixtures" / "real"


def _edition(name: str) -> DailyEdition:
    return DailyEdition.model_validate_json((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def r1() -> DailyEdition:
    return _edition("2026-10-07-selftest-r1.json")


@pytest.fixture(scope="module")
def r2() -> DailyEdition:
    return _edition("2026-10-07-selftest-r2.json")


def _story(ed: DailyEdition, start: str):
    return next(s for s in ed.stories if s.headline.startswith(start))


def test_real_editions_still_load(r1, r2):
    """The edition schema must keep reading what the app wrote on Windows."""
    assert len(r1.stories) == 48 and r1.model.label_calls == 21 and r1.model.label_calls_failed == 0
    assert r2.revision == 2 and r2.changes is not None


def test_model_remarks_about_its_input_are_removed(r1):
    for start, kept in (("Why Is NASA Bringing", "NASA is bringing 7,500 contractors back to work as civil servants."),
                        ("Meta's Muse", "Meta's Muse is a privacy and security dumpster fire.")):
        s = _story(r1, start)
        source = " ".join(e.title + " " + (e.excerpt or "") for e in s.evidence)
        assert "not specified" in s.sentences[0]  # as published by rc11
        assert without_unstated(s.sentences[0], source) == kept


def test_model_context_is_cut_at_a_word():
    from agent_reach.pipeline.clusterer import clip_words

    text = ("Mistral Large 4 has 1.05 trillion parameters with 49 billion active, native image input and a 1 million "
            "token context window. It was trained on 3,800 NVIDIA Grace Blackwell superchips over three months.")
    clipped = clip_words(text, 160)
    assert len(clipped) <= 164 and clipped.endswith(" ...")
    assert all(w in text.split() for w in clipped.removesuffix(" ...").split())  # no word cut in half ('Grac.')


def test_youtube_outage_is_one_note_not_21_broken_feeds(r1):
    """YouTube answered 1 of 22 channels (October 7). The note named 'BBC News, Reuters, Associated Press' as
    feeds that returned nothing, while the BBC's article feeds worked; the feed doctor would have blamed 21
    good addresses after three days."""
    from agent_reach.daily.feedhealth import channel_outage

    youtube = next(h for h in r1.source_health if h.source == "youtube")
    assert sum(f.status == "failed" for f in youtube.feeds) == 21
    feeds = [SimpleNamespace(ok=f.status != "failed") for f in youtube.feeds]
    assert channel_outage(feeds)
    cov = build_coverage(r1.source_health, r1.stories, Selection(stories=r1.stories), SimpleNamespace(llm_mode="ollama"))
    text = " ".join(cov.warnings)
    assert "YouTube did not answer for 21 of 22 channels" in text
    assert "BBC News," not in text and "Reuters" not in text


def test_review_of_a_real_edition_finds_what_a_reader_found(r1):
    from tests.daily_selftest import review_edition

    found = "\n".join(review_edition(r1, DailyPrefs()))
    assert "#15 'Lionel Messi Bids Farewell" in found and "#37 'Messi Signs Off" in found
    assert "('Grac')" in found
    assert found.count("the model talks about its input") == 2


def test_connection_refused_stops_the_model_calls():
    """When Ollama went away halfway (October 7), every remaining label batch and brief batch tried three
    times; each refused connect takes ~2 s on Windows, so the refresh ended 112 s after the cut."""
    from agent_reach.config import Settings
    from agent_reach.pipeline.clusterer import ClusteringError, SemanticClusterer

    class Gone:
        calls = 0

        async def chat(self, **kw):
            Gone.calls += 1
            raise ConnectionError("Failed to connect to Ollama. Please check that Ollama is downloaded, running")

    c = SemanticClusterer(Settings(llm_max_retries=2))
    c._client = Gone()

    async def run():
        for k in range(5):
            with pytest.raises(ClusteringError):
                await c._chat_json("s", "u", {}, f"label {k}")

    asyncio.run(run())
    assert Gone.calls == 1 and c.model_gone


@pytest.mark.xfail(strict=True, reason="next phase (event layer): one event reported in two sections")
def test_one_event_appears_once(r1):
    """Messi's farewell is #15 (Sports) and #37 (Entertainment) in the same edition."""
    assert same_topic(_story(r1, "Lionel Messi Bids Farewell"), _story(r1, "Messi Signs Off in Tears"))


@pytest.mark.xfail(strict=True, reason="next phase (event layer): editions minutes apart should agree")
def test_a_refresh_minutes_later_keeps_the_corroborated_news(r1, r2):
    """r2 ran 9 minutes after r1 on the same news. 28 of r1's 48 stories were 'no longer listed', including
    two corroborated Top-Story-grade reports, and only 20 of r2's 35 stories matched r1."""
    heads = {s.headline for s in r2.stories}
    assert "Eva Marie Saint Dies at 102" in heads and "Kenya Confirms First Ebola Case and Death" in heads
    assert len(r2.changes.new) <= 5


@pytest.mark.xfail(strict=True, reason="next phase: business news filed under Tech by the reporting outlet")
def test_media_merger_is_news_not_tech(r1):
    assert _story(r1, "Paramount Completes").category.value == "News"


@pytest.mark.xfail(strict=True, reason="next phase: 'why it matters' is accepted for 2 of 18 stories")
def test_why_it_matters_for_most_top_stories(r1):
    tops = [s for s in r1.stories if s.rank in set(r1.top_ranks)]
    assert sum(1 for s in tops if s.why_it_matters) >= len(tops) // 2


def test_fixture_files_are_valid_json():
    for p in FIXTURES.glob("*.json"):
        json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- second self-test run, October 7 (9:29 AM)
@pytest.fixture(scope="module")
def s2r1() -> DailyEdition:
    return _edition("2026-10-07-selftest2-r1.json")


@pytest.fixture(scope="module")
def s2r2() -> DailyEdition:
    return _edition("2026-10-07-selftest2-r2.json")


def test_a_middle_initial_does_not_end_a_sentence(s2r1):
    """#30 James Watson: the summary was split into 'Biologist James D.' and 'Watson appears to have ...'."""
    from agent_reach.daily.edition import SENTENCE_SPLIT_RX, body_sentences

    s = _story(s2r1, "James Watson Underplayed")
    assert s.sentences[0] == "Biologist James D."  # as published by rc11
    joined = " ".join(s.sentences)
    assert SENTENCE_SPLIT_RX.split(joined) == [joined]
    source = " ".join(e.title + " " + (e.excerpt or "") for e in s.evidence) + " " + joined
    assert body_sentences(joined, source)[0].startswith("Biologist James D. Watson appears")


@pytest.mark.xfail(strict=True, reason="next phase (event layer): the #1 story of an edition must not vanish")
def test_the_lead_story_survives_the_next_refresh(s2r1, s2r2):
    """'US Woman Who Survived Botched Execution Is Conscious, Speaking' (Christa Pike, 3 reports, #1 in Top
    Stories) is not in the edition made 6 minutes later at all."""
    lead = next(s for s in s2r1.stories if s.rank == s2r1.top_ranks[0])
    assert any("Pike" in " ".join([s.headline, *s.sentences, *s.entities]) for s in s2r2.stories), lead.headline


@pytest.fixture(scope="module")
def export0935() -> dict:
    return json.loads((FIXTURES / "2026-10-07-0935-export.json").read_text(encoding="utf-8"))


def test_a_summary_cut_at_a_quotation_mark_is_not_published(export0935):
    """Export of October 7 (9:35), Science #3 'James Webb Space Telescope Investigates Planetary Collisions':
    the whole summary was 'By studying 21 rare.' The source says 'By studying 21 rare "extreme debris disks"
    around young stars, ...': the model's JSON text ended at the unescaped inner quote. Rejected now, and the
    story falls back to the reports' own lead sentence instead."""
    from agent_reach.daily.edition import INTRO_ONLY_RX, body_sentences, build_story, truncated_copy
    from agent_reach.models import MacroCluster
    from tests.event_corpus import load_edition

    published = next(s for s in export0935["stories"] if s["headline"].startswith("James Webb Space Telescope"))
    assert published["summary"] == "By studying 21 rare."  # as rc11 published it
    corpus = load_edition("2026-10-07-0935-export.json")
    items = {c.item.item_id: c.item for c in corpus if c.gold == published["headline"]}
    source = " ".join(it.context or "" for it in items.values())
    assert truncated_copy("By studying 21 rare.", source) and INTRO_ONLY_RX.match("By studying 21 rare.")
    assert not truncated_copy("Researchers studied 21 rare debris disks around young stars.", source)
    assert body_sentences("By studying 21 rare.", source) == []
    cluster = MacroCluster(cluster_id="webb", headline=published["headline"], category="Science & AI",
                           relevance_score=7, velocity_score=10.0, summary="By studying 21 rare.",
                           raw_item_count=len(items), member_item_ids=list(items))
    story = build_story(3, cluster, items)
    assert story is not None and story.sentences[0].startswith("NASA's James Webb Space Telescope is giving astronomers")


def test_a_month_abbreviation_does_not_end_a_sentence(s2r2):
    """Selftest2 r2 #9 'Netanyahu Faces Reckoning over Oct. 7 Terror Attacks in Israeli Election': the summary
    was published as 'Prime Minister Benjamin Netanyahu faces a reckoning over the Oct.': the splitter ended
    the sentence after 'Oct.' and the rest ('7 terror attacks ...', not a sentence) was dropped."""
    from agent_reach.daily.edition import SENTENCE_SPLIT_RX, body_sentences
    from agent_reach.pipeline.cleaner import SENTENCE_RX, sanitize_summary

    s = _story(s2r2, "Netanyahu Faces Reckoning")
    assert s.sentences == ["Prime Minister Benjamin Netanyahu faces a reckoning over the Oct."]  # as rc11 published it
    for rx in (SENTENCE_SPLIT_RX, SENTENCE_RX):
        assert len(rx.split("Netanyahu faces a reckoning over the Oct. 7 attacks. Voters go to the polls.")) == 2
        assert len(rx.split("The deal closed on Sept. 30 after a vote. It took a year.")) == 2
    full = "Prime Minister Benjamin Netanyahu faces a reckoning over the Oct. 7 terror attacks in the Israeli election."
    assert sanitize_summary(full) == full
    source = " ".join(e.title + " " + (e.excerpt or "") for e in s.evidence) + " " + s.headline
    assert body_sentences(full, source) == [full]


def test_the_newest_report_controls_the_current_state():
    """Export of October 7 (9:35, a Wednesday), #2 'Stock Markets Hit Record High Despite Inflation, High Fuel
    Prices': the summary said 'U.S. stock markets hit a record high Tuesday ...' while the story's newest report
    (CNBC live updates, 9:00 a.m.) said stocks fell on Wednesday. The current state now leads, the
    Tuesday record stays as what came before, and the card says the story is developing."""
    from datetime import datetime, timezone

    from agent_reach.daily.edition import DEVELOPING_LABEL, build_story, newest_state
    from agent_reach.models import MacroCluster
    from tests.event_corpus import load_edition

    corpus = load_edition("2026-10-07-0935-export.json")
    head = "Stock Markets Hit Record High Despite Inflation, High Fuel Prices"
    items = {c.item.item_id: c.item for c in corpus if c.gold == head}
    tuesday = ("U.S. stock markets hit a record high Tuesday amid major inflation and skyrocketing fuel prices. "
               "The S&P 500 reached a new high Tuesday as tech stocks rallied.")
    cluster = MacroCluster(cluster_id="stocks", headline=head, category="News", relevance_score=9, velocity_score=78.0,
                           summary=tuesday, raw_item_count=len(items), member_item_ids=list(items))
    at = datetime(2026, 10, 7, 14, 35, tzinfo=timezone.utc)
    story = build_story(2, cluster, items, at)
    assert story.sentences[0] == ("U.S. equities fell on Wednesday, a day after the S&P 500 reached a fresh all-time "
                                  "high, as oil prices moved higher alongside Treasury yields.")
    assert story.sentences[1].startswith("U.S. stock markets hit a record high Tuesday")
    assert DEVELOPING_LABEL in story.labels
    # the same summary written on Tuesday evening is the current state: nothing changes
    tue = datetime(2026, 10, 6, 23, 0, tzinfo=timezone.utc)
    assert newest_state(story.sentences[1:], cluster, items, tue) is None
    assert newest_state(["Stocks fell on Wednesday as yields rose."], cluster, items, at) is None


def test_selftest_reports_a_failed_offline_suite_as_fail(tmp_path, monkeypatch):
    """The October 7 self-test said PASS for pytest's '1 failed, 449 passed, 2 skipped, 5 xfailed, 1 warning,
    2 errors' (the 2 errors were stray test files of other work): with only -rs, pytest prints no FAILED lines."""
    import subprocess
    import tests.daily_selftest as st

    stdout = "\n".join([
        "ERROR collecting tests/test_event_contract.py", "ERROR collecting tests/test_event_identity.py",
        "SKIPPED [1] tests\\test_daily_gui.py:67: no display: Can't find a usable tk.tcl",
        "1 failed, 449 passed, 2 skipped, 5 xfailed, 1 warning, 2 errors in 279.11s (0:04:39)"])
    monkeypatch.setattr(st.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, stdout, ""))
    report = st.Report(tmp_path)
    st.part_pytest(report, None)
    status = {c.name: c.status for c in report.checks}
    assert status["test files that do not load (not part of this release?)"] == "FAIL"
    assert status["full offline suite (window, Windows locks, process kill/cancel, pipeline)"] == "FAIL"
    assert status["window tests ran inside the test suite"] == "FAIL"
    clean = stdout.replace("1 failed, ", "").replace("SKIPPED [1] tests\\test_daily_gui.py:67: no display: Can't find a usable tk.tcl\n", "")
    monkeypatch.setattr(st.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, clean, ""))
    report = st.Report(tmp_path)
    st.part_pytest(report, None)
    status = {c.name: c.status for c in report.checks}  # only the stray files: the suite itself passed
    assert status["full offline suite (window, Windows locks, process kill/cancel, pipeline)"] == "PASS"
    assert "window tests ran inside the test suite" not in status
