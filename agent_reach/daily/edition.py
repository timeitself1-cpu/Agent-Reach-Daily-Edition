"""DailyEdition: the versioned presentation wrapper around one valid PipelineReport.

The pipeline's ``PipelineReport`` (schema_version 3) and ``CategoryEnum`` are unchanged; this
module adds a separate, versioned document (``edition_schema_version``) that the GUI and the
HTML export both render. An edition carries:

* ``edition_date`` = Central calendar date of the refresh START (consistent across midnight)
* generation start/completion in UTC, revision history for same-date replacements
* source health, coverage indicators and warnings, configuration fingerprint, model identity
* ranked stories with their evidence: item IDs, URLs, excerpts, publication time ONLY when the
  source stated one (``published_at_utc``), and the retrieval time

Story membership comes straight from the validated clusters; nothing here regroups items.
Momentum labels are derived only from the scorer's momentum/basis: a first run is BASELINE
(no trend label), and missing history is never shown as flat growth.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_reach.daily.prefs import GENERAL_NEWS_SOURCES, TECH_SOURCES, DailyPrefs
from agent_reach.daily.timeutil import CENTRAL_TZ_NAME, central_date, parse_utc
from agent_reach.daily.changes import EditionChanges
from agent_reach.daily.strength import EvidenceStrength, assess, strength_of
from agent_reach.pipeline.cleaner import MONTH_DAY_GUARD, significant_tokens
from agent_reach.models import PUBLISHED_FUTURE_TOLERANCE, CategoryEnum, CleanedTrendItem, MacroCluster, PipelineReport, RawTrendItem

EDITION_SCHEMA = "agent_reach.daily_edition"
EDITION_SCHEMA_VERSION = 1
MAX_EVIDENCE_PER_STORY = 8
EXCERPT_CHARS = 320

SOURCE_NAMES = {
    "x_trends24": "X (trends24)", "reddit": "Reddit", "tiktok": "TikTok", "google_trends": "Google Trends",
    "google_news": "Google News", "wikipedia": "Wikipedia", "arxiv": "arXiv", "hackernews": "Hacker News",
    "github": "GitHub", "producthunt": "Product Hunt", "news_rss": "News feeds", "youtube": "YouTube",
    "mastodon": "Mastodon", "bluesky": "Bluesky",
}
MOMENTUM_LABELS = {"SURGING": "Hot", "RISING": "Rising", "NEW": "New", "STEADY": "Continuing",
                   "COOLING": "Cooling", "FADING": "Fading"}
#: Platforms whose items come from a named publisher (an article or a channel's video), not a trend list or
#: social post.
PUBLISHER_PLATFORMS = frozenset({"news_rss", "google_news", "hackernews", "arxiv", "youtube", "mastodon"})
#: A lone trend/social signal with no publisher article is kept only when the model rates it this relevant.
STRONG_RELEVANCE = 7
META_SENTENCE_RX = re.compile(
    r"^(?:signals were observed on .*|.* (?:is|are) carrying \d+ related signals? about .*|"
    r".* is drawing attention across trend sources\.?)$",
    re.IGNORECASE,
)
#: A sentence ends at . ! ? (also when a closing quote follows), never after a title such as 'St.' or 'Dr.'.
SENTENCE_SPLIT_RX = re.compile(
    r"(?:(?<=[.!?])|(?<=[.!?][\"'\u2019\u201d]))" + MONTH_DAY_GUARD +
    r"(?<!\bSt\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bDr\.)(?<!\bJr\.)(?<!\bSr\.)(?<!\bMrs\.)(?<!\bGen\.)"
    r"(?<!\bSen\.)(?<!\bRep\.)(?<!\bGov\.)(?<!\bvs\.)(?<!\bU\.S\.)(?<!\bU\.K\.)(?<!\bU\.N\.)(?<!\bE\.U\.)(?<!\bNo\.)"
    r"(?<!\bBros\.)(?<!\bInc\.)(?<!\bCorp\.)(?<!\bCo\.)(?<!\bLtd\.)(?<!\bP\.T\.)"
    r"(?<![\s(\"][A-Z]\.)"  # a middle initial: 'Biologist James D. Watson' (a real edition, October 7)
    r"\s+(?=[A-Z0-9\"'(\u2018\u201c])"
)
#: Sentences that say nothing about what happened (seen in real editions): dropped from summaries.
WEAK_SENTENCE_RX = re.compile(
    r"\b(?:drawing|draws|drew|sparking|sparks|sparked|attracting|attracts|garnering|gaining|generating)\s+"
    r"(?:significant\s+|widespread\s+|much\s+|a lot of\s+|considerable\s+)?(?:attention|interest|buzz|discussion)\b"
    r"|^(?:this|these|the (?:news|move|update|development|story|incident|announcement|event|report))\s+"
    r"(?:showcases|highlights|underscores|demonstrates|illustrates|reflects|signals|marks|shows|is notable|has sparked)\b"
    r"|\b(?:demonstrates|shows|reflects|underscores) (?:the|its|their) (?:company's |firm's )?(?:commitment|dedication)\b"
    r"|\bis notable because\b|\bin various (?:scientific )?(?:journals|outlets|publications|media)\b"
    r"|\bdue to the (?:controversy|tragedy|high-profile nature|unexpected nature|lighthearted|humorous)\b"
    r"|\bthis (?:trend|development) is\b|\b(?:is|are) a (?:growing|major|serious) concern\b"
    # about the article, not the news ('The author provides their NFL Week 5 picks and score predictions')
    r"|^(?:the|this) (?:author|writer|article|piece|post|columnist|reporter) (?:provides|offers|shares|gives|"
    r"discusses|explains|looks at|breaks down|lists|reviews)\b",
    re.IGNORECASE,
)


def plural(n: int, one: str, many: str) -> str:
    """'1 story was', '3 stories were'."""
    return f"{n} {one if n == 1 else many}"


def source_name(source: str) -> str:
    return SOURCE_NAMES.get(source, source)


# ====================================================================== schema
class EvidenceLink(BaseModel):
    item_id: int
    source: str
    source_name: str
    title: str
    url: str | None = None
    publisher: str | None = None
    excerpt: str | None = None
    context_source: str | None = None
    published_at_utc: datetime | None = Field(default=None, description="only when the source stated a publication time")
    retrieved_at_utc: datetime | None = None
    feed: str | None = None  # publisher feed URL for news_rss items

    @model_validator(mode="after")
    def _normalise_times(self) -> "EvidenceLink":
        """UTC everywhere; a publication time after the retrieval time is not trustworthy."""
        for name in ("published_at_utc", "retrieved_at_utc"):
            value = getattr(self, name)
            if value is not None:
                value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
                object.__setattr__(self, name, value.astimezone(timezone.utc))
        if (self.published_at_utc is not None and self.retrieved_at_utc is not None
                and self.published_at_utc > self.retrieved_at_utc + PUBLISHED_FUTURE_TOLERANCE):
            object.__setattr__(self, "published_at_utc", None)
        return self


class Story(BaseModel):
    rank: int = Field(ge=1)
    story_id: str = Field(description="evidence fingerprint (event_id); can change when evidence changes")
    entity_id: str = ""
    headline: str
    category: CategoryEnum
    sentences: list[str] = Field(min_length=1, max_length=4)
    why_it_matters: str | None = None
    labels: list[str] = Field(default_factory=list)
    momentum: str
    velocity_basis: str
    momentum_note: str = ""
    relevance_score: int
    velocity_score: float
    combined_score: float
    platforms: list[str]
    publisher_hosts: list[str] = Field(default_factory=list)
    raw_item_count: int = Field(ge=1)
    member_item_ids: list[int] = Field(min_length=1)
    evidence: list[EvidenceLink] = Field(min_length=1)
    tech_only: bool = False
    entities: list[str] = Field(default_factory=list)  # key names (people, places, organisations); may be empty
    evidence_strength: EvidenceStrength | None = None  # deterministic; None in editions written before it existed

    @field_validator("labels")
    @classmethod
    def _no_uncertain_label(cls, v: list[str]) -> list[str]:
        """Editions before 1.0.0rc10 put 'Uncertain trend' on every card; it is no longer shown."""
        return [label for label in v if label != "Uncertain trend"]


class FeedHealth(BaseModel):
    """One publisher feed inside a channel: did it answer, how much it gave, how much was cited."""

    name: str
    url: str
    category: str | None = None
    status: Literal["ok", "empty", "failed"]
    collected: int = 0
    used: int = 0
    error: str | None = None


class SourceHealth(BaseModel):
    source: str
    name: str
    status: Literal["ok", "partial", "empty", "failed"]
    item_count: int = 0
    latency_ms: int = 0
    error: str | None = None
    used: int = 0  # articles from this channel cited in the edition
    feeds: list[FeedHealth] = Field(default_factory=list)


class Coverage(BaseModel):
    sources_attempted: int = 0
    sources_ok: int = 0
    failed: list[str] = Field(default_factory=list)
    partial: list[str] = Field(default_factory=list)
    category_counts: dict[str, int] = Field(default_factory=dict)
    general_news_available: bool = False
    tech_only_stories: int = 0
    held_back_for_balance: int = 0
    balanced: bool = False
    warnings: list[str] = Field(default_factory=list)


def grouping_summary(semantic: dict) -> dict:
    """The few numbers a reader can use to judge how stories were grouped (the full pair log stays in the
    diagnostics folder): which embedding model grouped them, why another was not used, and how many
    candidate pairs the identity check accepted or refused."""
    if not semantic:
        return {}
    gate = semantic.get("gate") or {}
    emb = semantic.get("embedding") or {}
    return {"model_used": semantic.get("model_used", ""), "fallback": semantic.get("fallback", ""),
            "dims": emb.get("dims") or None, "cache_hits": emb.get("cache_hits", 0), "reports": emb.get("items", 0),
            "candidate_pairs": gate.get("candidate_pairs", 0), "accepted_pairs": gate.get("accepted_pairs", 0),
            "refused_pairs": gate.get("rejected_pairs", 0), "roundups": semantic.get("roundups_in_run", 0),
            "merges_blocked": gate.get("merges_blocked_conflict", 0) + gate.get("merges_blocked_cohesion", 0)}


class ModelInfo(BaseModel):
    llm_model: str
    embed_model: str  # the model the settings asked for
    pipeline_mode: str
    embed_model_used: str = ""  # the model that actually grouped the stories ("" in editions before rc12)
    grouping: dict = Field(default_factory=dict)  # compact semantic diagnostics (``grouping_summary``)
    summaries: Literal["local_model", "extractive"]
    label_calls: int = 0  # model labelling batches; failed ones used the reports' own titles
    label_calls_failed: int = 0
    brief_calls: int = 0  # 'why it matters' batches; failed ones added nothing
    brief_calls_failed: int = 0

    @property
    def model_stopped(self) -> bool:
        """The model answered at first and then stopped (or never answered the labelling calls)."""
        return bool(self.label_calls_failed or self.brief_calls_failed) or "unreachable" in self.pipeline_mode


#: Labelling batches that may fall back to the reports' own titles before the edition counts as extractive.
MAX_LABEL_FALLBACK_SHARE = 0.5


class AccountingSummary(BaseModel):
    ingested: int
    passed_filters: int
    clustering_candidates: int
    clustered: int
    discarded_total: int
    balanced: bool


class Revision(BaseModel):
    revision: int
    run_id: str
    generation_completed_utc: datetime


class DailyEdition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    edition_schema: Literal["agent_reach.daily_edition"] = EDITION_SCHEMA
    edition_schema_version: int = EDITION_SCHEMA_VERSION
    demo: bool = False
    edition_date: date
    timezone: Literal["America/Chicago"] = CENTRAL_TZ_NAME
    revision: int = Field(default=1, ge=1)
    previous_revisions: list[Revision] = Field(default_factory=list)
    run_id: str
    trigger: str = "manual"
    generation_started_utc: datetime
    generation_completed_utc: datetime
    model: ModelInfo
    config_fingerprint: str
    pipeline_schema_version: int
    accounting: AccountingSummary
    source_health: list[SourceHealth]
    coverage: Coverage
    overview: str
    notes: list[str] = Field(default_factory=list)
    stories: list[Story]
    top_ranks: list[int] = Field(default_factory=list)  # Top Stories (ranks into stories); empty in older editions
    changes: EditionChanges | None = None  # vs. the previously persisted edition; None for the first edition

    @model_validator(mode="after")
    def _consistency(self) -> "DailyEdition":
        if self.edition_schema_version != EDITION_SCHEMA_VERSION:
            raise ValueError(f"unsupported edition schema version {self.edition_schema_version}")
        for name in ("generation_started_utc", "generation_completed_utc"):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.generation_completed_utc < self.generation_started_utc:
            raise ValueError("generation completed before it started")
        if not self.demo and central_date(self.generation_started_utc) != self.edition_date:
            raise ValueError("edition_date must be the Central date of the refresh start")
        if [s.rank for s in self.stories] != list(range(1, len(self.stories) + 1)):
            raise ValueError("story ranks must be 1..n")
        if not self.accounting.balanced:
            raise ValueError("an edition requires a balanced item ledger")
        if len(set(self.top_ranks)) != len(self.top_ranks) or any(not 1 <= r <= len(self.stories) for r in self.top_ranks):
            raise ValueError("top_ranks must be distinct story ranks")
        # Ordering against generation time: evidence cannot be published (or retrieved) after the
        # edition was generated. Such times are dropped rather than rejecting the whole edition, so a
        # cached edition written before this check still loads, without the impossible date.
        latest = self.generation_completed_utc.astimezone(timezone.utc) + PUBLISHED_FUTURE_TOLERANCE
        for story in self.stories:
            for e in story.evidence:
                if e.published_at_utc is not None and e.published_at_utc > latest:
                    object.__setattr__(e, "published_at_utc", None)
                if e.retrieved_at_utc is not None and e.retrieved_at_utc > latest:
                    object.__setattr__(e, "retrieved_at_utc", None)
        return self


# ====================================================================== building
def tech_only(cluster: MacroCluster) -> bool:
    return bool(cluster.sources) and set(cluster.sources) <= TECH_SOURCES


def momentum_uncertain(story_or_cluster) -> bool:
    return story_or_cluster.velocity_basis == "coverage_uncertain" or story_or_cluster.momentum == "UNCERTAIN"


def story_labels(cluster: MacroCluster) -> list[str]:
    """Trend labels only when the scorer had comparable history; BASELINE gets none. An uncertain
    trend gets no label either (said once in the edition's notes, not on every card)."""
    if cluster.momentum_uncertain or momentum_uncertain(cluster):
        return []
    if cluster.velocity_basis != "historical":
        return []
    label = MOMENTUM_LABELS.get(cluster.momentum)
    return [label] if label else []


def repeats(sentence: str, earlier: list[str], share: float = 0.6) -> bool:
    """True when most of a sentence's meaningful words were already said."""
    from agent_reach.pipeline.cleaner import dedupe_key, significant_tokens

    toks = significant_tokens(dedupe_key(sentence))
    if not toks:
        return True
    return any(len(toks & significant_tokens(dedupe_key(e))) >= share * len(toks) for e in earlier)


#: Common English function words: an English sentence of five or more words contains at least one.
ENGLISH_WORDS = frozenset("""the a an of to in on at for with by from and or but is are was were be been has have
had will would can could it its this that these those as after before over than not he she they his her their
who which said says new into about up out more""".split())
#: Attribution prefixes some feeds put in front of a headline ('Sources: Etched is in talks...').
LEAD_PREFIX_RX = re.compile(r"^(?:sources?|report|reports|exclusive|breaking|update|updated|watch|live)\s*:\s+",
                            re.IGNORECASE)
#: A sentence is shown only when at least this share of its content words appear in its sources.
SUPPORT_SHARE = 0.6


#: Function words of the other languages feeds most often carry (Danish, Norwegian, Swedish, German,
#: Dutch, Spanish, French, Portuguese). Name particles ('de', 'van', 'der', 'la') are left out.
FOREIGN_WORDS = frozenset("""og til af er ikke har med som det och att inte och und ist nicht mit auf eine
einer wird sind auch het een niet zijn voor ook wordt los las que para una est les des une pour dans sur pas qui
avec uma com nao""".split())


def looks_english(sentence: str) -> bool:
    """False for text in another language ('Det Centrale Personregister har konstateret en alvorlig
    sikkerhedshaendelse'): foreign function words outnumber English ones, or there are no English
    ones at all in five or more words."""
    words = re.findall(r"[a-z']+", sentence.lower())
    english = sum(1 for w in words if w in ENGLISH_WORDS)
    foreign = sum(1 for w in words if w in FOREIGN_WORDS)
    if foreign >= 2 and foreign > english:
        return False
    return not (foreign and not english and len(words) >= 5)


#: Linking words that carry no claim of their own (not in the pipeline's stopword list).
LINKING_WORDS = frozenset("while also still just being during until since whose there here very such even".split())


def _content_words(text: str) -> list[str]:
    from agent_reach.pipeline.cleaner import STOPWORDS, tokens

    return [t for t in tokens(text)
            if (len(t) >= 3 and t not in STOPWORDS and t not in LINKING_WORDS) or any(c.isdigit() for c in t)]


def _stem(word: str, n: int = 5) -> str:
    return word[:n] if word.isalpha() else word


def source_stems(text: str) -> set[str]:
    return {_stem(t) for t in _content_words(text)}


def support(sentence: str, stems: set[str]) -> float:
    """Share of a sentence's content words (stemmed) that its sources also use."""
    words = _content_words(sentence)
    if not words:
        return 1.0
    return sum(1 for w in words if _stem(w) in stems) / len(words)


def restates(sentence: str, earlier: list[str], share: float = 0.6) -> bool:
    """Like ``repeats`` but tolerant of word forms ('moved' ~ 'move', 'Iranian' ~ 'Iran')."""
    toks = {_stem(t, 4) for t in _content_words(sentence)}
    if not toks:
        return True
    said = {_stem(t, 4) for e in earlier for t in _content_words(e)}
    return len(toks & said) >= share * len(toks)


#: A sentence whose content words are mostly (this share) already said by the sentences before it adds
#: nothing ('Clayton will coordinate government engagement with AI. The new AI task force will coordinate
#: government engagement with AI.').
NOVEL_SHARE = 0.7
NUMBER_RX = re.compile(r"\d+(?:[.,]\d+)*")


def numbers_in(text: str) -> set[str]:
    """'1,000', '23', '1.4' -> {'1000', '23', '1.4'}."""
    return {n.replace(",", "").rstrip(".") for n in NUMBER_RX.findall(text or "")}


_ANCHOR_TOKEN_RX = re.compile(r"\d+(?:[.,]\d+)*|[A-Za-z][A-Za-z'-]*")
#: Words between a number and what it counts ('67 million articles', '$18M', '73 percent').
_SCALE_WORDS = frozenset("m bn b k tn mn s million billion trillion thousand hundred percent per cent gbp eur jpy usd"
                         .split())
_MONTHS = frozenset("""jan feb mar apr may jun jul aug sep sept oct nov dec january february march april june july
august september october november december""".split())
#: Numbers that label rather than count ('Week 5', 'Game 2', 'No. 1').
_LABEL_WORDS = frozenset("""week weeks game day round stage series chapter season episode part no number vol level grade
phase gen""".split())


def _anchor_tokens(text: str) -> list[str]:
    return [t.lower() for t in _ANCHOR_TOKEN_RX.findall(text)]


def _anchor_word(token: str) -> bool:
    from agent_reach.pipeline.cleaner import STOPWORDS

    t = token.strip("-'")
    return (len(t) >= 3 and t.replace("-", "").replace("'", "").isalpha() and t not in STOPWORDS
            and t not in _SCALE_WORDS)


def _anchor_stems(words: list[str]) -> set[str]:
    return {p[:4] for w in words for p in w.split("-") if len(p) >= 3}


def _around(tokens_: list[str], i: int, window: int) -> tuple[list[str], list[str]]:
    return ([t for t in tokens_[max(0, i - window):i] if _anchor_word(t)],
            [t for t in tokens_[i + 1:i + 1 + window] if _anchor_word(t)])


def numbers_anchored(sentence: str, source: str) -> bool:
    """Every number stands next to the same words as in the sources: a word just before it matches a
    word just before it there, or a word just after it matches one after it. 'Over 67 million Wikipedia
    hosts expose sensitive data' (the source: 'Wikipedia hosts over 67 million articles') and '23 billion
    weights' (the source: '23 billion active') attach a real number to the wrong thing. Years, dates and
    labels ('Week 5') are not checked; a number the sources lack is ``numbers_in``'s business."""
    st, so = _anchor_tokens(sentence), _anchor_tokens(source)
    paired = {x for pair in re.findall(r"(\d+)\s*[-–]\s*(\d+)", sentence) for x in pair}  # scores, ranges
    for i, t in enumerate(st):
        if not t[0].isdigit():
            continue
        n = t.replace(",", "")
        if (re.fullmatch(r"(?:19|20)\d\d", n) or n in paired
                or (i and st[i - 1] in _MONTHS | _LABEL_WORDS)):
            continue
        before, after = _around(st, i, 5)
        near_before: set[str] = set()
        near_after: set[str] = set()
        seen = False
        for j, u in enumerate(so):
            if u.replace(",", "") == n:
                seen = True
                b, a = _around(so, j, 6)
                near_before |= _anchor_stems(b)
                near_after |= _anchor_stems(a)
        if not seen or not after:  # a number that ends the sentence ('dies at 62') counts nothing
            continue
        if not (_anchor_stems(before[-2:]) & near_before or _anchor_stems(after[:2]) & near_after):
            return False
    return True


#: Quoted speech: a person quoted saying 'we' or 'you' is reporting, not the page talking to the reader.
QUOTED_RX = re.compile(r"\"[^\"]*\"|“[^”]*”|‘[^’]*’|(?<!\w)'[^']*'(?!\w)")
PAGE_VOICE_RX = re.compile(r"\b(?:you|your|yours|yourself|we|our|ours|ourselves)\b", re.IGNORECASE)
#: 'our own solar system', 'our galaxy': how science reports name the place everyone shares, not the page talking
#: to its reader (October 7 export, story #3: the Webb debris-disk lead was refused, so no fallback was left).
SHARED_PLACE_RX = re.compile(r"\bour\s+(?:own\s+)?(?:solar\s+system|galaxy|planet|moon|sun|universe|species|"
                             r"home\s+galaxy|cosmic\s+neighbou?rhood)\b", re.IGNORECASE)


def page_voice(sentence: str) -> bool:
    """True for text in the page's own voice outside quotes ('Every time you ask ChatGPT a question',
    'as our industry stepped into'): copied page text, not a summary. Lower-case 'us' counts; 'US' does not."""
    bare = SHARED_PLACE_RX.sub(" ", QUOTED_RX.sub(" ", sentence))
    return bool(PAGE_VOICE_RX.search(bare) or re.search(r"\bus\b", bare))


SUBORDINATE_OPENER_RX = re.compile(
    r"^(?:(?:over|in|during|for|after|within|throughout|across)\b[^,]{0,80},\s*)?"
    r"(?:as|while|when|whereas|although|though|because|since|unless)\b", re.IGNORECASE)
#: An introductory phrase with no main clause after it: 'By studying 21 rare.' (the export of October 7, story #3:
#: the model's summary was cut at a quotation mark), 'After the vote.', 'Following months of talks.'.
INTRO_ONLY_RX = re.compile(r"^(?:by|after|before|following|despite|amid|with|without|while|when|in order to|"
                           r"according to|thanks to|due to)\b[^,;:]*[.!?]?$", re.IGNORECASE)
IRREGULAR_PAST = frozenset("""won lost made took gave became began fell rose left met ran told found held kept led
paid put set sent sold spent struck saw came went got hit cut beat broke chose drew drove flew fled grew knew spoke
stole wore woke shut quit""".split())


def is_fragment(sentence: str) -> bool:
    """A subordinate clause with no main clause ('Over the past five years, as our industry stepped
    into this new era of short-form mega consumption, AI-pushing productivity platforms, and Hollywood
    nods.'): after the clause the opener starts, no comma-separated part has a verb."""
    from agent_reach.pipeline.cleaner import HEADLINE_VERBS

    m = SUBORDINATE_OPENER_RX.match(sentence)
    if not m:
        return False
    parts = sentence.rstrip(".!?").split(",")
    start = 1 if "," in m.group(0) else 0
    for part in parts[start + 1:]:
        for w in re.findall(r"[a-z']+", part.lower()):
            if w in HEADLINE_VERBS or w in IRREGULAR_PAST or (len(w) > 4 and w.endswith("ed")):
                return False
    return True


_WORDS_RX = re.compile(r"[a-z0-9]+(?:[.'-][a-z0-9]+)*")


def _four_grams(text: str) -> set[tuple[str, ...]]:
    words = _WORDS_RX.findall(text.lower())
    return {tuple(words[i:i + 4]) for i in range(len(words) - 3)}


def _repeats_itself(text: str) -> bool:
    words = _WORDS_RX.findall(text.lower())
    grams = [tuple(words[i:i + 4]) for i in range(len(words) - 3)]
    return len(grams) != len(set(grams))


#: Words a finished sentence never ends on ('Clayton will lead the government's new.').
DANGLING_END_WORDS = frozenset("""a an the and or but nor of to for with from by via vs its their his her our your
my this these those new""".split())


def truncated_copy(sentence: str, source: str | None) -> bool:
    """The sentence is a source sentence cut off just before a quotation mark: 'By studying 21 rare.' where the
    report says 'By studying 21 rare "extreme debris disks" around young stars, researchers found ...' (a model
    writing JSON ends its text at an unescaped double quote). Copying a whole clause is fine."""
    if not source:
        return False
    body = re.sub(r"[.!?]+$", "", sentence.strip()).strip()
    if len(body.split()) < 2:
        return False
    for m in re.finditer(re.escape(body), source, flags=re.IGNORECASE):
        rest = source[m.end():].lstrip()
        if rest[:1] in ('"', "\u201c", "\u201d") or rest[:2] == "''":
            return True
    return False


def ends_dangling(sentence: str) -> bool:
    """A sentence cut short: fewer than three words ('Gov.', 'Midterm elections.'), or it ends on an article,
    a preposition, a possessive or 'new'."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9']*", sentence)
    if sentence.rstrip().endswith(("...", "…")):  # a clipped excerpt ('in front of a fake...')
        return True
    return len(words) < 3 or words[-1].lower() in DANGLING_END_WORDS or words[-1].lower().endswith("'s")


def _runs(text: str, n: int = 5) -> set[tuple[str, ...]]:
    words = _WORDS_RX.findall(text.lower())
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def shares_run(a: str, b: str) -> bool:
    """The two texts say five words in a row the same."""
    return bool(_runs(a) & _runs(b))


def extends(sentence: str, earlier: str) -> bool:
    """``sentence`` says ``earlier`` word for word (80% of its four-word runs) and more."""
    grams = _four_grams(earlier)
    return bool(grams) and len(sentence) > len(earlier) and len(grams & _four_grams(sentence)) >= 0.8 * len(grams)


def place_sentence(sentences: list[str], new: str, keep_first: bool = False) -> bool:
    """Add ``new`` unless it repeats a five-word run of a sentence already there ('The Yankees committed
    four errors, including three in the first inning.' after 'The Yankees committed four errors in ...').
    When it contains that sentence and says more ('The Houthis claimed they struck Riyadh's airport.' ->
    '... airport, an oil refinery and military bases'), it replaces it instead (never the first sentence
    when ``keep_first``). Returns whether ``new`` was placed."""
    runs = _runs(new)
    for i, old in enumerate(sentences):
        if runs & _runs(old):
            if extends(new, old) and not (keep_first and i == 0):
                sentences[i] = new
                return True
            return False
    sentences.append(new)
    return True


def without_self_repeat(sentence: str) -> str | None:
    """'A team of Claude Opus 5.5 agents discovered two candidate magnets ..., found by a team of
    Claude Opus 5.5 agents.' -> the sentence without the clause that says it again. None when the
    repetition cannot be removed by dropping a clause."""
    if not _repeats_itself(sentence):
        return sentence
    parts = sentence.rstrip(".!?").split(", ")
    kept = [parts[0]]
    for part in parts[1:]:
        if not _four_grams(part) & _four_grams(", ".join(kept)):
            kept.append(part)
    end = sentence[-1] if sentence.endswith(("!", "?")) else "."
    out = ", ".join(kept) + end
    return None if _repeats_itself(out) else out


#: A sentence that opens with a pronoun, a connective or 'the move' needs the sentence before it ('It is an
#: open-weight model ...', 'But tracing their journey ...', 'The move aims to ...').
PRONOUN_START_RX = re.compile(r"^(?:he|she|they|it|his|her|their|its|but|and|yet|however|also)\b"
                              r"|^(?:the|that) (?:move|decision|step|deal|change)\b"
                              # 'This model is part of a new crop ...' (but 'This year's prize ...' stands alone)
                              r"|^(?:this|these) (?!year|week|month|morning|evening|weekend|season|summer|winter|"
                              r"spring|fall|autumn|time\b)\w+", re.IGNORECASE)


#: The model talking about its input instead of the news ('Meta's Muse is a privacy and security dumpster fire,
#: but the context is not specified.', 'NASA is bringing 7,500 contractors back ..., but the reason is not
#: specified.': a real edition of October 7). Reporters write 'not disclosed' or 'not known'; those are facts.
UNSTATED_RX = re.compile(
    r"(?:,?\s*(?:but|although|though|and|while|however,?)\s+)?(?:the\s+|its\s+|their\s+|any\s+)?"
    r"(?:exact\s+|specific\s+|further\s+|additional\s+|more\s+)?"
    r"(?:context|reasons?|details?|cause|specifics|motive|purpose|nature|information|outcome|explanation)\s+"
    r"(?:is|are|was|were|has|have|remains?)\s+(?:been\s+)?(?:not|un)\s*"
    r"(?:specified|mentioned|provided|given|stated|included|available)\b"
    r"(?:\s+(?:in|from|by)\s+the\s+(?:provided\s+|given\s+)?(?:text|sources?|evidence|articles?|excerpts?|reports?))?"
    r"(?=\s*[.!?]?\s*$)",  # only a remark that ends the sentence ('Details were not provided by police' is news)
    re.IGNORECASE)


def without_unstated(sentence: str, source: str | None) -> str:
    """The sentence without the model's remark that something is 'not specified' (unless the sources say it)."""
    m = UNSTATED_RX.search(sentence)
    if not m or (source and m.group(0).strip(" ,").lower() in source.lower()):
        return sentence
    out = (sentence[:m.start()] + sentence[m.end():]).strip()
    out = re.sub(r"\s+([.,;:!?])", r"\1", out).rstrip(" ,;:")
    if out and out[-1] not in ".!?":
        out += "."
    return out if len(out.split()) >= 3 else ""


def body_sentences(summary: str, source: str | None = None, headline: str | None = None) -> list[str]:
    """Up to two summary sentences, without meta lines, empty filler, repeats of what was already said,
    sentences that repeat themselves, non-English text, the page's own voice ('you', 'our'), verbless
    fragments, a sentence that only restates the ``headline`` ('The redesign is the biggest in decades.')
    or (when the sources are given) claims or numbers the sources do not support."""
    stems = source_stems(source) if source else None
    numbers = numbers_in(source) if source else None
    out: list[str] = []
    restated: list[str] = []  # sound sentences left out only because they restate the headline
    for s in (p.strip() for p in SENTENCE_SPLIT_RX.split(summary or "")):
        s = without_unstated(LEAD_PREFIX_RX.sub("", s), source)
        s = without_self_repeat(s[:1].upper() + s[1:]) if s else None
        if (s and not META_SENTENCE_RX.match(s) and not WEAK_SENTENCE_RX.search(s) and not repeats(s, out)
                and not (out and restates(s, out, NOVEL_SHARE)) and looks_english(s)
                and not page_voice(s) and not is_fragment(s) and not ends_dangling(s)
                and not INTRO_ONLY_RX.match(s) and not truncated_copy(s, source)
                and (stems is None or (support(s, stems) >= SUPPORT_SHARE and numbers_in(s) <= numbers
                                       and numbers_anchored(s, source or "")))):
            if headline and restates(s, [headline], 1.0):
                restated.append(s)
            else:
                place_sentence(out, s)
    # 'He was best known for playing Bo Brady' needs the sentence that says who he is; with none, a summary
    # does not open with it ('It is an open-weight model available through Reflection.')
    if out and restated and PRONOUN_START_RX.match(out[0]):
        out.insert(0, restated[0])
    while out and PRONOUN_START_RX.match(out[0]):
        out.pop(0)
    return out[:2]


def lead_sentence(cluster: MacroCluster, items: dict[int, CleanedTrendItem], headline: str = "") -> str | None:
    """The first sound sentence of what the reports themselves say, for a story whose model summary
    did not survive. Live blogs are never used; their pages cover many events."""
    from agent_reach.pipeline.cleaner import is_live_blog, is_roundup

    members = sorted((items[i] for i in cluster.member_item_ids if i in items),
                     key=lambda m: m.heuristic_score, reverse=True)
    for m in members:
        if is_roundup(m.normalized_title) or is_live_blog(m.context):
            continue
        for segment in reversed((m.context or "").split(" | ")):
            for s in SENTENCE_SPLIT_RX.split(segment.strip())[:3]:
                s = re.sub(r"\s+([.,;:!?])", r"\1", s.strip())  # page text: 'in August .'
                if (len(s) >= 40 and s.endswith((".", "!", "?")) and looks_english(s) and not page_voice(s)
                        and not is_fragment(s) and not ends_dangling(s) and not PRONOUN_START_RX.match(s)
                        and not (headline and restates(s, [headline], 1.0))):
                    return s
    return None


_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WEEKDAY_RX = re.compile(r"\b(" + "|".join(_WEEKDAYS) + r"|yesterday|today)\b", re.IGNORECASE)
DEVELOPING_LABEL = "Developing"


def stated_day(sentence: str, today: int) -> int | None:
    """The weekday (0 = Monday) a sentence says it is about, when it names exactly one ('yesterday' and
    'today' count relative to ``today``)."""
    days = set()
    for m in _WEEKDAY_RX.finditer(sentence):
        word = m.group(1).lower()
        days.add(today if word == "today" else (today - 1) % 7 if word == "yesterday" else _WEEKDAYS.index(word))
    return days.pop() if len(days) == 1 else None


def newest_state(sentences: list[str], cluster: MacroCluster, items: dict[int, CleanedTrendItem],
                 reference: datetime) -> str | None:
    """A source sentence about TODAY for a summary that only says what happened on an earlier day.

    The export of October 7 (a Wednesday), story #2 'Stock Markets Hit Record High Despite Inflation, High
    Fuel Prices': the summary said 'US stock markets hit a record high Tuesday', while the story's newest
    report said 'Stocks fell on Wednesday as pressure continued to build in the bond market'. The newest
    reliable evidence controls the current state: that sentence leads, the earlier one stays as what came
    before. Only page text of the story's own reports is used, newest stated publication first, with the
    same sentence checks as ``lead_sentence`` and at least two words in common with the story."""
    today = central_date(reference).weekday()
    days = [stated_day(x, today) for x in sentences]
    if not any(d is not None and (today - d) % 7 in (1, 2) for d in days) or today in days:
        return None
    topic = {t[:5] for t in significant_tokens(" ".join([cluster.headline, *sentences]))}
    epoch = datetime.min.replace(tzinfo=timezone.utc)

    def stated(m: CleanedTrendItem) -> datetime:  # newest publication time a source stated; unknown sorts last
        times = [parse_utc(o.metadata.get("published_at")) for o in [m, *m.observations]]
        return max((t for t in times if t is not None and t <= reference), default=epoch)

    members = sorted((items[i] for i in cluster.member_item_ids if i in items and items[i].context_source == "page"),
                     key=stated, reverse=True)
    for m in members:
        for segment in (m.context or "").split(" | "):
            for x in SENTENCE_SPLIT_RX.split(segment.strip()):
                x = re.sub(r"\s+([.,;:!?])", r"\1", x.strip())
                if (stated_day(x, today) == today and len(x) >= 40 and x.endswith((".", "!", "?"))
                        and looks_english(x) and not page_voice(x) and not is_fragment(x) and not ends_dangling(x)
                        and not PRONOUN_START_RX.match(x)
                        and len({t[:5] for t in significant_tokens(x)} & topic) >= 2):
                    return x
    return None


def member_text(cluster: MacroCluster, items: dict[int, CleanedTrendItem]) -> str:
    """Everything the pipeline read for a story: titles, page or feed context, descriptions."""
    parts: list[str] = []
    for i in cluster.member_item_ids:
        m = items.get(i)
        if m is None:
            continue
        parts += [m.normalized_title, m.title, m.context or "", m.description or ""]
        parts += [o.title for o in m.observations]
        parts += [str(t) for t in (m.metadata.get("news_titles") or [])[:5]]
    return " ".join(p for p in parts if p)


def _host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return None
    return host.removeprefix("www.") or None


def safe_url(url: str | None) -> str | None:
    """Only absolute http(s) URLs with a host are ever rendered as links."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return url.strip()


#: Hosts whose links are redirects, trend pages or social posts rather than the reporting itself.
NON_ARTICLE_HOSTS = ("news.google.com", "trends.google.com", "google.com", "bsky.app", "x.com", "twitter.com",
                     "reddit.com", "tiktok.com", "trends24.in", "news.ycombinator.com")


def primary_url(story: "Story") -> str | None:
    """The link a headline opens: the first cited publisher article, else the first safe link."""
    links = [safe_url(e.url) for e in story.evidence]
    for url in links:
        host = _host(url) or ""
        if url and not any(host == h or host.endswith("." + h) for h in NON_ARTICLE_HOSTS):
            return url
    return next((u for u in links if u), None)


def _clip(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-") + "..."


def evidence_links(cluster: MacroCluster, items: dict[int, CleanedTrendItem],
                   limit: int | None = MAX_EVIDENCE_PER_STORY) -> list[EvidenceLink]:
    members = [items[i] for i in cluster.member_item_ids if i in items]
    members.sort(key=lambda m: m.heuristic_score, reverse=True)
    links: list[EvidenceLink] = []
    seen: set[str] = set()
    for m in members:
        observations: list[RawTrendItem] = list(m.observations) or [m]
        for k, obs in enumerate(observations):
            url = safe_url(obs.url)
            key = url or f"{obs.source.value}|{obs.title.lower()}"
            if key in seen:
                continue
            seen.add(key)
            md = obs.metadata or {}
            links.append(EvidenceLink(
                item_id=m.item_id,
                source=obs.source.value,
                source_name=source_name(obs.source.value),
                title=_clip(obs.title, 300) or obs.title[:300],
                url=url,
                publisher=(str(md.get("publisher")) if md.get("publisher") else None) or _host(url),
                excerpt=_clip(m.context, EXCERPT_CHARS) if k == 0 else None,
                context_source=m.context_source if k == 0 else None,
                published_at_utc=parse_utc(md.get("published_at")),
                retrieved_at_utc=parse_utc(md.get("retrieved_at")),
                feed=str(md["feed"]) if md.get("feed") else None,
            ))
    links.sort(key=lambda link: link.url is None)  # linked evidence first, order otherwise preserved
    return links[:limit] if limit else links


def newest_published(story: Story) -> datetime | None:
    """Most recent publication time a source actually stated for this story (None if none did)."""
    times = [e.published_at_utc for e in story.evidence if e.published_at_utc is not None]
    return max(times) if times else None


def is_stale(story: Story, now: datetime, max_age_hours: float) -> bool:
    """True when every stated publication time is older than ``max_age_hours``.

    Stories without any stated publication time (trend lists, Wikipedia) are not stale by this
    rule; they are shown with "publication time not stated" instead of a fake age.
    """
    newest = newest_published(story)
    return newest is not None and (now - newest).total_seconds() > max_age_hours * 3600


def is_weak(story: Story) -> bool:
    """A single uncorroborated trend/social signal with no publisher article and modest relevance."""
    has_publisher = any(p in PUBLISHER_PLATFORMS for p in story.platforms)
    return story.raw_item_count <= 1 and not has_publisher and story.relevance_score < STRONG_RELEVANCE


def is_live_blog_only(story: Story) -> bool:
    """Every report is a live blog ('... - as it happened') or a newsletter digest ('First Thing: ...'):
    a running page of many events, not one story."""
    from agent_reach.pipeline.cleaner import is_live_blog, is_roundup

    return all(is_roundup(e.title) or is_live_blog(e.excerpt) for e in story.evidence)


def _topic_tokens(story: Story) -> set[str]:
    from agent_reach.pipeline.cleaner import dedupe_key, significant_tokens

    return significant_tokens(dedupe_key(story.headline))


def same_entities(a: Story, b: Story) -> bool:
    """The same entity set. The id hashes only the key names, so one shared name ('Donald Trump': a
    diesel order and a closed live blog) is not the same story; stories without stored key names
    (older editions, or an id made from the headline) keep the plain id comparison."""
    return bool(a.entity_id) and a.entity_id == b.entity_id and len(a.entities) != 1 and len(b.entities) != 1


def same_topic(a: Story, b: Story) -> bool:
    """Deterministic 'this is the same story again' test used to avoid repetitive editions."""
    if same_entities(a, b):
        return True
    urls_a = {e.url for e in a.evidence if e.url}
    if urls_a & {e.url for e in b.evidence if e.url}:
        return True
    ta, tb = _topic_tokens(a), _topic_tokens(b)
    shared = ta & tb
    return len(shared) >= 2 and len(shared) / max(1, min(len(ta), len(tb))) >= 0.6


#: First-person columns ('How I made a paid Mac app ...'): kept, but below the news and out of Top Stories.
FIRST_PERSON_RX = re.compile(
    r"^(?:how|why|what|when) i\b|^i(?:'m|'ve|'d| am| was| have| tried| made| built| used| tested| spent| switched|"
    r" quit| asked| bought| love| hate)\b|^my\b|\bhere'?s (?:how|why) i\b",
    re.IGNORECASE,
)
#: A story told only through video clips (highlights, reactions, recaps) is not a report.
CLIP_TITLE_RX = re.compile(r"\b(?:highlights|full game|full match|full episode|reaction|recap|live ?stream)\b",
                           re.IGNORECASE)
FILLER_TITLE_RX = re.compile(r"\b(?:trailers?|podcasts?|mock drafts?|first take|debate show|explainer|explained|"
                             r"breaks? down a play|video essay|uncanny valley)\b", re.I)


def qualifies(story: Story, now: datetime) -> bool:
    strength = strength_of(story, now)
    if strength.independent_reports >= 2:
        return True
    if any(FILLER_TITLE_RX.search(title) for title in [story.headline, *(e.title for e in story.evidence)]):
        return False
    news_type = any(e.source in {'news_rss', 'google_news'} for e in story.evidence)
    strong_signal = story.relevance_score >= 9 and story.raw_item_count >= 3
    return news_type or strong_signal
#: A category may place this many stories beyond ``max_per_category`` in Top Stories when they are strong.
STRONG_EXTRA_PER_CATEGORY = 2


def is_secondary(story: Story) -> bool:
    """A first-person column, or a story whose every report is a video clip: below the news, never on top."""
    titles = [e.title for e in story.evidence] or [story.headline]
    if FIRST_PERSON_RX.search(story.headline) or sum(bool(FIRST_PERSON_RX.search(t)) for t in titles) * 2 > len(titles):
        return True
    return all(e.source == "youtube" and CLIP_TITLE_RX.search(e.title) for e in story.evidence)


#: Among single-outlet stories, those this relevant reach Top Stories first (after all corroborated news).
TOP_SINGLE_SOURCE_RELEVANCE = 9


def is_corroborated(story: Story) -> bool:
    """More than one independent report (or no strength assessment, as in older editions)."""
    return story.evidence_strength is None or story.evidence_strength.level != "limited"


def is_strong(story: Story) -> bool:
    """Important and corroborated: may go beyond the per-category cap of Top Stories."""
    return story.relevance_score >= 8 and is_corroborated(story)


@dataclass
class Selection:
    stories: list[Story]
    top: list[Story] = field(default_factory=list)  # Top Stories, in rank order
    held_back: int = 0  # beyond the per-category section size
    filled_from_held_back: int = 0
    dropped_unsupported: int = 0
    dropped_stale: int = 0
    dropped_weak: int = 0
    dropped_live_blog: int = 0
    dropped_duplicate: int = 0
    secondary: int = 0  # first-person columns and clip-only stories moved below the news
    notes: list[str] = field(default_factory=list)


def select_stories(stories: list[Story], prefs: DailyPrefs, *, now: datetime) -> Selection:
    """Choose the edition from stories in pipeline rank order: sections of ``max_stories``.

    1. Drop stale stories (every stated publication time older than ``max_story_age_hours``),
       weak single uncorroborated trend signals, stories told only by live blogs, and repeats of a
       story already chosen.
    2. Each category keeps its top ``max_stories`` (10) stories, corroborated ones first.
    3. Top Stories are the ``max_stories`` best of those, with at most ``max_per_category`` from one
       category (a strong story - relevance 8+ and corroborated - may exceed it by
       ``STRONG_EXTRA_PER_CATEGORY``) and at most ``max_tech_only_share`` tech-only stories, so the
       top of the edition stays broad. Corroborated stories (more than one independent report) are
       chosen first, in pipeline rank order; then corroborated stories beyond the category cap; then
       single-outlet stories (those the model rated 9+ first). If the caps leave slots empty, the next
       best stories fill them.
    4. Inside every section corroborated stories come before single-outlet ones. First-person
       columns and clip-only stories follow the news and never enter Top Stories.
    """
    sel = Selection(stories=[])
    candidates: list[Story] = []
    for s in stories:
        if is_stale(s, now, prefs.max_story_age_hours):
            sel.dropped_stale += 1
        elif is_weak(s):
            sel.dropped_weak += 1
        elif not qualifies(s, now):
            sel.dropped_weak += 1
        elif is_live_blog_only(s):
            sel.dropped_live_blog += 1
        elif any(same_topic(s, c) for c in candidates):
            sel.dropped_duplicate += 1
        else:
            candidates.append(s)
    pipeline_order = {id(s): i for i, s in enumerate(candidates)}
    secondary = {id(s) for s in candidates if is_secondary(s)}
    sel.secondary = len(secondary)
    news = [s for s in candidates if id(s) not in secondary]
    candidates = ([s for s in news if is_corroborated(s)] + [s for s in news if not is_corroborated(s)]
                  + [s for s in candidates if id(s) in secondary])

    per_section = prefs.max_stories
    per_cat: Counter[str] = Counter()
    chosen: list[Story] = []
    for s in candidates:
        if per_cat[s.category.value] < per_section:
            chosen.append(s)
            per_cat[s.category.value] += 1
        else:
            sel.held_back += 1

    # Once there is a useful body of corroborated news, keep single-outlet items below half the edition.
    # A short section is preferable to padding. On an unusually sparse day, eligible news can still publish.
    corroborated = sum(strength_of(s, now).independent_reports >= 2 for s in chosen)
    if corroborated >= prefs.min_useful_stories:
        singles = sorted((s for s in chosen if strength_of(s, now).independent_reports < 2),
                         key=lambda s: (s.relevance_score, s.combined_score), reverse=True)
        permitted = {id(s) for s in singles[:corroborated - 1]}
        sel.held_back += len(singles) - len(permitted)
        chosen = [s for s in chosen if strength_of(s, now).independent_reports >= 2 or id(s) in permitted]

    tech_cap = per_section if prefs.max_tech_only_share >= 1 else int(per_section * prefs.max_tech_only_share)
    top: list[Story] = []
    in_top: set[int] = set()
    top_cat: Counter[str] = Counter()
    tech = 0
    ranked = sorted(chosen, key=lambda s: pipeline_order[id(s)])
    # 1. corroborated news within the category caps;
    # 2. corroborated news beyond the caps: news several outlets report never waits for a single outlet
    #    (a 1-report story the model rated 9 took a place while a 5-report story waited, October 6);
    # 3. single-outlet stories within the caps, those rated 9+ first
    stages = ((is_corroborated, True),
              (is_corroborated, False),
              (lambda s: s.relevance_score >= TOP_SINGLE_SOURCE_RELEVANCE, True),
              (lambda s: True, True))
    for wanted, capped in stages:
        for s in ranked:
            if len(top) >= per_section:
                break
            if id(s) in secondary or id(s) in in_top or not wanted(s):
                continue
            room = prefs.max_per_category + (STRONG_EXTRA_PER_CATEGORY if is_strong(s) else 0)
            if (capped and top_cat[s.category.value] >= room) or (s.tech_only and tech >= tech_cap):
                continue
            sel.filled_from_held_back += top_cat[s.category.value] >= room  # beyond its category's cap
            top.append(s)
            in_top.add(id(s))
            top_cat[s.category.value] += 1
            tech += s.tech_only
    for s in ranked:  # caps left slots empty: the next best real stories fill them
        if len(top) >= per_section:
            break
        if id(s) not in in_top and id(s) not in secondary:
            top.append(s)
            in_top.add(id(s))
            sel.filled_from_held_back += 1
    order = {id(s): i for i, s in enumerate(chosen)}
    sel.stories = chosen
    sel.top = sorted(top, key=lambda s: order[id(s)])
    return sel


def top_stories(edition: "DailyEdition") -> list[Story]:
    """Top Stories in rank order (older editions without sections: their first ten stories)."""
    if edition.top_ranks:
        by_rank = {s.rank: s for s in edition.stories}
        return [by_rank[r] for r in edition.top_ranks if r in by_rank]
    return list(edition.stories[:10])


#: Reading order of the category sections (any category not listed follows in enum order).
SECTION_ORDER = ["News", "Local", "Tech", "Science & AI", "Sports", "Entertainment", "Internet Culture"]


def section_order() -> list[str]:
    return SECTION_ORDER + [c for c in CategoryEnum.values() if c not in SECTION_ORDER]


def category_sections(edition: "DailyEdition") -> list[tuple[str, list[Story]]]:
    """[(category, stories in rank order)] for every category that has stories, in reading order."""
    out = []
    for cat in section_order():
        stories = [s for s in edition.stories if s.category.value == cat]
        if stories:
            out.append((cat, stories))
    return out


def build_story(rank: int, cluster: MacroCluster, items: dict[int, CleanedTrendItem],
                reference: datetime | None = None) -> Story | None:
    """None when the cluster has no factual sentence or no evidence to cite."""
    source = member_text(cluster, items)
    sentences = body_sentences(cluster.summary, source or None, cluster.headline)
    all_evidence = evidence_links(cluster, items, limit=None)
    evidence = all_evidence[:MAX_EVIDENCE_PER_STORY]
    if not sentences:
        lead = lead_sentence(cluster, items, cluster.headline)
        # a summary that only restates the headline is still better than no story at all
        sentences = [lead] if lead else body_sentences(cluster.summary, source or None)
    if not sentences or not evidence:
        return None
    labels = story_labels(cluster)
    latest = newest_state(sentences, cluster, items, reference or datetime.now(timezone.utc))
    if latest:
        sentences = [latest, *sentences[:3]]
        labels.append(DEVELOPING_LABEL)
    return Story(
        rank=rank,
        story_id=cluster.event_id or cluster.cluster_id,
        entity_id=cluster.entity_id,
        headline=cluster.headline,
        category=cluster.category,
        sentences=sentences,
        labels=labels,
        momentum=cluster.momentum,
        velocity_basis=cluster.velocity_basis,
        momentum_note=cluster.momentum_note,
        relevance_score=cluster.relevance_score,
        velocity_score=cluster.velocity_score,
        combined_score=cluster.combined_score,
        platforms=list(cluster.sources),
        publisher_hosts=list(cluster.publisher_hosts),
        raw_item_count=cluster.raw_item_count,
        member_item_ids=list(cluster.member_item_ids),
        evidence=evidence,
        evidence_strength=assess(all_evidence, reference or datetime.now(timezone.utc)),
        tech_only=tech_only(cluster),
        entities=list(cluster.primary_entities)[:6],
    )


HEALTH_WORDS = {"ok": "healthy", "partial": "partial", "empty": "empty", "failed": "failed"}
_STATUS_RX = re.compile(r"(?<![\d./])([45]\d\d)(?![\d./])")
_URL_RX = re.compile(r"https?://\S+")


def friendly_error(error: str | None) -> str:
    """Short plain-language reason for a source or feed problem (the raw text stays in the data)."""
    if not error:
        return ""
    text = _URL_RX.sub("", error.removeprefix("partial: "))
    m = _STATUS_RX.search(text)
    code = int(m.group(1)) if m else None
    if code == 429:
        return "rate-limited by the site (HTTP 429)"
    if code in (401, 403):
        return f"blocked by the site (HTTP {code})"
    if code in (404, 410):
        return f"feed address not found (HTTP {code}); it may have moved"
    if code is not None and code >= 500:
        return f"the site had a server error (HTTP {code})"
    low = text.lower()
    if "invalid xml" in low or "no entries" in low:
        return "not a readable feed (no articles found)"
    if "timeout" in low or "timed out" in low:
        return "the site did not answer in time"
    if "connecterror" in low or "name or service" in low or "getaddrinfo" in low or "unreachable" in low:
        return "could not connect (offline, or the site is blocked)"
    return text.strip(" :")[:160]


def health_summary(health: list[SourceHealth]) -> str:
    """Honest one-line count, e.g. '6 healthy \u00b7 1 partial' (a channel with errors is never 'healthy')."""
    counts = Counter(h.status for h in health)
    parts = [f"{counts[k]} {HEALTH_WORDS[k]}" for k in ("ok", "partial", "empty", "failed") if counts[k]]
    return " \u00b7 ".join(parts) if parts else "no sources"


def source_health(report: PipelineReport, stories: list[Story] | None = None) -> list[SourceHealth]:
    used_by_source: Counter[str] = Counter()
    used_by_feed: Counter[str] = Counter()
    for story in stories or []:
        for e in story.evidence:
            used_by_source[e.source] += 1
            if e.feed:
                used_by_feed[e.feed] += 1
    out = []
    for s in report.source_stats:
        if not s.ok:
            status = "failed"
        elif s.error:
            status = "partial"
        elif s.item_count == 0:
            status = "empty"
        else:
            status = "ok"
        feeds = [FeedHealth(name=f.name, url=f.url, category=f.category,
                            status="failed" if not f.ok else ("ok" if f.item_count else "empty"),
                            collected=f.item_count, used=used_by_feed.get(f.url, 0), error=f.error)
                 for f in s.feeds]
        out.append(SourceHealth(source=s.source, name=source_name(s.source), status=status,
                                item_count=s.item_count, latency_ms=s.latency_ms, error=s.error,
                                used=used_by_source.get(s.source, 0), feeds=feeds))
    return out


def build_coverage(health: list[SourceHealth], stories: list[Story], selection: Selection,
                   report: PipelineReport) -> Coverage:
    ok = [h for h in health if h.status in ("ok", "partial")]
    failed = [h.name for h in health if h.status == "failed"]
    partial = [h.name for h in health if h.status in ("partial", "empty")]
    counts = Counter(s.category.value for s in stories)
    general = any(h.source in GENERAL_NEWS_SOURCES for h in ok)
    tech_n = sum(s.tech_only for s in stories)
    warnings: list[str] = []
    if failed:
        warnings.append(f"Unavailable this run: {', '.join(failed)}.")
    if partial:
        warnings.append(f"Partial or empty coverage: {', '.join(partial)}.")
    # A YouTube channel with no new upload answered normally; only failures and empty article feeds count.
    # A channel that (nearly) all failed at once is one outage, said once ('YouTube did not answer for 21 of
    # 22 channels'), not 21 broken feeds named like the publishers' working article feeds.
    from agent_reach.daily.feedhealth import OUTAGE_OK_SHARE

    unit = {"youtube": "channels", "google_news": "sections"}
    all_feeds, bad_feeds = [], []
    for h in health:
        down = [f for f in h.feeds if f.status == "failed"]
        if len(h.feeds) >= 5 and len(h.feeds) - len(down) < OUTAGE_OK_SHARE * len(h.feeds):
            warnings.append(f"{h.name} did not answer for {len(down)} of {len(h.feeds)} "
                            f"{unit.get(h.source, 'feeds')} (an outage or a block on that site; it usually passes).")
            continue
        all_feeds += h.feeds
        suffix = f" ({h.name})" if h.source == "youtube" else ""
        bad_feeds += [f.name + suffix for f in h.feeds
                      if f.status == "failed" or (f.status == "empty" and h.source != "youtube")]
    if bad_feeds:
        shown = ", ".join(bad_feeds[:6]) + (f" and {len(bad_feeds) - 6} more" if len(bad_feeds) > 6 else "")
        warnings.append(f"{len(bad_feeds)} of {len(all_feeds)} feeds returned nothing: {shown}.")
    if not general:
        warnings.append("No general-news source responded, so this edition may over-represent social and tech trends.")
    top = selection.top or stories
    top_tech = sum(s.tech_only for s in top)
    if top and top_tech / len(top) > 0.5:
        warnings.append(f"{top_tech} of {len(top)} top stories come only from tech sources.")
    if "lexical" in (report.llm_mode or ""):
        warnings.append("Embedding model unavailable: stories were grouped by shared words (less precise).")
    balanced = general and len(counts) >= 3 and (not top or top_tech / len(top) <= 0.5)
    return Coverage(
        sources_attempted=len(health), sources_ok=len(ok), failed=failed, partial=partial,
        category_counts=dict(counts.most_common()), general_news_available=general,
        tech_only_stories=tech_n, held_back_for_balance=selection.held_back, balanced=balanced, warnings=warnings,
    )


def build_overview(stories: list[Story], coverage: Coverage) -> str:
    if not stories:
        return ""
    cats = ", ".join(f"{k} {v}" for k, v in coverage.category_counts.items())
    text = (f"{len(stories)} {'story' if len(stories) == 1 else 'stories'} in {len(coverage.category_counts)} "
            f"sections from {coverage.sources_ok} of {coverage.sources_attempted} sources: {cats}.")
    if coverage.failed or coverage.partial or not coverage.balanced:
        text += " Coverage is partial today (see Details)."
    return text


def assemble_edition(
    report: PipelineReport,
    selection: Selection,
    prefs: DailyPrefs,
    *,
    started: datetime,
    completed: datetime,
    trigger: str,
    config_fingerprint: str,
    revision: int = 1,
    previous_revisions: list[Revision] | None = None,
    brief_stats: dict[str, int] | None = None,
) -> DailyEdition:
    if not report.valid or report.accounting is None:
        raise ValueError("only a valid report can become an edition")
    stories = selection.stories
    for i, s in enumerate(stories, start=1):
        s.rank = i
    health = source_health(report, stories)
    coverage = build_coverage(health, stories, selection, report)
    acct = report.accounting
    labels, labels_failed = report.label_calls, report.label_calls_failed
    mostly_fallback = bool(labels) and labels_failed >= MAX_LABEL_FALLBACK_SHARE * labels
    summaries = "extractive" if report.llm_mode.startswith("heuristic") or mostly_fallback else "local_model"
    brief = brief_stats or {}
    semantic = report.semantic or {}
    model = ModelInfo(llm_model=prefs.ollama_model, embed_model=prefs.embed_model, pipeline_mode=report.llm_mode,
                      embed_model_used=str(semantic.get("model_used") or ""), grouping=grouping_summary(semantic),
                      summaries=summaries, label_calls=labels, label_calls_failed=labels_failed,
                      brief_calls=brief.get("calls", 0), brief_calls_failed=brief.get("failed_calls", 0))
    notes = edition_notes(selection, prefs, extractive=summaries == "extractive", model=model)
    return DailyEdition(
        edition_date=central_date(started),
        revision=revision,
        previous_revisions=previous_revisions or [],
        run_id=report.run_id,
        trigger=trigger,
        generation_started_utc=started.astimezone(timezone.utc),
        generation_completed_utc=completed.astimezone(timezone.utc),
        model=model,
        config_fingerprint=config_fingerprint,
        pipeline_schema_version=report.schema_version,
        accounting=AccountingSummary(ingested=acct.ingested, passed_filters=acct.passed_filters,
                                     clustering_candidates=acct.clustering_candidates, clustered=acct.clustered,
                                     discarded_total=acct.discarded_total, balanced=acct.balanced),
        source_health=health,
        coverage=coverage,
        overview=build_overview(stories, coverage),
        notes=notes,
        stories=stories,
        top_ranks=[st.rank for st in selection.top],
    )


def edition_notes(selection: Selection, prefs: DailyPrefs, *, extractive: bool = False,
                  model: ModelInfo | None = None) -> list[str]:
    """Plain-language notes on what the edition left out or could not measure (each said once)."""
    stories = selection.stories
    notes = list(selection.notes)
    if stories and all(s.velocity_basis == "cold_start" for s in stories):
        notes.append("No Hot or Rising labels yet: momentum is measured against a refresh from about a day "
                     "earlier with the same sources, and there is none yet.")
    elif stories and all(momentum_uncertain(s) for s in stories):
        notes.append("No Hot or Rising labels today: the sources or settings changed since the refresh used "
                     "for comparison, so growth could not be measured fairly.")
    if selection.dropped_unsupported:
        n = selection.dropped_unsupported
        notes.append(f"{plural(n, 'ranked group was', 'ranked groups were')} omitted because "
                     f"{'it' if n == 1 else 'they'} had no citable factual sentence.")
    if selection.dropped_stale:
        notes.append(f"{plural(selection.dropped_stale, 'story was', 'stories were')} left out because every source "
                     f"was published more than {prefs.max_story_age_hours:g} hours before this refresh.")
    if selection.dropped_duplicate:
        notes.append(f"{plural(selection.dropped_duplicate, 'repeat', 'repeats')} of stories already in this "
                     "edition left out.")
    if selection.secondary:
        n = selection.secondary
        notes.append(f"{plural(n, 'opinion column or video clip is', 'opinion columns or video clips are')} "
                     f"listed after the news in {'its section' if n == 1 else 'their sections'} and kept out of "
                     "Top Stories.")
    if selection.dropped_weak:
        notes.append(f"{plural(selection.dropped_weak, 'weak signal was', 'weak signals were')} left out (a single "
                     "trend or social post with no article).")
    if selection.dropped_live_blog:
        notes.append(f"{plural(selection.dropped_live_blog, 'live blog was', 'live blogs were')} left out (a running "
                     "page of many updates is not one story).")
    if extractive and model is not None and model.model_stopped:
        notes.append("The local model stopped answering during this refresh, so summaries are lead sentences from "
                     "the sources.")
    elif extractive:
        notes.append("Summaries are extractive (lead sentences from the sources) because the local model was not used.")
    elif model is not None and model.label_calls_failed:
        notes.append(f"The local model stopped answering partway through: "
                     f"{plural(model.label_calls_failed, 'group of stories was', 'groups of stories were')} titled "
                     "from the reports themselves.")
    if model is not None and model.brief_calls and model.brief_calls_failed == model.brief_calls and not extractive:
        notes.append("No 'why it matters' notes this time: the local model stopped answering before writing them.")
    return notes


@dataclass
class PublishDecision:
    publishable: bool
    reasons: list[str]


def evaluate_publication(edition: DailyEdition, prefs: DailyPrefs, *, allow_extractive: bool = False,
                         same_day: DailyEdition | None = None) -> PublishDecision:
    """Publication is stricter than ledger validity: an empty run can balance and still be useless.

    ``same_day`` is the edition of the same date that this one would replace (as a new revision). A refresh where
    fewer than ``prefs.min_share_of_same_day`` of its sources answered, or of its stories passed, keeps that
    edition: before rc16 a run with 2 of 10 sources and 3 stories replaced a full edition of the day, on the
    website too (backend audit round 2, N1, Oct 8)."""
    reasons: list[str] = []
    cov = edition.coverage
    if cov.sources_ok == 0:
        reasons.append("No news source responded (offline, blocked or all feeds failed).")
    elif cov.sources_ok < prefs.min_ok_sources:
        reasons.append(f"Only {plural(cov.sources_ok, 'source', 'sources')} responded; at least "
                       f"{prefs.min_ok_sources} are required.")
    if len(edition.stories) < prefs.min_useful_stories:
        reasons.append(f"Only {plural(len(edition.stories), 'useful story was', 'useful stories were')} found; at least "
                       f"{prefs.min_useful_stories} are required for a daily edition.")
    if edition.model.summaries == "extractive" and prefs.require_llm and not allow_extractive:
        if edition.model.model_stopped:
            reasons.append("The local model (Ollama) stopped answering during the refresh, and AI summaries are "
                           "required by your settings.")
        else:
            reasons.append("The local model was not used, and AI summaries are required by your settings.")
    share = prefs.min_share_of_same_day
    if same_day is not None and same_day.edition_date == edition.edition_date and share > 0 and not reasons:
        before_sources, before_stories = same_day.coverage.sources_ok, len(same_day.stories)
        allowed = prefs.max_stories * max(1, len({s.category for s in same_day.stories}))
        if cov.sources_ok < share * before_sources or len(edition.stories) < share * min(before_stories, allowed):
            reasons.append(f"This refresh found much less than today's edition ({plural(len(edition.stories), 'story', 'stories')} "
                           f"from {plural(cov.sources_ok, 'source', 'sources')}, against "
                           f"{plural(before_stories, 'story', 'stories')} from {plural(before_sources, 'source', 'sources')}); "
                           "some news sources may not have answered.")
    if same_day is not None and same_day.edition_date == edition.edition_date:
        interval = (edition.generation_completed_utc - same_day.generation_completed_utc).total_seconds()
        from agent_reach.daily.changes import _match
        breaking = any(strength_of(s, edition.generation_completed_utc).level == 'strong'
                       and _match(s, same_day.stories) is None for s in top_stories(edition)[:3])
        if interval < 3600 and not breaking:
            reasons.append('Same-day updates wait at least 60 minutes unless new Strong coverage reaches the top 3.')
    return PublishDecision(publishable=not reasons, reasons=reasons)


def all_categories() -> list[str]:
    return CategoryEnum.values()
