"""Standalone HTML export of one cached edition (same JSON the GUI renders).

Every string from sources or the model is untrusted: it is escaped with ``html.escape`` (quotes
included) and only absolute http(s) URLs become links. The page has no scripts and no remote
assets, so it reads offline; the article links themselves need internet access.
"""

from __future__ import annotations

from html import escape

from agent_reach.daily.edition import DailyEdition, Story, safe_url
from agent_reach.daily.timeutil import edition_heading, format_central, updated_line

CSS = """
:root { --bg:#f6f5f2; --card:#fff; --ink:#1d1d1f; --muted:#5f6368; --line:#e2e0da; --accent:#1a5fb4;
        --warn-bg:#fff4d6; --warn-ink:#6b4e00; --demo-bg:#ffe1e1; --demo-ink:#8a1010; }
@media (prefers-color-scheme: dark) { :root { --bg:#17181a; --card:#212226; --ink:#ececec; --muted:#a3a7ad;
  --line:#33353a; --accent:#8ab4f8; --warn-bg:#3a3018; --warn-ink:#f3d58a; --demo-bg:#4a1d1d; --demo-ink:#ffc9c9; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 "Segoe UI", system-ui, sans-serif; }
main { max-width:860px; margin:0 auto; padding:24px 16px 48px; }
h1 { font-size:1.9rem; margin:0 0 4px; }
.sub { color:var(--muted); margin:0 0 16px; }
.banner { border-radius:8px; padding:10px 14px; margin:12px 0; background:var(--warn-bg); color:var(--warn-ink); }
.demo { background:var(--demo-bg); color:var(--demo-ink); font-weight:700; }
.overview { font-size:1.05rem; margin:12px 0 20px; }
article { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px; margin:14px 0; }
article h2 { font-size:1.2rem; margin:0 0 6px; }
.meta { color:var(--muted); font-size:.85rem; margin-bottom:8px; }
.chip { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:0 8px; margin-right:6px; font-size:.8rem; }
.label { font-weight:600; }
.why { margin-top:6px; }
ul.evidence { margin:10px 0 0; padding-left:18px; font-size:.9rem; }
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


def _story(s: Story) -> str:
    chips = [f'<span class="chip">{_e(s.category.value)}</span>']
    chips += [f'<span class="chip label">{_e(label)}</span>' for label in s.labels]
    body = " ".join(_e(x) for x in s.sentences)
    why = f'<p class="why"><strong>Why it matters:</strong> {_e(s.why_it_matters)}</p>' if s.why_it_matters else ""
    items = []
    for ev in s.evidence:
        when = ""
        if ev.published_at_utc:
            when = f" &middot; published {_e(format_central(ev.published_at_utc))}"
        elif ev.retrieved_at_utc:
            when = f" &middot; publication time not stated; retrieved {_e(format_central(ev.retrieved_at_utc))}"
        pub = f" ({_e(ev.publisher)})" if ev.publisher else ""
        excerpt = f'<span class="excerpt">{_e(ev.excerpt)}</span>' if ev.excerpt else ""
        items.append(f"<li>{_e(ev.source_name)}: {_link(ev.url, ev.title)}{pub}{when}{excerpt}</li>")
    platforms = ", ".join(s.platforms)
    return (
        f'<article id="story-{s.rank}"><h2>{s.rank}. {_e(s.headline)}</h2>'
        f'<div class="meta">{"".join(chips)} {_e(s.raw_item_count)} signal(s) from {_e(platforms)}</div>'
        f"<p>{body}</p>{why}"
        f'<ul class="evidence">{"".join(items)}</ul></article>'
    )


def render_edition_html(edition: DailyEdition) -> str:
    title = edition_heading(edition.edition_date)
    banners = []
    if edition.demo:
        banners.append('<div class="banner demo">DEMO EDITION - sample content for testing the layout. '
                       "These are not real news stories.</div>")
    for w in edition.coverage.warnings:
        banners.append(f'<div class="banner">{_e(w)}</div>')
    for n in edition.notes:
        banners.append(f'<div class="banner">{_e(n)}</div>')
    rows = "".join(
        f"<tr><td>{_e(h.name)}</td><td>{_e(h.status)}</td><td>{_e(h.item_count)}</td><td>{_e(h.error or '')}</td></tr>"
        for h in edition.source_health
    )
    revision = f" &middot; revision {edition.revision}" if edition.revision > 1 else ""
    stories = "".join(_story(s) for s in edition.stories) or "<p>No stories in this edition.</p>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'">
<title>{_e(("DEMO - " if edition.demo else "") + title)}</title><style>{CSS}</style></head>
<body><main>
<h1>{_e(title)}</h1>
<p class="sub">{_e(updated_line(edition.generation_completed_utc))}{revision}</p>
{"".join(banners)}
<p class="overview">{_e(edition.overview)}</p>
{stories}
<h3>Source health</h3>
<table><tr><th>Source</th><th>Status</th><th>Items</th><th>Notes</th></tr>{rows}</table>
<footer>Agent Reach Daily &middot; edition {_e(edition.edition_date.isoformat())} (America/Chicago) &middot;
run {_e(edition.run_id)} &middot; model {_e(edition.model.llm_model)} / {_e(edition.model.embed_model)}
({_e(edition.model.summaries)}) &middot; refresh started {_e(format_central(edition.generation_started_utc))}.
Summaries are generated locally from the cited evidence; open the sources to verify.</footer>
</main></body></html>
"""
