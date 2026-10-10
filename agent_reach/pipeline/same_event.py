"""A narrow second chance for same-actor, same-action, same-day headline pairs."""
import re
from datetime import datetime, timezone

STOP = set('a an the of to in on for and or with at by from as is are was be not before after says said us new will promises promise resume again january february march april may june july august september october november december'.split())
ACTION_GROUPS = [
    {'strike', 'attack', 'bomb'}, {'launch', 'unveil', 'introduce'}, {'resign', 'quit'},
    {'arrest', 'detain'}, {'suspend', 'halt', 'pause'}, {'win', 'defeat'},
]


def title_words(title):
    title = re.sub(r'\bu\.s\.', 'us', title.lower())
    # Compare the main claim, rather than a trailing background clause in a longer publisher title.
    title = re.split(r'\s+as\s+', title, maxsplit=1)[0]
    words = {w.removesuffix('s') for w in re.findall(r'[a-z0-9]+', title) if w not in STOP}
    for family in ACTION_GROUPS:
        if words & family:
            words = (words - family) | {sorted(family)[0]}
    return words


def _actor(title):
    title = re.sub(r'^(?:sources?|reports?|exclusive|breaking)\s*:\s*', '', title.lower())
    prefix = re.split(r"\b(?:says|said|promises|will|won['’]t|has|have|is|are|launch\w*|unveil\w*|introduc\w*|"
                      r"win\w*|resign\w*|suspend\w*|strike\w*|attack\w*|bomb\w*|arrest\w*|detain\w*|"
                      r"refus\w*|reject\w*|orders?|rises?|falls?)\b", title, maxsplit=1)[0]
    roles = {'the', 'a', 'an', 'president', 'former', 'prime', 'minister'}
    return [w for w in re.findall(r'[a-z]+', prefix) if w not in roles]


def _same_actor(a, b):
    left, right = _actor(a.normalized_title), _actor(b.normalized_title)
    return bool(left and right and (left == right or (len(left) == 1 and left[0] == right[-1])
                                    or (len(right) == 1 and right[0] == left[-1])))


def _different_central_actors(a, b) -> bool:
    """Two reports about different named individuals cannot be the same event.

    Catches cases like a Pentagon execution livestream (about a specific military case)
    vs Christa Pike's execution: same topic (capital punishment) but different people,
    different actions, different events. The actor extraction focuses on the title prefix
    (who the story is about), so 'Pentagon plans to livestream execution' vs
    'Christa Pike execution scheduled' correctly identifies different central figures.
    """
    left, right = _actor(a.normalized_title), _actor(b.normalized_title)
    if not left or not right:
        return False
    # Normalize: compare as sets of words, ignoring order
    left_set, right_set = set(left), set(right)
    # If they share no words at all and both name specific entities (2+ words or a
    # distinctive single name), they are about different actors.
    if not (left_set & right_set):
        # Single common words like 'pentagon' vs 'pike' are distinctive enough when
        # the rest of the title context differs (checked by the caller via topic words)
        left_specific = len(left) >= 2 or (len(left) == 1 and len(left[0]) > 4)
        right_specific = len(right) >= 2 or (len(right) == 1 and len(right[0]) > 4)
        if left_specific and right_specific:
            return True
    return False


def _same_actor_action_day(a, b, shared_actor, *, check_actor=True):
    if not shared_actor or (check_actor and not _same_actor(a, b)):
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
    return bool(re.search(r"\b(?:not|never|no|won['’]t|cannot|can['’]t|refuses?|rejects?)\b", title, re.I))


def _different_bounds(a, b):
    bounds = [re.search(r'\b(before|after|during|until)\b', item.normalized_title, re.I) for item in (a, b)]
    return bool(all(bounds) and bounds[0][1].lower() != bounds[1][1].lower())


def same_event_titles(a, b, *, shared_actor: bool = False) -> bool:
    return bool(_same_actor_action_day(a, b, shared_actor) and not _different_bounds(a, b)
                and _negative(a.normalized_title) == _negative(b.normalized_title))


def conflicting_claims(a, b, *, shared_actor: bool = False) -> bool:
    return bool(_same_actor_action_day(a, b, shared_actor, check_actor=False) and
                (not _same_actor(a, b) or _different_bounds(a, b)
                or _negative(a.normalized_title) != _negative(b.normalized_title)))
