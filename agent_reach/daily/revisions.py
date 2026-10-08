"""Selection hysteresis: an eligible incumbent needs a replacement scoring at least 20% more."""
from collections import Counter
from zoneinfo import ZoneInfo

from agent_reach.daily.changes import _match
from agent_reach.daily.edition import is_stale, is_live_blog_only, is_weak, qualifies


def retain_listed(candidates, previous, prefs, now):
    if previous is None or previous.edition_date != now.astimezone(ZoneInfo('America/Chicago')).date():
        return candidates
    remaining = [s for s in candidates if not is_stale(s, now, prefs.max_story_age_hours)
                 and not is_live_blog_only(s) and not is_weak(s) and qualifies(s, now)]
    incumbents = []
    for old in previous.stories:
        if is_stale(old, now, prefs.max_story_age_hours) or is_live_blog_only(old) or is_weak(old) or not qualifies(old, now):
            continue
        fresh = _match(old, remaining)
        if fresh is not None:
            remaining.remove(fresh)
            incumbents.append(fresh)
        else:
            incumbents.append(old.model_copy(deep=True))
    kept = []
    counts = Counter()
    for story in incumbents:
        if counts[story.category] < prefs.max_stories:
            kept.append(story)
            counts[story.category] += 1
    for challenger in remaining:
        if counts[challenger.category] < prefs.max_stories:
            kept.append(challenger)
            counts[challenger.category] += 1
            continue
        weakest = min((s for s in kept if s.category == challenger.category), key=lambda s: s.combined_score)
        if challenger.combined_score >= 1.2 * weakest.combined_score:
            kept.remove(weakest)
            kept.append(challenger)
    return sorted(kept, key=lambda s: -s.combined_score)
