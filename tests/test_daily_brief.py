"""Daily app: the local model may add detail and 'why it matters' only when grounded in the evidence."""

from __future__ import annotations

import asyncio
import json

import pytest

from agent_reach.config import Settings
from agent_reach.daily.brief import apply_brief, enrich_stories, grounded
from tests.daily_fakes import make_story

EVIDENCE = ("Ferry workers in Norvale began a 48-hour strike over pay on Tuesday, halting service to three islands. "
            "The Norvale Port Authority said talks with the union resume on Friday. Twelve island schools closed. "
            "The EU transport office said fares could rise by 5 percent.")


@pytest.mark.parametrize("sentence", [
    "Island residents lose their ferry link while the 48-hour strike lasts.",
    "Talks between the Norvale Port Authority and the union resume on Friday.",
    "Families on three islands are cut off until the strike ends.",
    "Twelve island schools closed during the strike.",
    "The EU transport office said fares could rise by 5 percent.",  # hedge and acronym are in the evidence
])
def test_supported_names_numbers_and_quantities_pass(sentence):
    assert grounded(sentence, EVIDENCE)


@pytest.mark.parametrize("sentence", [
    "Mayor Elena Ruiz called the strike illegal.",  # invented person
    "The strike will cost the region 12 million dollars.",  # invented number + magnitude
    "Ferry fares rose by twenty percent.",  # invented spelled-out quantity
    "The UN condemned the strike on Tuesday.",  # 2-letter acronym not in evidence
    "The strike might spread to other ports.",  # speculation the evidence does not make
    "Unions in Artesia joined the strike.",  # substring 'art' of 'start' is not evidence for 'Artesia'
    "This could have significant implications for the region.",
    "This highlights the importance of reliable ferry links.",
    "Only time will tell how long the strike lasts.",
    "It remains to be seen whether talks on Friday succeed.",
    "Read more at https://example.com/norvale",
    "[INSUFFICIENT_DATA]",
    "",
])
def test_unsupported_or_generic_claims_are_rejected(sentence):
    assert not grounded(sentence, EVIDENCE)


def _story():
    s = make_story(headline="Norvale Ferry Strike Halts Island Service",
                   sentences=["Ferry workers in Norvale began a 48-hour strike over pay."])
    s.evidence[0].title = "Norvale ferry strike halts island service"
    s.evidence[0].excerpt = EVIDENCE
    return s


def test_apply_brief_adds_only_grounded_novel_text():
    s = _story()
    added, why = apply_brief(s, "Talks with the union resume on Friday. Ferry workers in Norvale began a 48-hour strike.",
                             "Island residents lose their ferry link while the 48-hour strike lasts.")
    assert added == 1 and s.sentences[-1] == "Talks with the union resume on Friday."  # the repeat was dropped
    assert why == 1 and s.why_it_matters.startswith("Island residents")
    s2 = _story()
    assert apply_brief(s2, "Mayor Elena Ruiz resigned.", "This highlights the importance of ferries.") == (0, 0)
    assert s2.why_it_matters is None and len(s2.sentences) == 1


class _Client:
    def __init__(self, content=None, exc=None):
        self.content, self.exc, self.calls = content, exc, 0

    async def chat(self, **kw):
        self.calls += 1
        if self.exc:
            raise self.exc
        return {"message": {"content": self.content}}


def _run(stories, client):
    return asyncio.run(enrich_stories(stories, Settings(), client=client))


def test_model_failures_never_raise_and_leave_stories_untouched():
    for client in (_Client(exc=ConnectionError("Ollama went away")), _Client(content="I cannot answer that."),
                   _Client(content=""), _Client(content='{"stories": "nonsense"}')):
        s = _story()
        before = s.model_dump()
        stats = _run([s], client)
        assert s.model_dump() == before
        assert stats["calls"] == 1


def test_model_answers_are_validated_per_story():
    stories = [_story(), _story()]
    content = json.dumps({"stories": [
        {"id": 1, "details": "", "why_it_matters": "Island residents lose their ferry link while the 48-hour strike lasts."},
        {"id": 2, "details": "", "why_it_matters": "Coach Marta Velez said the strike costs $5 million."},
    ]})
    stats = _run(stories, _Client(content=content))
    assert stories[0].why_it_matters and stories[1].why_it_matters is None
    assert stats["why_added"] == 1 and stats["rejected"] == 1
