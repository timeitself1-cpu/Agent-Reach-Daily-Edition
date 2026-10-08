"""A narrow second chance for same-actor, same-action, same-day headline pairs."""
import re
from datetime import datetime, timezone

STOP = set('a an the of to in on for and or with at by from as is are was be not before after says said us new will promises promise resume'.split())
ACTION_GROUPS = [
    {'strike', 'attack', 'bomb'}, {'launch', 'unveil', 'introduce'}, {'resign', 'quit'},
    {'arrest', 'detain'}, {'suspend', 'halt', 'pause'}, {'win', 'defeat'},
]


def title_words(title):
    return {w.removesuffix('s') for w in re.findall(r'[a-z0-9]+', title.lower()) if w not in STOP}


def _same_actor_action_day(a, b, shared_actor):
    if not shared_actor:
        return False
    def stated_time(item):
        raw = item.metadata.get('published_at')
        try:
            stamp = datetime.fromisoformat(str(raw).replace('Z', '+00:00')) if raw else None
            return stamp.astimezone(timezone.utc) if stamp and stamp.tzinfo else None
        except ValueError:
            return None
    da, db = stated_time(a), stated_time(b)
    if da is None or db is None or da.date() != db.date():
        return False
    ta, tb = title_words(a.normalized_title), title_words(b.normalized_title)
    if len(ta & tb) / max(1, len(ta | tb)) < 0.4:
        return False
    return any(ta & family and tb & family for family in ACTION_GROUPS)


def _negative(title):
    return bool(re.search(r'\b(?:not|never|no|refuses?|rejects?)\b', title, re.I))


def same_event_titles(a, b, *, shared_actor: bool = False) -> bool:
    return bool(_same_actor_action_day(a, b, shared_actor) and _negative(a.normalized_title) == _negative(b.normalized_title))


def conflicting_claims(a, b, *, shared_actor: bool = False) -> bool:
    return bool(_same_actor_action_day(a, b, shared_actor) and _negative(a.normalized_title) != _negative(b.normalized_title))
