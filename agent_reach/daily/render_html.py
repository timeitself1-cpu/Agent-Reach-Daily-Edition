"""Standalone HTML export of one cached edition: the shared renderer (``render.py``) in its standalone frame.

There is ONE renderer. The export is the public edition shape (``publish.public_edition(export=True)``: no
publisher excerpts, nothing local) drawn by ``render.render_edition_html(..., standalone=True)``: a single file
with inline CSS, no scripts and no remote assets, so it reads offline; the article links need internet access.
"""

from __future__ import annotations

from agent_reach.daily.edition import DailyEdition
from agent_reach.daily.publish import public_edition
from agent_reach.daily.render import render_edition_html as _render


def render_edition_html(edition: DailyEdition) -> str:
    return _render(public_edition(edition, export=True), standalone=True)
