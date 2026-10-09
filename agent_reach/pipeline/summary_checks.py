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
        r'announces|announced|reveals|revealed|claims|claimed|launches|launched)\b', sentence, re.I))


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


def validate_summary(text: str, headline: str, sources: list[tuple[str, str | None]]) -> list[str]:
    """All sentence quantities/entities must be supported together by one source sentence.

    This is a conservative text gate, not semantic proof. Unverifiable paraphrases fall back to extraction.
    """
    from agent_reach.daily.brief import CAP_WORD_RX, STARTERS, COMMON_OPENERS
    from agent_reach.pipeline.cleaner import STOPWORDS
    evidence = [s for title, excerpt in sources for part in (title, excerpt or '') for s in sentences(part)]
    body = sentences(text)
    errors = []
    if not body:
        errors.append('empty summary')
    for sentence in body:
        if _subjectless(sentence):
            errors.append('sentence has no subject')
        if not any(_anchored(sentence, source) for source in evidence):
            errors.append('number or named entity lacks cited sentence context')
    summary_words = _words(text)
    group_nouns = COMMON_OPENERS | {'crew', 'astronauts', 'cosmonauts'}
    names = {w.lower().strip(".'") for w in CAP_WORD_RX.findall(headline)
             if w.lower() not in STOPWORDS | STARTERS | group_nouns}
    # Conservative entity candidates must also occur in cited titles or prose, including feeds with no excerpt.
    prose = ' '.join(title + ' ' + (excerpt or '') for title, excerpt in sources)
    entities = {name for name in names if re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', prose, re.I)}
    if not _words(' '.join(entities)) <= summary_words:
        errors.append('headline key entity missing from summary')
    # Also require the headline's event/action, not only a shared actor (Misnames vs terrorist claim).
    actions = {'misnames', 'misnamed', 'names', 'named', 'launches', 'launch', 'wins', 'win', 'strikes', 'strike',
               'arrests', 'arrest', 'suspends', 'suspend', 'resigns', 'resign', 'teaches', 'teach'}
    headline_actions = {w.removesuffix('s') for w in re.findall(r'[a-z]+', headline.lower()) if w in actions}
    if headline_actions and not headline_actions & summary_words:
        errors.append('headline action disagrees with summary')
    return list(dict.fromkeys(errors))


def extractive_fallback(sources: list[tuple[str, str | None]]) -> tuple[str, str]:
    """Best source (caller order) title plus a complete extractive first sentence when available."""
    for title, excerpt in sources:
        title = repair_text(title)
        if not title:
            continue
        first = next((s for s in sentences(excerpt or '')
                      if not _subjectless(s) and not s.endswith(('...', '…'))), '')
        return title, title.rstrip('.!?') + '.' + (' ' + first if first and first.lower().rstrip('.!?') != title.lower().rstrip('.!?') else '')
    return '', ''


def verified_story(story) -> tuple[str, list[str]]:
    from agent_reach.daily.strength import SIGNAL_SOURCES
    from agent_reach.pipeline.clusterer import is_roundup
    cited = [(ev.title, ev.excerpt) for ev in story.evidence
             if ev.source not in SIGNAL_SOURCES and not is_roundup(ev.title)]
    if not cited:
        cited = [(ev.title, ev.excerpt) for ev in story.evidence]
    text = repair_text(' '.join(story.sentences))
    headline = repair_text(story.headline)
    if validate_summary(text, headline, cited):
        headline, text = extractive_fallback(cited)
    return headline, sentences(text)[:4]
