"""Local news: which stories file under the edition's Local section.

The model never chooses "Local" (an 8B model would file world news there); a fixed rule decides it from
the reports' own titles and descriptions, after the model has labelled the story:

* a report TITLE names a town of the area (Frisco, Plano, McKinney, Collin County, Frisco ISD, ...): Local,
  from any outlet. "Frisco" alone is not enough when the text places it in Colorado or San Francisco;
* a report from a local feed (category hint Local) names the area or its region (North Texas, Dallas-Fort
  Worth, Dallas, Fort Worth) in its title or description: Local;
* professional sports stay in Sports: the Cowboys train in Frisco, so "FRISCO, Texas (AP)" datelines are
  common in NFL reports. School and youth sports (ISD, high school) are Local.

A report from a local feed that names no local place (a TV station's national story) is categorised as
usual; its Local hint counts as News there (``ordinary``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from agent_reach.models import CategoryEnum


@dataclass(frozen=True)
class LocalArea:
    key: str
    name: str
    towns: re.Pattern[str]       # a title naming one of these is local from any outlet
    region: re.Pattern[str]      # counts only for reports from local feeds
    elsewhere: re.Pattern[str]   # "Frisco" in these contexts is another place
    searches: tuple[str, ...] = ()  # Google News sections ("Local|search words|Name") read for this area


def _rx(words: Iterable[str]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)


FRISCO_TX = LocalArea(
    key="frisco-tx",
    name="Frisco & North Texas",
    # towns whose name is also a word or a surname need their state or school district
    towns=_rx([r"frisco", r"collin county", r"denton county", r"plano", r"little elm", r"lewisville",
               r"mckinney,? (?:texas|tx)", r"city of mckinney", r"prosper,? (?:texas|tx)", r"town of prosper",
               r"the colony,? (?:texas|tx)", r"celina,? (?:texas|tx)", r"allen,? (?:texas|tx)",
               r"(?:frisco|plano|mckinney|prosper|allen|celina|little elm|lewisville) isd",
               r"dallas north tollway", r"sam rayburn tollway", r"toyota stadium", r"riders field"]),
    region=_rx([r"north texas", r"dallas[- ]fort worth", r"dfw", r"dallas", r"fort worth", r"metroplex",
                r"denton", r"mckinney", r"prosper", r"arlington,? (?:texas|tx)", r"garland,? (?:texas|tx)",
                r"irving,? (?:texas|tx)", r"richardson,? (?:texas|tx)", r"carrollton"]),
    elsewhere=_rx([r"frisco,? colo(?:rado)?", r"summit county", r"breckenridge", r"san francisco",
                   r"frisco,? (?:north carolina|n\.?c\.?)", r"hatteras"]),
    searches=('Local|"Frisco" Texas|Google News - Frisco',
              'Local|"Collin County" OR "Frisco ISD" OR Plano OR "Denton County"|Google News - Collin & Denton'),
)
AREAS = {FRISCO_TX.key: FRISCO_TX}

#: Pro teams whose news stays in Sports even with a Frisco dateline (school and youth sports are Local).
_PRO_SPORTS = _rx([r"cowboys", r"fc dallas", r"stars", r"mavericks", r"mavs", r"rangers", r"nfl", r"mls", r"nhl",
                   r"nba", r"mlb", r"pga", r"lpga", r"rough riders", r"dallas wings", r"wnba"])
_SCHOOL_SPORTS = _rx([r"isd", r"high school", r"uil", r"varsity", r"youth"])


def area(key: str | None) -> LocalArea | None:
    return AREAS.get((key or "").strip().lower())


def google_news_sections(key: str | None) -> list[str]:
    where = area(key)
    return list(where.searches) if where else []


def ordinary(category: CategoryEnum | None) -> CategoryEnum | None:
    """A Local feed hint outside the Local rule counts as general news."""
    return CategoryEnum.NEWS if category is CategoryEnum.LOCAL else category


_FRISCO_TEXAS = re.compile(r"\bfrisco,? (?:texas|tx)\b", re.IGNORECASE)


def _names_town(text: str, where: LocalArea, context: str | None = None) -> bool:
    """Does ``text`` name a town of the area? ``context`` (the reports' descriptions too) decides whether a
    bare "Frisco" is another Frisco (Colorado's ski town, San Francisco's old nickname)."""
    found = [m.group(0).lower() for m in where.towns.finditer(text)]
    if not found:
        return False
    if any(t != "frisco" for t in found) or _FRISCO_TEXAS.search(f"{text} {context or ''}"):
        return True
    return not where.elsewhere.search(f"{text} {context or ''}")


def is_local(proposed: CategoryEnum, members, where: LocalArea | None) -> bool:
    """Does this story (its member reports, labelled ``proposed``) belong in the Local section?"""
    if where is None or not members:
        return False
    titles = " | ".join(m.normalized_title or "" for m in members)
    texts = " | ".join(f"{m.normalized_title or ''} {m.description or ''}" for m in members)
    if proposed is CategoryEnum.SPORTS and _PRO_SPORTS.search(texts) and not _SCHOOL_SPORTS.search(texts):
        return False
    if _names_town(titles, where, texts):
        return True
    for m in members:
        if m.category_hint is not CategoryEnum.LOCAL:
            continue
        text = f"{m.normalized_title or ''} {m.description or ''}"
        if _names_town(text, where) or (where.region.search(text) and not where.elsewhere.search(text)):
            return True
    return False
