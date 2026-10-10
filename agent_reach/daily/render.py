"""The ONE edition renderer: the public edition JSON -> HTML.

``render_edition_html(public, standalone=False)`` is the no-script shell of the live site (shared site CSS and
JS, which replace it in a browser) and ``standalone=True`` is the single self-contained file of the app's export
(inline CSS, no scripts, no remote assets). Only the page frame differs; the content is the same function:
sections from ``sections.json``, sources per story, coverage strength, "Why it matters", what changed and what
was left out, and a link to the corrections page.

Time policy (one place, ``_when``): a time is shown only when a source stated it (``published_utc``); a
retrieval time is never shown as a publication time (app invariant 9). The standalone file labels every time
with America/Chicago (the app's edition clock); the live shell prints UTC and marks the element
``data-local`` so ``site.js`` can show the reader's own zone. RSS stays UTC.

Every string from sources or the model is untrusted: escaped, and only absolute http(s) URLs become links.
"""

from __future__ import annotations

from datetime import date
from html import escape

from agent_reach.daily.edition import safe_url
from agent_reach.daily.sections import load_sections, section_label
from agent_reach.daily.timeutil import CENTRAL_TZ_NAME, format_central, format_long_date, format_utc, parse_utc
from agent_reach.ingestion.google_urls import is_google_news

SITE_URL = "https://getagentreach.dev"

BRIEF_STORIES = 5
COVERAGE_WORDS = {"strong": "Strong coverage", "moderate": "Moderate coverage"}

STANDALONE_CSS = """
:root { --bg:#f5f5f7; --card:#fff; --ink:#1d1d1f; --ink2:#3a3a3c; --muted:#6e6e73; --line:#e5e5ea; --accent:#0066cc;
        --warn-bg:#fff4d6; --warn-ink:#6b4e00; --demo-bg:#ffe1e1; --demo-ink:#8a1010; --shadow:0 1px 3px rgba(0,0,0,.06); }
@media (prefers-color-scheme: dark) { :root { --bg:#1c1c1e; --card:#2c2c2e; --ink:#f5f5f7; --ink2:#d1d1d6; --muted:#98989d;
  --line:#3a3a3c; --accent:#4da3ff; --warn-bg:#3a3018; --warn-ink:#f3d58a; --demo-bg:#4a1d1d; --demo-ink:#ffc9c9;
  --shadow:none; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); -webkit-font-smoothing:antialiased;
       font:16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif; }
main { max-width:820px; margin:0 auto; padding:32px 20px 56px; overflow-wrap:anywhere; }
h1 { font-size:2rem; letter-spacing:-.01em; margin:0 0 2px; }
.sub { color:var(--muted); margin:0 0 14px; }
nav.sections { display:flex; flex-wrap:wrap; gap:8px; margin:8px 0 10px; font-size:.9rem; }
nav.sections a { text-decoration:none; color:var(--ink2); background:var(--card); border:1px solid var(--line);
                 border-radius:999px; padding:3px 12px; }
nav.sections a:hover { color:var(--accent); }
section.sec > h2 { font-size:1.5rem; letter-spacing:-.01em; margin:34px 0 0; }
section.sec > .count { color:var(--muted); font-size:.9rem; margin:0 0 8px; }
.banner { border-radius:10px; padding:10px 14px; margin:12px 0; background:var(--warn-bg); color:var(--warn-ink); }
.demo { background:var(--demo-bg); color:var(--demo-ink); font-weight:700; }
article { background:var(--card); border:1px solid var(--line); border-radius:14px; box-shadow:var(--shadow);
          padding:16px 20px; margin:12px 0; }
article h3 { font-size:1.15rem; line-height:1.35; margin:2px 0 6px; }
a.hl { color:inherit; text-decoration:none; }
a.hl:hover, a.hl:focus-visible { color:var(--accent); text-decoration:underline; }
article p { margin:0 0 6px; color:var(--ink2); }
.kicker { color:var(--muted); font-size:.78rem; font-weight:600; letter-spacing:.02em; }
.cat { color:var(--accent); text-transform:uppercase; margin-right:6px; }
.label, .tag { text-transform:uppercase; margin-right:6px; }
.tag.new { color:#248a3d; } .tag.updated { color:var(--accent); }
.brief { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:12px 20px; margin:14px 0 4px; }
.brief h2 { font-size:.78rem; letter-spacing:.06em; text-transform:uppercase; color:var(--accent); margin:0 0 4px; }
.brief ul { margin:0; padding-left:18px; } .brief li { margin:4px 0; }
.brief a { color:inherit; text-decoration:none; } .brief a:hover { color:var(--accent); text-decoration:underline; }
.why { margin-top:8px !important; }
.why strong { color:var(--accent); font-size:.78rem; letter-spacing:.04em; text-transform:uppercase; margin-right:4px; }
details.evidence { margin:10px 0 0; }
details.evidence > summary { cursor:pointer; color:var(--muted); font-size:.85rem; padding:2px 0; }
details.evidence > summary:hover { color:var(--ink); }
summary:focus-visible { outline:2px solid var(--accent); outline-offset:2px; border-radius:4px; }
.strength { font-size:.85rem; color:var(--muted) !important; margin:6px 0 0 !important; }
ul.evidence { margin:6px 0 0; padding-left:18px; font-size:.88rem; }
ul.evidence li { margin:4px 0; }
ul.evidence small { color:var(--muted); display:block; }
ul.also { list-style:none; padding:0; margin:6px 0 0; }
ul.also li { padding:8px 2px; border-top:1px solid var(--line); }
p.also-h { color:var(--muted); font-size:.8rem; font-weight:600; text-transform:uppercase; letter-spacing:.04em; margin:18px 0 0; }
.more { margin-top:36px; }
.more > details { border-top:1px solid var(--line); padding:10px 0; }
.more > details > summary { cursor:pointer; color:var(--muted); }
.more ul { font-size:.9rem; }
.more .kind { font-weight:600; }
a { color:var(--accent); }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:.88rem; }
td, th { border-bottom:1px solid var(--line); padding:4px 6px; text-align:left; vertical-align:top; }
footer { color:var(--muted); font-size:.78rem; margin-top:28px; }
@media print { details.evidence > summary { display:none; } article { box-shadow:none; } }
"""


def _e(text: object) -> str:
    return escape("" if text is None else str(text), quote=True)


def _link(url: str | None, text: str, cls: str = "") -> str:
    safe = safe_url(url)
    if not safe:
        return _e(text)
    c = f' class="{cls}"' if cls else ""
    return f'<a{c} href="{_e(safe)}" rel="noopener noreferrer nofollow" target="_blank">{_e(text)}</a>'


def _when(iso: str | None, standalone: bool) -> str:
    """One timestamp as HTML. Standalone: America/Chicago with its zone abbreviation. Live shell: UTC, marked so
    site.js shows the reader's zone. Nothing parseable -> nothing (never a guess)."""
    stamp = parse_utc(iso)
    if stamp is None:
        return ""
    if standalone:
        return f'<time datetime="{_e(iso)}">{_e(format_central(stamp))}</time>'
    return f'<time datetime="{_e(iso)}" data-local="true">{_e(format_utc(stamp))}</time>'


def _slug(text: str) -> str:
    return "sec-" + "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")


def coverage_line(story: dict) -> tuple[str, str]:
    """(label, plain-English reasons) of a story's coverage strength, from the public coverage block."""
    c = story.get("coverage") or {}
    n = int(c.get("independent_reports") or 0)
    label = COVERAGE_WORDS.get(c.get("level") or "", "Single source" if n <= 1 else "Limited coverage")
    parts = [f"{n} independent newsroom{'s' if n != 1 else ''}" + (f": {', '.join(c['publishers'])}" if c.get("publishers") else "")
             if n else "no independent newsroom report yet"]
    if c.get("repeats"):
        parts.append(f"{c['repeats']} repeat or syndicated cop{'ies' if c['repeats'] != 1 else 'y'} counted once")
    if c.get("signals"):
        parts.append(f"{c['signals']} social or search signal{'s' if c['signals'] != 1 else ''} (attention, not reporting)")
    if n < 2:
        parts.append("not yet confirmed by a second independent newsroom")
    return label, "; ".join(parts)


def _source(src: dict, standalone: bool) -> str:
    published = _when(src.get("published_utc"), standalone)
    when = f"published {published}" if published else "publication time not stated"
    via = " &middot; Google News redirect" if is_google_news(src.get("url")) else ""
    kind = f" &middot; {_e(src['kind'])}" if src.get("kind") else ""
    return (f"<li>{_link(src.get('url'), src.get('title') or src.get('outlet') or 'Report')}"
            f"<small>{_e(src.get('outlet'))} &middot; {when}{kind}{via}</small></li>")


def _story(s: dict, number: int, standalone: bool) -> str:
    label, reasons = coverage_line(s)
    kicker = [f'<span class="cat">{_e(section_label(s.get("category", "")))}</span>']
    if s.get("change") in ("new", "updated"):
        kicker.append(f'<span class="tag {s["change"]}">{_e(s["change"])}</span>')
    kicker += [f'<span class="label">{_e(x)}</span>' for x in s.get("labels") or []]
    headline = _link(s.get("url"), s["headline"], "hl")
    body = "".join(f"<p>{_e(p)}</p>" for p in s.get("summary") or [])
    why = (f'<p class="why"><strong>Why it matters</strong> {_e(s["why_it_matters"])}</p>' if s.get("why_it_matters") else "")
    sources = s.get("sources") or []
    return (
        f'<article class="card" id="story-{_e(s["id"])}"><div class="kicker">{" ".join(kicker)}</div>'
        f"<h3>{number}. {headline}</h3>{body}{why}"
        f'<details class="evidence src"><summary>Sources ({len(sources)}) &middot; {_e(label)}</summary>'
        f'<p class="strength">{_e(label)}: {_e(reasons)}. Coverage counts independent newsrooms; it is not a fact check.</p>'
        f'<ul class="evidence">{"".join(_source(x, standalone) for x in sources)}</ul></details></article>'
    )


def _section(title: str, stories: list[dict], shown: set[str], standalone: bool, key: str) -> str:
    parts, also = [], []
    for s in stories:
        if s["id"] in shown:
            also.append(f'<li><a href="#story-{_e(s["id"])}">{_e(s["headline"])}</a></li>')
        else:
            shown.add(s["id"])
            parts.append(_story(s, len(parts) + 1, standalone))
    count = f"{len(stories)} {'story' if len(stories) == 1 else 'stories'}"
    head = "Also in Top Stories" if parts else "In Top Stories"
    also_html = f'<p class="also-h">{head}</p><ul class="also">{"".join(also)}</ul>' if also else ""
    sid = _slug(key)
    return (f'<section class="sec" id="{sid}" aria-labelledby="{sid}-h"><h2 id="{sid}-h">{_e(title)}</h2>'
            f'<p class="count">{count}</p>{"".join(parts)}{also_html}</section>')


def _changes(public: dict, corrections: str) -> str:
    ch = public.get("changes")
    if public.get("demo"):
        return ""
    if not ch:
        return ("<details><summary>What changed since last refresh</summary>"
                "<p>This is the first edition: there is no earlier edition to compare with.</p></details>")
    cmp = ch.get("compared_with") or {}
    counts = [f"{len(ch.get('new') or [])} new", f"{len(ch.get('updated') or [])} updated"]
    gone = ch.get("dropped") or []
    if gone:
        counts.append(f"{len(gone)} no longer in this edition")
    summary = " &middot; ".join(counts)
    compared = (f"<p>Compared with the edition of {_e(cmp.get('edition_date'))}"
                + (f" (update {_e(cmp['revision'])})" if int(cmp.get("revision") or 1) > 1 else "") + ".</p>") if cmp else ""
    dropped = ""
    if gone:
        dropped = ('<p class="dropped-note">Stories leave the edition when newer or better-covered news takes their place. '
                   'That does not mean they were wrong; <a href="/corrections/">corrections</a> are listed separately.</p>'
                   "<ul>" + "".join(f"<li>{_e(g.get('headline'))}</li>" for g in gone) + "</ul>")
    return f"<details><summary>What changed since last refresh ({summary})</summary>{compared}{dropped}</details>"


def _left_out(public: dict) -> str:
    """What the quality checks held back, in counts only (the held-back stories stay on the PC)."""
    q = public.get("quality")
    if not q or not q.get("stories_quarantined"):
        return ""
    reasons = ", ".join(f"{_e(k)}: {_e(v)}" for k, v in sorted((q.get("reason_counts") or {}).items()))
    return (f"<details><summary>Left out by quality checks ({_e(q['stories_quarantined'])})</summary>"
            f"<p>{_e(q['stories_quarantined'])} candidate stor{'y' if q['stories_quarantined'] == 1 else 'ies'} did not pass "
            f"the checks and {'is' if q['stories_quarantined'] == 1 else 'are'} not in this edition"
            + (f" ({reasons})" if reasons else "") + ".</p></details>")


def _source_health(public: dict) -> str:
    rows = "".join(f"<tr><td>{_e(x.get('name'))}</td><td>{_e(x.get('status'))}</td><td>{_e(x.get('reports'))}</td>"
                   f"<td>{_e(x.get('cited'))}</td></tr>" for x in public.get("sources") or [])
    if not rows:
        return ""
    return ("<details><summary>Source health</summary><div class=\"scroll\"><table><tr><th>Source</th><th>Status</th>"
            f"<th>Reports</th><th>Cited</th></tr>{rows}</table></div></details>")


def _grouping(public: dict) -> str:
    g = (public.get("run") or {}).get("grouping")
    if not g:
        return ""
    lines = [f"Grouping model: {g.get('model_used') or 'none'}" + (f" ({g['dims']} dimensions)" if g.get("dims") else "")]
    if g.get("fallback"):
        lines.append("Fallback: " + str(g["fallback"]))
    lines.append(f"Same-event check: {g.get('candidate_pairs', 0)} candidate pairs, {g.get('accepted_pairs', 0)} accepted, "
                 f"{g.get('refused_pairs', 0)} refused (different events, roundups or dates only); "
                 f"{g.get('merges_blocked', 0)} merges blocked")
    if g.get("roundups"):
        lines.append(f"{g['roundups']} multi-story roundups (newsletters, live blogs) were kept out of every story")
    if g.get("reports"):
        lines.append(f"Embeddings reused from earlier refreshes: {g.get('cache_hits', 0)} of {g['reports']} reports")
    return "<details><summary>How stories were grouped</summary><ul>" + "".join(f"<li>{_e(x)}</li>" for x in lines) + "</ul></details>"


def _groups(public: dict) -> list[tuple[str, str, list[dict]]]:
    """[(key, title, stories)]: Top Stories, then every section with stories, in sections.json order."""
    by_id = {s["id"]: s for s in public["stories"]}
    top = [by_id[i] for i in public.get("top") or [] if i in by_id] or sorted(public["stories"], key=lambda s: s["rank"])[:10]
    known = [s["id"] for s in load_sections()["sections"]]
    cats = sorted(public.get("sections") or [], key=lambda sec: known.index(sec["category"]) if sec["category"] in known else len(known))
    out = [("Top Stories", "Top Stories", top)]
    for sec in cats:
        stories = [by_id[i] for i in sec["ids"] if i in by_id]
        if stories:
            out.append((sec["category"], section_label(sec["category"]), stories))
    return out


def render_edition_html(public: dict, *, standalone: bool = False, site_url: str = SITE_URL) -> str:
    d = public["edition_date"]
    day = format_long_date(date.fromisoformat(d))
    demo = bool(public.get("demo"))
    heading = f"Trending news for {day}" if standalone else f"Agent Reach Daily: {day}"
    title = ("DEMO - " if demo else "") + heading
    groups = _groups(public)
    corrections = _e(f"{site_url.rstrip('/')}/corrections/") if standalone else "/corrections/"
    nav = "".join(f'<a href="#{_slug(k)}">{_e(t)} ({len(st)})</a>' for k, t, st in groups)
    shown: set[str] = set()
    top = groups[0][2]
    brief = "".join(f'<li><a href="#story-{_e(s["id"])}">{_e(s["headline"])}</a></li>' for s in top[:BRIEF_STORIES])
    brief_html = f'<section class="brief" aria-label="In brief"><h2>In brief</h2><ul>{brief}</ul></section>' if len(top) >= 3 else ""
    body = "".join(_section(t, st, shown, standalone, k) for k, t, st in groups) if public["stories"] else "<p>No stories in this edition.</p>"
    revision = f" &middot; update {int(public['revision'])}" if int(public.get("revision") or 1) > 1 else ""
    zone = CENTRAL_TZ_NAME if standalone else "UTC"
    generated = _when(public.get("generated_utc"), standalone)
    banners = ('<div class="banner demo">DEMO EDITION - sample content for testing the layout. These are not real news '
              "stories.</div>") if demo else ""
    notes = public.get("notes") or []
    notes_html = (f"<details><summary>Coverage notes ({len(notes)})</summary><ul>"
                  + "".join(f"<li>{_e(n)}</li>" for n in notes) + "</ul></details>") if notes else ""
    run = public.get("run") or {}
    foot_run = (f" &middot; run {_e(run.get('id'))} &middot; model {_e(run.get('llm'))} / {_e(run.get('grouping_model'))} "
                f"({_e(run.get('summaries'))}) &middot; refresh started {_when(run.get('started_utc'), standalone)}") if run else ""
    footer = (f"<footer>Agent Reach Daily &middot; edition {_e(d)} (America/Chicago){foot_run}. "
              "Times are shown in " + ("America/Chicago (CDT or CST)" if standalone else "UTC; with scripts on, in your own time zone")
              + ". Summaries are generated locally from the cited evidence; open the sources to verify. "
              + f'<a href="{corrections}">Corrections</a></footer>')
    main = (f'<h1>{_e(heading)}</h1><p class="sub">{len(public["stories"])} stories{revision} &middot; Generated {generated or "(time unknown)"}'
            f" &middot; times in {_e(zone)}</p>{banners}"
            f'<nav class="sections" aria-label="Sections">{nav}</nav>{brief_html}{body}'
            f'<div class="more">{_changes(public, corrections)}{_left_out(public)}'
            f'<details class="run-details"><summary>Run details</summary>{notes_html}{_grouping(public)}{_source_health(public)}</details></div>'
            f"{footer}")
    if standalone:
        return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; img-src 'none'\">"
                f"<title>{_e(title)}</title><style>{STANDALONE_CSS}</style></head>\n<body><main>{main}</main></body></html>\n")
    url = _e(f"{site_url.rstrip('/')}/daily/{d}/")
    lead = next(iter(groups[0][2]), None) or public["stories"][0]
    desc = _e(f"{lead['headline']}, and {len(public['stories']) - 1} more stories from the {day} edition.")
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
        f"<title>{_e(title)}</title>\n<meta name=\"description\" content=\"{desc}\">\n"
        f"<link rel=\"canonical\" href=\"{url}\">\n"
        f"<meta property=\"og:title\" content=\"{_e(title)}\"><meta property=\"og:description\" content=\"{desc}\">"
        f"<meta property=\"og:type\" content=\"article\"><meta property=\"og:url\" content=\"{url}\">\n"
        "<meta name=\"theme-color\" content=\"#121417\">\n"
        "<link rel=\"icon\" href=\"/assets/icon.svg\" type=\"image/svg+xml\">\n"
        "<link rel=\"alternate\" type=\"application/rss+xml\" title=\"Agent Reach Daily\" href=\"/feed.xml\">\n"
        "<link rel=\"stylesheet\" href=\"/assets/site.css\"><script src=\"/assets/site.js\" defer></script>\n"
        "</head>\n"
        f"<body data-page=\"edition\" data-date=\"{_e(d)}\">\n<div id=\"app\">\n"
        f'<main id="main" class="wrap shell"><nav aria-label="Edition navigation">'
        f'<a href="/daily/">Latest edition</a> &middot; <a href="/archive/">Browse the archive</a></nav>{main}</main>\n'
        "</div>\n</body>\n</html>\n"
    )


def main(argv: list[str] | None = None) -> int:
    """``python -m agent_reach.daily.render [--standalone] [--date D] -o out.html``: the same renderer, either frame."""
    import argparse
    from pathlib import Path

    from agent_reach.daily.paths import DataPaths
    from agent_reach.daily.publish import public_edition
    from agent_reach.daily.store import EditionStore

    ap = argparse.ArgumentParser(prog="agent_reach.daily.render")
    ap.add_argument("--standalone", action="store_true", help="one self-contained file (inline CSS, America/Chicago times)")
    ap.add_argument("--date", help="edition date (default: latest)")
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args(argv)
    store = EditionStore(DataPaths.resolve())
    edition = store.load_date(args.date)[0] if args.date else store.load_latest().edition
    if edition is None:
        print("No cached edition found.")
        return 2
    page = render_edition_html(public_edition(edition, export=args.standalone), standalone=args.standalone)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")
    print(f"Rendered {edition.edition_date.isoformat()} ({'standalone' if args.standalone else 'site shell'}) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
