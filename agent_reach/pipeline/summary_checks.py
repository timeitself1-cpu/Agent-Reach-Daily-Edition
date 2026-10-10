"""Conservative, sentence-level checks over cited titles/excerpts; no model or network needed."""
from __future__ import annotations

import re


def repair_text(text: str) -> str:
    text = text.replace('“', '"').replace('”', '"')
    # Abbreviations do not end a sentence: P.T. Has -> P.T. has.
    text = re.sub(r'\b((?:[A-Z]\.){2,})\s+(Has|Have|Is|Was|Are|Were)\b',
                  lambda m: m[1] + ' ' + m[2].lower(), text)
    if text.count('"') % 2:
        # A lost opening quote is safest to repair by removing the orphan quote. Do not invent quotation.
        pos = text.rfind('"')
        text = text[:pos] + text[pos + 1:]
    return text.strip()


def sentences(text: str) -> list[str]:
    from agent_reach.daily.edition import SENTENCE_SPLIT_RX
    return [s.strip() for part in re.split(r'\s*\|\s*|[\r\n]+', repair_text(text))
            for s in SENTENCE_SPLIT_RX.split(part) if s.strip()]


def _words(text: str) -> set[str]:
    from agent_reach.pipeline.cleaner import STOPWORDS
    return {w.removesuffix('s') for w in re.findall(r'[a-z0-9]+', text.lower()) if w not in STOPWORDS}


def _subjectless(sentence: str) -> bool:
    from agent_reach.daily.edition import is_fragment
    return is_fragment(sentence) or bool(re.match(
        r'^(?:teaches|works|studies|says|said|has|have|is|was|are|were|became|becomes|'
        r'announces|announced|reveals|revealed|claims|claimed|launches|launched|'
        # a participle with no subject: 'Built for high-volume work like summarization, subagents, and browser use.'
        r'built|designed|made|meant|aimed|intended|available|coming|set to|slated to)\b', sentence, re.I))


def _anchored(sentence: str, source: str) -> bool:
    from agent_reach.daily.brief import grounded
    from agent_reach.daily.edition import numbers_anchored
    if not grounded(sentence, source) or not numbers_anchored(sentence, source):
        return False
    from agent_reach.daily.brief import QUANTITY_WORDS
    # A total number of people is not a count of astronauts. Match the noun immediately following a quantity.
    def quantity_pairs(text):
        words = re.findall(r'[a-z]+|\d[\d,]*(?:\.\d+)?', text.lower())
        return [(w.replace(',', ''), words[i + 1].removesuffix('s')) for i, w in enumerate(words[:-1])
                if w in QUANTITY_WORDS or w[0].isdigit()]
    for number, noun in quantity_pairs(sentence):
        if (number, noun) not in quantity_pairs(source):
            return False
    overlap = _words(sentence) & _words(source)
    if len(overlap) < min(3, len(_words(sentence))):
        return False
    # Numbers may not inherit a country's total or multi-day period in an event-local sentence.
    has_number = bool(re.search(r'\d|\b(?:two|three|four|five|six|seven|eight|nine|ten)\b', sentence, re.I))
    if has_number:
        scope_words = {'nationwide', 'countrywide', 'france', 'across', 'between', 'through', 'since'}
        scoped = _words(source) & scope_words
        if scoped and not scoped <= _words(sentence):
            return False
        dates = re.findall(r'\b(?:Jan\w*|Feb\w*|Mar\w*|Apr\w*|May|Jun\w*|Jul\w*|Aug\w*|Sep\w*|Oct\w*|Nov\w*|Dec\w*)\s+\d{1,2}\b', source, re.I)
        if len(dates) >= 2 and not all(d.lower() in sentence.lower() for d in dates):
            return False
    return True


def _evidence(sources: list[tuple[str, str | None]]) -> list[str]:
    return [s for title, excerpt in sources for part in (title, excerpt or '') for s in sentences(part)]


def sentence_problems(sentence: str, evidence: list[str]) -> list[str]:
    """What is wrong with one summary sentence: no subject, or a number or name no single source sentence supports."""
    errors = []
    if _subjectless(sentence):
        errors.append('sentence has no subject')
    if not any(_anchored(sentence, source) for source in evidence):
        errors.append('number or named entity lacks cited sentence context')
    return errors


def _title_case(text: str) -> bool:
    words = [w for w in re.findall(r"[A-Za-z][\w'\u2019-]*", text)[1:] if len(w) > 3]
    return bool(words) and sum(w[0].isupper() for w in words) >= 0.7 * len(words)


def summary_problems(text: str, headline: str, sources: list[tuple[str, str | None]]) -> list[str]:
    """What is wrong with the summary as a whole: empty, or not about the headline's names and action."""
    from agent_reach.daily.brief import CAP_WORD_RX, STARTERS, COMMON_OPENERS
    from agent_reach.pipeline.cleaner import STOPWORDS
    errors = []
    if not sentences(text):
        errors.append('empty summary')
    summary_words = _words(text)
    group_nouns = COMMON_OPENERS | {'crew', 'astronauts', 'cosmonauts'}
    names = {w.lower().strip(".'") for w in CAP_WORD_RX.findall(headline)
             if w.lower() not in STOPWORDS | STARTERS | group_nouns}
    # Conservative entity candidates must also occur in cited titles or prose, including feeds with no excerpt.
    prose = ' '.join(title + ' ' + (excerpt or '') for title, excerpt in sources)
    entities = {name for name in names if re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', prose, re.I)}
    # A Title Case headline capitalises every word: only words the reports write as names count ('Norvale' in
    # 'Ferry workers in Norvale walked out', not 'Strike', 'Halts' or 'Service'). Requiring them all made a summary
    # either repeat the headline or fall back to a source title (October 9: 17 of 27 summaries opened with it).
    if _title_case(headline):
        written = ' '.join([excerpt or '' for _, excerpt in sources] + [t for t, _ in sources if not _title_case(t)])
        caps = {w.lower().strip(".'"): w.strip(".'") for w in CAP_WORD_RX.findall(headline)}

        def written_as_name(name: str) -> bool:
            word = caps.get(name, name)
            if len(word) > 1 and word.isupper():
                return True  # an acronym: 'NASA', 'US'
            form = word[:1].upper() + word[1:]
            return bool(re.search(r"[a-z,;:]['\u2019]?\s+" + re.escape(form) + r"(?!\w)", written))

        entities = {name for name in entities if written_as_name(name)}
    if not _words(' '.join(entities)) <= summary_words:
        errors.append('headline key entity missing from summary')
    # Also require the headline's event/action, not only a shared actor (Misnames vs terrorist claim).
    actions = {'misnames', 'misnamed', 'names', 'named', 'launches', 'launch', 'wins', 'win', 'strikes', 'strike',
               'arrests', 'arrest', 'suspends', 'suspend', 'resigns', 'resign', 'teaches', 'teach'}
    headline_actions = {w.removesuffix('s') for w in re.findall(r'[a-z]+', headline.lower()) if w in actions}
    if headline_actions and not headline_actions & summary_words:
        errors.append('headline action disagrees with summary')
    return errors


def validate_summary(text: str, headline: str, sources: list[tuple[str, str | None]]) -> list[str]:
    """All sentence quantities/entities must be supported together by one source sentence.

    This is a conservative text gate, not semantic proof. Unverifiable paraphrases fall back to extraction.
    """
    evidence = _evidence(sources)
    errors = [e for sentence in sentences(text) for e in sentence_problems(sentence, evidence)]
    errors += summary_problems(text, headline, sources)
    return list(dict.fromkeys(errors))


#: A publisher's name after a headline ('What to expect at Apple's 'Welcome home' event next week - Engadget').
_PUBLISHER_SUFFIX_RX = re.compile(r"\s+[-|\u2013\u2014]\s+(?:[A-Z][\w.&'\u2019]*|of|the|and|on)(?:\s+(?:[A-Z][\w.&'\u2019]*|of|the|and|on)){0,4}$")
#: Page furniture, not news: 'In this episode, ...', 'Find the full MLB playoff bracket ...', 'Sign up for ...'.
_PROMO_RX = re.compile(r"^(?:in (?:this|today's|the latest) (?:episode|video|podcast|newsletter|edition|week's)|"
                       r"(?:find|watch|listen|read|click|subscribe|sign up|follow|get|download|see)\b|"
                       r"(?:here's|here is|here are) (?:what|how|why|everything)|contribute to\b)|"
                       r"\bby creating an account\b", re.I)
#: The end of a complete sentence ('... a record fifth time' without one was cut off by the feed).
_COMPLETE_RX = re.compile(r"[.!?][\"'\u2019\u201d)]*$")


def clean_title(title: str) -> str:
    """A source title as a headline: repaired, without a publisher's name tacked on the end."""
    title = repair_text(title)
    stripped = _PUBLISHER_SUFFIX_RX.sub('', title)
    return stripped if len(stripped.split()) >= 4 else title


def _sound(sentence: str) -> bool:
    """A complete, plain sentence of reporting that can stand on its own under a headline."""
    from agent_reach.daily.edition import (INTRO_ONLY_RX, META_SENTENCE_RX, PRONOUN_START_RX, WEAK_SENTENCE_RX,
                                           ends_dangling, is_fragment, looks_english, page_voice)
    return (len(sentence) >= 40 and _complete(sentence) and ' | ' not in sentence and looks_english(sentence)
            and not page_voice(sentence) and not is_fragment(sentence) and not ends_dangling(sentence)
            and not PRONOUN_START_RX.match(sentence) and not INTRO_ONLY_RX.match(sentence)
            and not META_SENTENCE_RX.match(sentence) and not WEAK_SENTENCE_RX.search(sentence)
            and not _PROMO_RX.match(sentence) and not _subjectless(sentence))


def _complete(sentence: str) -> bool:
    return bool(_COMPLETE_RX.search(sentence)) and not sentence.rstrip('"\'\u2019\u201d)').endswith(('...', '\u2026'))


def _same_subject(title: str, headline: str) -> bool:
    from agent_reach.daily.edition import _headline_stems
    return len(_headline_stems(title) & _headline_stems(headline)) >= 2


def added_sentences(sources: list[tuple[str, str | None]], headline: str, limit: int = 2) -> list[str]:
    """Up to ``limit`` sentences of the reports' own text that tell more than the headline: the first sound one of
    each report whose title is about the headline's subject (a podcast's 'And, ICE agent shoots man in NYC.' under a
    story on Iran was the second half of a roundup's description, October 9), in source order."""
    from agent_reach.daily.edition import adds_to_headline
    out: list[str] = []
    for title, excerpt in sources:
        if len(out) >= limit:
            break
        if not _same_subject(title, headline):
            continue
        for sentence in sentences(excerpt or ''):
            sentence = re.sub(r'\s+', ' ', sentence).strip()
            if _sound(sentence) and adds_to_headline(sentence, ' '.join([headline, *out])):
                out.append(sentence)
                break
    return out


def useful_summary(headline: str, body: list[str]) -> list[str]:
    """The summary sentences a reader gains something from under ``headline``: complete ones that do not repeat
    it, and no 'They ...' left without the sentence it refers to. May be empty: the headline then stands alone."""
    from agent_reach.daily.edition import PRONOUN_START_RX, adds_to_headline
    out: list[str] = []
    for sentence in body:
        if not _complete(sentence) or _PROMO_RX.match(sentence):
            continue
        if not adds_to_headline(sentence, ' '.join([headline, *out])):
            continue
        if not out and PRONOUN_START_RX.match(sentence):
            continue
        out.append(sentence)
    return out


def extractive_fallback(sources: list[tuple[str, str | None]]) -> tuple[str, str]:
    """Best source (caller order) title as the headline, and what the reports' own sentences add to it. With no
    such sentence the summary is the title itself (the app shows every story with a sentence; the public edition
    leaves a summary that repeats its headline out: ``useful_summary``). Until October 10 the summary always
    began with the title, so the website printed most headlines twice."""
    for title, _ in sources:
        title = clean_title(title)
        if title:
            break
    else:
        return '', ''
    added = added_sentences(sources, title)
    return title, ' '.join(added) if added else title.rstrip('.!?') + '.'


def verified_story(story) -> tuple[str, list[str]]:
    """The headline and summary sentences that pass the checks against the story's own cited reports. Sentences
    that fail are left out one by one (the rest must still name the headline's subject and action); with none
    left, the best report's title and its own sentences replace the model's text (``extractive_fallback``)."""
    from agent_reach.daily.strength import SIGNAL_SOURCES
    from agent_reach.pipeline.clusterer import is_roundup
    cited = [(ev.title, ev.excerpt) for ev in story.evidence
             if ev.source not in SIGNAL_SOURCES and not is_roundup(ev.title)]
    if not cited:
        cited = [(ev.title, ev.excerpt) for ev in story.evidence]
    text = repair_text(' '.join(story.sentences))
    headline = repair_text(story.headline)
    evidence = _evidence(cited)
    body = [s for s in sentences(text) if not sentence_problems(s, evidence)]
    if not body or summary_problems(' '.join(body), headline, cited):
        headline, text = extractive_fallback(cited)
        body = sentences(text)
    if not useful_summary(headline, body):
        body = added_sentences(cited, headline) or body
    return headline, body[:4]
