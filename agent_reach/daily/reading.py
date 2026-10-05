"""Reading features, computed without Tk: the 'In brief' digest, NEW / UPDATED / DAY n tags,
followed and muted topics, and which stories the reader has already read.

Read state lives in ``state/reading.json`` and is written only by the window (the refresh worker
never touches it). A story is identified by its ``story_id`` (the evidence fingerprint), so a story
that gains new evidence reads as unread again, which is what an updated story should do.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_reach.daily.edition import DailyEdition, Story
from agent_reach.daily.fsutil import atomic_write_json, read_json
from agent_reach.daily.paths import DataPaths

READ_KEEP_DAYS = 14
BRIEF_STORIES = 5
BRIEF_CHARS = 170
DEVELOPING_LOOKBACK = 7


# ====================================================================== read state
class ReadingState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int = 1
    read: dict[str, datetime] = Field(default_factory=dict)  # story_id -> when it was read


def _path(paths: DataPaths):
    return paths.state_dir / "reading.json"


def load_reading(paths: DataPaths) -> ReadingState:
    """Never fails: a missing or damaged file means nothing has been read."""
    try:
        return ReadingState.model_validate(read_json(_path(paths)))
    except (OSError, ValueError, ValidationError):
        return ReadingState()


def save_reading(paths: DataPaths, state: ReadingState, now: datetime) -> None:
    cutoff = now - timedelta(days=READ_KEEP_DAYS)
    state.read = {k: v for k, v in state.read.items() if v >= cutoff}
    try:
        atomic_write_json(_path(paths), state.model_dump(mode="json"))
    except OSError:
        pass  # read marks are a convenience; never an error for the reader


def set_read(paths: DataPaths, story_ids: list[str], now: datetime, read: bool = True) -> ReadingState:
    state = load_reading(paths)
    for sid in story_ids:
        if read:
            state.read.setdefault(sid, now)
        else:
            state.read.pop(sid, None)
    save_reading(paths, state, now)
    return state


# ====================================================================== topics
def _topic_rx(topic: str) -> re.Pattern[str]:
    words = [re.escape(w) for w in topic.split()]
    return re.compile(r"(?<![\w])" + r"\s+".join(words) + r"(?![\w])", re.IGNORECASE)


def story_text(story: Story) -> str:
    return " ".join([story.headline, *story.sentences, story.why_it_matters or "", *story.entities,
                     *(e.title for e in story.evidence)])


def matching_topics(story: Story, topics: list[str]) -> list[str]:
    """The topics (whole words or phrases, any case) a story mentions."""
    text = story_text(story)
    return [t for t in topics if t.strip() and _topic_rx(t).search(text)]


def without_muted(stories: list[Story], mute: list[str]) -> tuple[list[Story], int]:
    """Stories that mention no muted topic, and how many were hidden."""
    if not mute:
        return list(stories), 0
    kept = [s for s in stories if not matching_topics(s, mute)]
    return kept, len(stories) - len(kept)


def followed(stories: list[Story], follow: list[str]) -> list[Story]:
    """Stories that mention a followed topic, in rank order."""
    return [s for s in stories if follow and matching_topics(s, follow)]


def topic_suggestions(story: Story, limit: int = 4) -> list[str]:
    """Names to offer for 'Follow' / 'Mute': the story's key names, else names from its headline."""
    names = [e for e in story.entities if 2 <= len(e) <= 40]
    if not names:
        from agent_reach.pipeline.clusterer import extract_entities

        names = extract_entities([story.headline, *(e.title for e in story.evidence[:3])], limit=limit)
    out: list[str] = []
    for n in names:
        if n.lower() not in {o.lower() for o in out}:
            out.append(n)
    return out[:limit]


# ====================================================================== tags
def change_tags(edition: DailyEdition) -> dict[int, str]:
    """rank -> 'new' (not in the previous edition) or 'updated' (materially changed since then)."""
    ch = edition.changes
    if ch is None or edition.demo:
        return {}
    tags = {c.rank: "updated" for c in ch.updated if c.rank}
    tags.update({c.rank: "new" for c in ch.new if c.rank})
    return tags


def developing_since(edition: DailyEdition, earlier: list[DailyEdition]) -> dict[int, date]:
    """rank -> date first seen, for stories also present in the preceding editions (newest first).

    A story counts as developing while each earlier edition in turn still carries it; the first
    edition without it ends the run. Matching uses the same rules as 'what changed'.
    """
    from agent_reach.daily.changes import _match

    out: dict[int, date] = {}
    for story in edition.stories:
        first = None
        current = story
        for older in earlier:
            if older.edition_date >= edition.edition_date:
                continue
            match = _match(current, list(older.stories))
            if match is None:
                break
            first, current = older.edition_date, match
        if first is not None:
            out[story.rank] = first
    return out


def day_label(first_seen: date, today: date) -> str:
    return f"Day {(today - first_seen).days + 1}"


# ====================================================================== in brief
def brief_line(story: Story, limit: int = BRIEF_CHARS) -> str:
    """One sentence that says what happened (the story's lead sentence, clipped at a word)."""
    text = (story.sentences[0] if story.sentences else story.headline).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-") + "..."


def in_brief(stories: list[Story], n: int = BRIEF_STORIES) -> list[tuple[Story, str]]:
    return [(s, brief_line(s)) for s in stories[:n]]
