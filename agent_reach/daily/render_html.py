"""Standalone HTML export of one cached edition (same JSON the GUI renders).

Every string from sources or the model is untrusted: it is escaped with ``html.escape`` (quotes
included) and only absolute http(s) URLs become links. The page has no scripts and no remote
assets, so it reads offline; the article links themselves need internet access.
"""

from __future__ import annotations

from html import escape

from agent_reach.daily.edition import DailyEdition, Story, category_sections, safe_url, top_stories
from agent_reach.daily.strength import strength_of
from agent_reach.daily.timeutil import edition_heading, format_central, updated_line

CSS = """
:root { --bg:#f6f5f2; --card:#fff; --ink:#1d1d1f; --muted:#5f6368; --line:#e2e0da; --accent:#1a5fb4;
        --warn-bg:#fff4d6; --warn-ink:#6b4e00; --demo-bg:#ffe1e1; --demo-ink:#8a1010; }
@media (prefers-color-scheme: dark) { :root { --bg:#17181a; --card:#212226; --ink:#ececec; --muted:#a3a7ad;
  --line:#33353a; --accent:#8ab4f8; --warn-bg:#3a3018; --warn-ink:#f3d58a; --demo-bg:#4a1d1d; --demo-ink:#ffc9c9; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif; }
nav.sections { display:flex; flex-wrap:wrap; gap:6px 14px; margin:6px 0 18px; font-size:.92rem; }
nav.sections a { text-decoration:none; }
section.sec > h2 { font-size:1.45rem; margin:30px 0 4px; }
section.sec > .count { color:var(--muted); font-size:.9rem; margin:0 0 6px; }
ul.also { list-style:none; padding:0; margin:8px 0 0; }
ul.also li { padding:8px 0; border-top:1px solid var(--line); }
ul.also .num { color:var(--muted); font-weight:600; margin-right:8px; }
.more { margin-top:30px; }
.more > details { border-top:1px solid var(--line); padding:10px 0; }
.more > details > summary { cursor:pointer; color:var(--muted); }
main { max-width:860px; margin:0 auto; padding:24px 16px 48px; }
h1 { font-size:1.9rem; margin:0 0 4px; }
.sub { color:var(--muted); margin:0 0 16px; }
.banner { border-radius:8px; padding:10px 14px; margin:12px 0; background:var(--warn-bg); color:var(--warn-ink); }
.demo { background:var(--demo-bg); color:var(--demo-ink); font-weight:700; }
.overview { font-size:1.05rem; margin:12px 0 20px; }
article { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 20px; margin:12px 0; }
article h2 { font-size:1.2rem; margin:0 0 6px; }
.meta { color:var(--muted); font-size:.85rem; margin-bottom:8px; }
.chip { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:0 8px; margin-right:6px; font-size:.8rem; }
.label { font-weight:600; }
.why { margin-top:6px; }
details.evidence { margin:10px 0 0; border-top:1px solid var(--line); padding-top:8px; }
details.evidence > summary { cursor:pointer; color:var(--muted); font-size:.9rem; padding:2px 0; }
details.evidence > summary:hover { color:var(--ink); }
summary:focus-visible { outline:2px solid var(--accent); outline-offset:2px; border-radius:4px; }
.strength { font-size:.85rem; color:var(--muted); margin:6px 0 0; }
.changes { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 18px; margin:14px 0; }
.changes h2 { font-size:1.05rem; margin:0 0 4px; }
.changes ul { margin:6px 0 0; padding-left:18px; font-size:.92rem; }
.changes .kind { font-weight:600; }
@media print { details.evidence > summary { display:none; } }
ul.evidence { margin:6px 0 0; padding-left:18px; font-size:.9rem; }
ul.evidence li { margin:4px 0; }
a { color:var(--accent); }
.excerpt { color:var(--muted); display:block; }
table { border-collapse:collapse; width:100%; font-size:.9rem; }
td, th { border-bottom:1px solid var(--line); padding:4px 6px; text-align:left; vertical-align:top; }
footer { color:var(--muted); font-size:.8rem; margin-top:28px; }
"""


def _e(text: object) -> str:
    return escape("" if text is None else str(text), quote=True)


def _link(url: str | None, text: str) -> str:
    safe = safe_url(url)
    if not safe:
        return _e(text)
    return f'<a href="{_e(safe)}" rel="noopener noreferrer nofollow" target="_blank">{_e(text)}</a>'


def _story(s: Story, edition: DailyEdition, number: int | None = None) -> str:
    chips = [f'<span class="chip">{_e(s.category.value)}</span>']
    chips += [f'<span class="chip label">{_e(label)}</span>' for label in s.labels]
    body = " ".join(_e(x) for x in s.sentences)
    why = f'<p class="why"><strong>Why it matters:</strong> {_e(s.why_it_matters)}</p>' if s.why_it_matters else ""
    items = []
    for ev in s.evidence:
        if ev.published_at_utc:
            when = f" &middot; published {_e(format_central(ev.published_at_utc))}"
        else:
            when = " &middot; publication time not stated"
            if ev.retrieved_at_utc:
                when += f"; retrieved {_e(format_central(ev.retrieved_at_utc))}"
        pub = f" ({_e(ev.publisher)})" if ev.publisher else ""
        excerpt = f'<span class="excerpt">{_e(ev.excerpt)}</span>' if ev.excerpt else ""
        items.append(f"<li>{_e(ev.source_name)}: {_link(ev.url, ev.title)}{pub}{when}{excerpt}</li>")
    platforms = ", ".join(s.platforms)
    strength = strength_of(s, edition.generation_completed_utc)
    return (
        f'<article id="story-{s.rank}"><h2>{number or s.rank}. {_e(s.headline)}</h2>'
        f'<div class="meta">{"".join(chips)} {_e(strength.label)} &middot; {_e(s.raw_item_count)} signal(s) from '
        f'{_e(platforms)}</div>'
        f"<p>{body}</p>{why}"
        f'<details class="evidence"><summary>Sources and evidence ({len(s.evidence)}) &middot; {_e(strength.label)}'
        f'</summary><p class="strength">{_e(strength.label)}: {_e("; ".join(strength.reasons))}.</p>'
        f'<ul class="evidence">{"".join(items)}</ul></details></article>'
    )


_KIND_TEXT = {"new": "New", "updated": "Updated", "signals_up": "Growing", "signals_down": "Fading"}


def _changes(edition: DailyEdition) -> str:
    """'What changed since last refresh', collapsed at the end of the page (none for demo editions)."""
    if edition.demo:
        return ""
    ch = edition.changes
    if ch is None:
        return ("<details><summary>What changed since last refresh</summary>"
                "<p>This is the first edition: there is no earlier edition to compare with.</p></details>")
    items = [f'<li><span class="kind">{_KIND_TEXT[c.kind]}:</span> {_e(c.headline)}'
             + (f" &mdash; {_e(c.detail)}" if c.detail and c.kind != "new" else "") + "</li>"
             for group in (ch.new, ch.updated, ch.signals_up, ch.signals_down) for c in group]
    items += [f'<li><span class="kind">No longer listed:</span> {_e(c.headline)}</li>' for c in ch.gone]
    compared = (f"Compared with the edition of {_e(ch.compared_edition_date)}"
                + (f" (revision {ch.compared_revision})" if ch.compared_revision > 1 else "")
                + f", generated {_e(format_central(ch.compared_generated_utc))}.")
    body = f"<p>{_e(ch.summary())}{'; ' + str(ch.unchanged) + ' unchanged' if ch.unchanged else ''}. {compared}</p>"
    return (f"<details><summary>What changed since last refresh ({_e(ch.summary())})</summary>{body}"
            + (f"<ul>{''.join(items)}</ul>" if items else "") + "</details>")


def _slug(text: str) -> str:
    return "sec-" + "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")


def _section(title: str, stories: list[Story], edition: DailyEdition, shown: set[int]) -> str:
    """One section: full story cards, or a one-line link for a story already shown above."""
    parts = []
    also = []
    for i, s in enumerate(stories, start=1):
        if s.rank in shown:
            also.append(f'<li><span class="num">{i}.</span><a href="#story-{s.rank}">{_e(s.headline)}</a>'
                        f' <span class="count">(in Top Stories)</span></li>')
        else:
            parts.append(_story(s, edition, number=i))
            shown.add(s.rank)
    count = f"{len(stories)} {'story' if len(stories) == 1 else 'stories'}"
    also_html = f'<ul class="also">{"".join(also)}</ul>' if also else ""
    return (f'<section class="sec" id="{_slug(title)}" aria-labelledby="{_slug(title)}-h">'
            f'<h2 id="{_slug(title)}-h">{_e(title)}</h2><p class="count">{count}</p>{"".join(parts)}{also_html}</section>')


def render_edition_html(edition: DailyEdition) -> str:
    title = edition_heading(edition.edition_date)
    banners = []
    if edition.demo:
        banners.append('<div class="banner demo">DEMO EDITION - sample content for testing the layout. '
                       "These are not real news stories.</div>")
    notes = list(edition.coverage.warnings) + list(edition.notes)
    rows = "".join(
        f"<tr><td>{_e(h.name)}</td><td>{_e(h.status)}</td><td>{_e(h.item_count)}</td><td>{_e(h.error or '')}</td></tr>"
        for h in edition.source_health
    )
    revision = f" &middot; revision {edition.revision}" if edition.revision > 1 else ""
    top = top_stories(edition)
    groups = [("Top Stories", top)] + category_sections(edition)
    nav = "".join(f'<a href="#{_slug(t)}">{_e(t)} ({len(st)})</a>' for t, st in groups)
    shown: set[int] = set()
    body = "".join(_section(t, st, edition, shown) for t, st in groups) if edition.stories else \
        "<p>No stories in this edition.</p>"
    notes_html = ("<details><summary>Coverage notes ({0})</summary><ul>{1}</ul></details>".format(
        len(notes), "".join(f"<li>{_e(n)}</li>" for n in notes)) if notes else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'">
<title>{_e(("DEMO - " if edition.demo else "") + title)}</title><style>{CSS}</style></head>
<body><main>
<h1>{_e(title)}</h1>
<p class="sub">{_e(updated_line(edition.generation_completed_utc))}{revision}</p>
{"".join(banners)}
<nav class="sections" aria-label="Sections">{nav}</nav>
{body}
<div class="more">
{_changes(edition)}
{notes_html}
<details><summary>Source health</summary>
<table><tr><th>Source</th><th>Status</th><th>Items</th><th>Notes</th></tr>{rows}</table></details>
</div>
<footer>Agent Reach Daily &middot; edition {_e(edition.edition_date.isoformat())} (America/Chicago) &middot;
run {_e(edition.run_id)} &middot; model {_e(edition.model.llm_model)} / {_e(edition.model.embed_model)}
({_e(edition.model.summaries)}) &middot; refresh started {_e(format_central(edition.generation_started_utc))}.
Summaries are generated locally from the cited evidence; open the sources to verify.</footer>
</main></body></html>
"""
