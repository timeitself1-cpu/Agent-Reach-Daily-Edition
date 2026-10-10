"""The editorial pass of October 10, 2026: summaries that tell more than their headline."""

from __future__ import annotations

from agent_reach.daily.edition import adds_to_headline, body_sentences
from agent_reach.daily.publish import public_edition
from agent_reach.pipeline.clusterer import CLUSTER_SYSTEM_PROMPT
from agent_reach.pipeline.summary_checks import (added_sentences, clean_title, extractive_fallback, useful_summary,
                                                 verified_story)
from tests.daily_fakes import make_edition, make_story

HURRICANE = "Isaias strengthens into Category 2 hurricane on collision course with the Gulf Coast"


def test_a_sentence_that_restates_its_headline_adds_nothing():
    """The October 9 edition opened 17 of its 27 summaries with the headline, word for word or nearly."""
    assert not adds_to_headline(HURRICANE + ".", HURRICANE)
    assert not adds_to_headline("Fort Hood attacker's execution by firing squad will be livestreamed, Pentagon says.",
                                "Firing Squad Execution to Be Livestreamed, Pentagon Says")
    assert not adds_to_headline("Houthi strikes on Riyadh airport killed three Saudis as war escalates.",
                                "Houthi Strikes on Riyadh Airport Killed Three Saudis")
    assert adds_to_headline("The first hurricane of the Atlantic season was forecast to intensify rapidly and cause "
                            "dangerous conditions in the Gulf.", HURRICANE)
    # a fact the headline lacks counts even when most words are shared (who: 'co-creator of Empire Market')
    assert adds_to_headline("A US judge sentenced Raheim Hamilton, co-creator of the dark web marketplace Empire Market, "
                            "to 40 years in prison.", "US Judge Sentences Raheim Hamilton to 40 Years in Prison")


def test_the_public_summary_leaves_out_repeats_cut_off_and_dangling_sentences():
    head = "Margaret Hamilton, computing pioneer who led software development for the Apollo program, dies at 90"
    assert useful_summary(head, [head + ".", "She coined the term software engineering and founded two companies."]) == []
    assert useful_summary(HURRICANE, ["Forecasters said the storm could bring a six-foot surge to coastal Alabama"]) == []
    assert useful_summary("OpenAI withdraws three mathematical results",
                          ["Contribute to openai/math development by creating an account on GitHub."]) == []
    keep = "Forecasters expect landfall near Mobile on Thursday, with surge warnings for three states."
    assert useful_summary(HURRICANE, [HURRICANE + ".", keep]) == [keep]
    # the app's own body sentences follow the same rule: the restating sentence is not the summary
    assert body_sentences(f"{HURRICANE}. {keep}", None, HURRICANE) == [keep]


def test_the_fallback_uses_the_reports_own_sentences_never_the_title_twice():
    sources = [
        ("What to expect at Apple's 'Welcome home' event next week - Engadget",
         "Apple will hold a launch event on October 27 in Cupertino. Sign up for our newsletter."),
        ("Trump Says U.S. Won't Attack Iran Before Midterms",  # another subject: never borrowed from
         "Trump says U.S. won't attack Iran before midterms. And, ICE agent shoots man in NYC."),
    ]
    headline, summary = extractive_fallback(sources)
    assert headline == "What to expect at Apple's 'Welcome home' event next week"
    assert summary == "Apple will hold a launch event on October 27 in Cupertino."
    assert added_sentences(sources[1:], sources[1][0]) == []  # 'And, ...' leans on a sentence that is not there
    assert clean_title("Fury vs Joshua - tickets sell out in one hour") == "Fury vs Joshua - tickets sell out in one hour"
    # nothing to add: the app still has a sentence to show, the website none
    title, text = extractive_fallback([("Princeton Celebrates Anne Carson, a Nobel Prize Winner", None)])
    assert text == title + "." and useful_summary(title, [text]) == []


def test_a_sentence_that_fails_the_check_is_dropped_alone():
    """One unsupported sentence used to throw away the whole model summary for the source title."""
    story = make_story(headline="Norvale Ferry Strike Halts Island Service",
                       sentences=["Ferry workers in Norvale went on strike on Monday over unpaid overtime.",
                                  "The strike cost the island 900 jobs."])
    story.evidence[0].excerpt = "Ferry workers in Norvale went on strike on Monday over unpaid overtime, the union said."
    headline, summary = verified_story(story)
    assert headline == "Norvale Ferry Strike Halts Island Service"
    assert summary == ["Ferry workers in Norvale went on strike on Monday over unpaid overtime."]


def test_the_labelling_prompt_forbids_repeating_the_headline():
    assert "never repeat or reword the headline" in CLUSTER_SYSTEM_PROMPT
    assert "neutral news headline" in CLUSTER_SYSTEM_PROMPT


def test_a_published_edition_has_no_summary_that_repeats_its_headline():
    stories = [make_story(1, sentences=["Norvale Ferry Strike Halts Island Service across the bay."]),
               make_story(2, headline="Port Calder Earthquake Damages Roads",
                          sentences=["A magnitude 6.1 earthquake struck Port Calder early on Tuesday, officials said."])]
    stories[1].evidence[0].excerpt = "A magnitude 6.1 earthquake struck Port Calder early on Tuesday, officials said."
    public = public_edition(make_edition(stories))
    by_head = {s["headline"]: s["summary"] for s in public["stories"]}
    assert by_head["Norvale Ferry Strike Halts Island Service"] == []
    assert by_head["Port Calder Earthquake Damages Roads"] == [
        "A magnitude 6.1 earthquake struck Port Calder early on Tuesday, officials said."]
