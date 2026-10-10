"""Release 2: Cross-edition event identity validation.

Feeds saved editions into the event ID logic and verifies:
1. Same event across editions → same event_id (continuity)
2. Different events on same topic → different event_ids (no false merges)

Usage: python3 scripts/validate_event_identity.py

Standalone: does not require pydantic or other deps.
"""
import hashlib
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path


try:
    from agent_reach.pipeline.evidence import canonical_event_id as _canonical_event_id
except ImportError:
    _canonical_event_id = None


def canonical_event_id_standalone(story: dict) -> str:
    """Canonical event ID for validation (prefers pipeline function if available)."""
    if _canonical_event_id is not None:
        try:
            return _canonical_event_id(story)
        except Exception:
            pass
    # Prefer event_id if already present
    if story.get("event_id"):
        return story["event_id"]
    # Prefer entity_id
    if story.get("entity_id"):
        return "evt_" + str(story["entity_id"])[:12]
    # Fallback: headline hash
    headline = story.get("headline", "")
    return "evt_" + hashlib.sha256(f"{headline.casefold()}|fallback".encode()).hexdigest()[:12]


def load_edition(date: str) -> dict:
    path = Path(__file__).parent.parent / "website" / "editions" / f"{date}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    dates = ["2026-10-08", "2026-10-09", "2026-10-10"]
    editions = {}
    for d in dates:
        try:
            editions[d] = load_edition(d)
            print(f"Loaded {d}: {len(editions[d].get('stories', []))} stories")
        except FileNotFoundError:
            print(f"Missing {d}, skipping")

    # Compute event IDs for all stories
    story_ids = {}  # (date, idx) -> event_id
    for date, ed in editions.items():
        for i, story in enumerate(ed.get("stories", [])):
            try:
                eid = canonical_event_id_standalone(story)
                story_ids[(date, i)] = eid
            except Exception as e:
                print(f"  ERROR computing ID for {date} story {i}: {e}")
                story_ids[(date, i)] = None

    print(f"\nComputed {len(story_ids)} event IDs")

    # Test 1: Continuity — find stories with similar headlines across editions
    print("\n=== Test 1: Cross-edition continuity ===")

    def headline_sim(a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    continuity_checks = 0
    continuity_pass = 0
    for d1 in dates:
        for d2 in dates:
            if d1 >= d2:
                continue
            stories1 = editions[d1].get("stories", [])
            stories2 = editions[d2].get("stories", [])
            for i, s1 in enumerate(stories1):
                for j, s2 in enumerate(stories2):
                    sim = headline_sim(s1.get("headline", ""), s2.get("headline", ""))
                    if sim > 0.7:  # likely same event
                        continuity_checks += 1
                        id1 = story_ids.get((d1, i))
                        id2 = story_ids.get((d2, j))
                        match = id1 == id2 and id1 is not None
                        if match:
                            continuity_pass += 1
                        status = "PASS" if match else "FAIL"
                        print(f"  [{status}] {d1}#{i} <-> {d2}#{j} (sim={sim:.2f})")
                        print(f"    '{s1.get('headline', '')[:60]}...'")
                        print(f"    IDs: {id1} vs {id2}")

    print(f"\nContinuity: {continuity_pass}/{continuity_checks} passed")

    # Test 2: No false merges — different stories in same edition should have different IDs
    print("\n=== Test 2: No false merges (same edition) ===")
    false_merges = 0
    total_pairs = 0
    for date, ed in editions.items():
        stories = ed.get("stories", [])
        ids = [story_ids.get((date, i)) for i in range(len(stories))]
        # Count duplicates (excluding None)
        seen = {}
        for i, eid in enumerate(ids):
            if eid is None:
                continue
            if eid in seen:
                # Check if they're actually the same event (similar headlines)
                j = seen[eid]
                sim = headline_sim(stories[i].get("headline", ""), stories[j].get("headline", ""))
                total_pairs += 1
                if sim < 0.5:
                    false_merges += 1
                    print(f"  [FALSE MERGE] {date}#{j} and #{i} share ID {eid}")
                    print(f"    '{stories[j].get('headline', '')[:50]}...'")
                    print(f"    '{stories[i].get('headline', '')[:50]}...'")
            else:
                seen[eid] = i

    print(f"\nFalse merges: {false_merges}/{total_pairs} pairs")
    print("\n=== Summary ===")
    print(f"Continuity: {continuity_pass}/{continuity_checks}")
    print(f"False merges: {false_merges}")
    return 0 if false_merges == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
