"""Style regressions use headline text only, without inventing supporting reporting."""
import pytest

from agent_reach.daily.headlines import HeadlineConfig, normalize_headline


@pytest.mark.parametrize("word", "awarded hit step steps deadly attacks allies says analysis takeaways sweep killed amid after before powerful earthquakes watch livestream execution shooter".split())
def test_generic_headline_words_lowercase(word):
    assert normalize_headline(f"Panama {word.title()} Today", cfg=HeadlineConfig()) == f"Panama {word} today"


def test_new_generic_words_still_keep_story_names_quotes_and_acronyms():
    cfg = HeadlineConfig()
    assert normalize_headline('NASA Says "Deadly Attacks" Hit iPhone?', cfg=cfg) == 'NASA says "Deadly Attacks" hit iPhone?'
    assert normalize_headline('Panama Says Powerful Prize', names={'Powerful'}, cfg=cfg) == 'Panama says Powerful Prize'
    assert normalize_headline('Panama Hits Norvale Today', cfg=cfg) == 'Panama hits Norvale today'
