"""Neutral headline style, applied when an edition is published (``publish._public_story``, so the website, the
search index and the RSS feed all carry it). Style only: no word is added, reordered or paraphrased.

* A bait opener ('We Might Be Cooked, As ...') is removed when four or more words remain.
* A Title Case headline is put in sentence case. A word keeps its capital when it is a name: on the allowlist, one of
  the story's key names, or written capitalised in the middle of a sentence in the story's own prose (summary,
  report excerpts, reports that are not themselves Title Case). Function words, common headline words and any word
  the story's prose writes in lower case go to lower case. Every other word keeps its capital, because a wrong
  capital is cheaper than 'norvale' (the story's prose may simply never mention the name). The allowlist
  (``headline_keep_words`` in config.py), acronyms and mixed-case words (iPhone) are always kept.
* Quoted text is never touched.
* Trailing '!', '...', '?!' and '??' are removed. A single '?' stays: a question headline is not bait by itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from agent_reach.config import DEFAULT_HEADLINE_BAIT_OPENERS, DEFAULT_HEADLINE_KEEP_WORDS

FUNCTION_WORDS = frozenset("""a an the and or but nor so yet of to in on at for with by from as into onto over under
after before about against between through during without within up down out off per via vs than then that this these
those is are was were be been being am has have had do does did will would can could may might must shall should not
no it its he she they we you his her their our your who whom whose which what when where why how if while
until since because also just only still even""".split())
#: Ordinary words of headlines that a story's reports may not happen to write in lower case.
COMMON_WORDS = frozenset("""new says say said after amid over into more most first last next top big small major minor
latest early late late-night record high low best worst better worse hits hit set sets wins win won loses lose lost
beats beat rises rise falls fall drops drop cuts cut adds add gets get gives give takes take makes make shows show
finds find sees see warns warn plans plan faces face seeks seek calls call urges urge backs back blocks block
bans ban halts halt ends end delays delay postpones postpone starts start opens open closes close returns return reveals reveal launches launch
unveils unveil releases release announces announce confirms confirm denies deny rejects reject approves approve
accuses accuse charges charge arrests arrest sues sue dies die kills kill shot shoots shoot killed injured hurt
crash crashes strike strikes protest protests vote votes court judge police officials official report reports
study study finds experts workers people man woman men women children students teachers players team teams
company companies firm firms market markets stock stocks price prices rate rates jobs job pay deal deals talks
plan plans law laws rule rules ban bill bills tax taxes budget government war ceasefire attack attacks storm
storms fire fires flood floods quake earthquake hurricane update updates game games season week day year years
month months night time long still again back down off out up now today tonight tomorrow yesterday near
ports port browser browsers web work works seem seems perfectly latest launch launches bios chip chips laptop
laptops phone phones model models agents agent data training company data walk walks out again over pay audit
resigns resign quits quit funds fund missing winner winners joins join probe probes raid raids filing filings lawyer lawyers agents court
case cases trial ruling rules ruled bid bids push pushes move moves boost boosts surge surges slump slumps
hike hikes plunge plunges soar soars jump jumps leaps leap claims claim warns says tells tell asks ask wants want
needs need hopes hope fears fear vows vow pledges pledge promises promise offers offer sends send sent brings
bring pulls pull puts put keeps keep lets let runs goes go comes come leaves leave stays stay holds hold
service services island islands strike ferry workers worker union cut cuts jobs weeks months years days hours
minutes million billion thousand dollars percent per cent power energy oil gas climate health care school schools
hospital hospitals cities state states country countries world national local global federal public private
tech technology science space moon mars planet ocean sea river lake mountain park""".split())
# 'run' and 'city' are left out on purpose: 'Hit and Run' and 'Vice City' (Oct 10) are titles whose last word is one.
_SUFFIXES = ("ing", "ed", "ly", "ness", "tion", "ment")

_QUOTE_RX = re.compile(r"\"[^\"]*\"|“[^”]*”|‘[^’]*’|(?<!\w)'[^']*'(?!\w)")
_TOKEN_RX = re.compile(r"(\S+)")
_EDGE_RX = re.compile(r"^([\"'“‘(\[]*)(.*?)([\"'”’)\].,;:!?…]*)$", re.S)
_DOTTED_RX = re.compile(r"^(?:[A-Za-z]\.){2,}$")
_PLACEHOLDER_RX = re.compile(r"\x00\d+\x00")


@dataclass
class HeadlineConfig:
    keep_words: tuple[str, ...] = DEFAULT_HEADLINE_KEEP_WORDS
    bait_openers: tuple[str, ...] = DEFAULT_HEADLINE_BAIT_OPENERS

    @classmethod
    def from_settings(cls, settings=None) -> "HeadlineConfig":
        if settings is None:
            from agent_reach.config import Settings
            settings = Settings()
        return cls(tuple(settings.headline_keep_words), tuple(settings.headline_bait_openers))


def is_title_case(text: str) -> bool:
    """Most words of four letters or more (after the first) start with a capital."""
    words = [w for w in re.findall(r"[A-Za-z][\w'’-]*", text)[1:] if len(w) > 3]
    return bool(words) and sum(w[0].isupper() for w in words) >= 0.7 * len(words)


def strip_bait(headline: str, cfg: HeadlineConfig) -> str:
    for pattern in cfg.bait_openers:
        try:
            m = re.match(r"\s*(?:" + pattern + r")\s*[,:;!.–—-]*\s*(?:(?:as|but|and|because)\s+)?",
                         headline, re.IGNORECASE)
        except re.error:
            continue
        rest = headline[m.end():] if m else ""
        if m and len(rest.split()) >= 4:
            return rest[:1].upper() + rest[1:]
    return headline


def strip_trailing_bait(headline: str) -> str:
    out = re.sub(r"(?:\s*(?:!+|\.{2,}|…))+$", "", headline)  # 'Wow!' 'It works...'
    out = re.sub(r"\s*\?[?!]+$|\s*!+\?+$", "", out)  # '?!' '??'
    out = re.sub(r"(?:\.{2,}|…)\s*\?$", "", out)  # '...?'
    return out.rstrip()


def _known_lower(vouching_text: str) -> set[str]:
    """Words the story's own reports write in lower case somewhere (so they are ordinary words)."""
    return set(re.findall(r"(?<![A-Za-z'’-])[a-z][a-z'’-]*(?![A-Za-z])", vouching_text))


def sentence_case(headline: str, *, names: frozenset[str] | set[str] = frozenset(), vouching_text: str = "",
                  cfg: HeadlineConfig | None = None) -> str:
    cfg = cfg or HeadlineConfig()
    keep = {w.lower(): w for w in cfg.keep_words}
    key_names = {t.lower() for n in names for t in re.findall(r"[A-Za-z][\w'’-]*", n)}
    lower_seen = _known_lower(vouching_text)
    seen_names = _names_seen(vouching_text)
    quotes: list[str] = []

    def hold(m: re.Match) -> str:
        quotes.append(m.group(0))
        return f"\x00{len(quotes) - 1}\x00"

    text = _QUOTE_RX.sub(hold, headline)

    def fix_word(word: str, initial: bool) -> str:
        if not word or any(c.isdigit() for c in word):
            return word
        low = word.lower()
        if low in keep:
            return keep[low] if not initial or keep[low][:1].isupper() else keep[low]
        if _DOTTED_RX.match(word) or (word.isupper() and len(word) >= 2) or word[1:] != word[1:].lower():
            return word  # U.S., GTA, iPhone, McDonald
        if low in key_names or (low in seen_names and low not in FUNCTION_WORDS):
            return word
        if low in FUNCTION_WORDS or low in COMMON_WORDS or low in lower_seen or (len(low) > 5 and low.endswith(_SUFFIXES)):
            return word[:1].upper() + low[1:] if initial else low
        return word  # nothing shows that this is not a name

    out, initial = [], True
    for token in _TOKEN_RX.split(text):
        if not token or token.isspace():
            out.append(token)
            continue
        if _PLACEHOLDER_RX.search(token):
            out.append(token)
            initial = token.rstrip().endswith((":", "?", "!"))
            continue
        lead, core, trail = _EDGE_RX.match(token).groups()  # type: ignore[union-attr]
        parts = core.split("-") if not _DOTTED_RX.match(core) and "-" in core else [core]
        if core.lower() in keep:
            parts = [core]
        parts = [fix_word(p, initial and i == 0) for i, p in enumerate(parts)]
        out.append(lead + "-".join(parts) + trail)
        initial = trail.endswith((":", "?", "!", ".", "…")) and not _DOTTED_RX.match(core)
    result = "".join(out)
    return re.sub(r"\x00(\d+)\x00", lambda m: quotes[int(m.group(1))], result)


def normalize_headline(headline: str, *, names=(), vouching_text: str = "", cfg: HeadlineConfig | None = None) -> str:
    """The headline in neutral style (see the module text). Idempotent; returns the input if it ends up empty."""
    cfg = cfg or HeadlineConfig.from_settings()
    original = headline
    text = re.sub(r"\s+", " ", headline).strip()
    text = strip_bait(text, cfg)
    text = strip_trailing_bait(text)
    if is_title_case(text):
        text = sentence_case(text, names=set(names), vouching_text=vouching_text, cfg=cfg)
    return text if text.strip() else original


def _names_seen(prose: str) -> set[str]:
    """Words written with a capital in the middle of a sentence (so they are names)."""
    return {m.group(1).lower() for m in re.finditer(r"(?<=[a-z0-9,;:'’\"”)] )([A-Z][A-Za-z'’-]+)", prose)}
