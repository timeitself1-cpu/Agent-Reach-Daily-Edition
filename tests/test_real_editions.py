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
