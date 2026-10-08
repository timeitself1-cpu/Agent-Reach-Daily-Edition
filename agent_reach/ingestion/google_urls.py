"""Bounded, cached Google News redirect resolution. Unresolved links remain explicitly labelled."""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit, urljoin

from bs4 import BeautifulSoup

from agent_reach.pipeline.enricher import ContentEnricher, _is_public_http_url


def is_google_news(url: str | None) -> bool:
    try:
        return (urlsplit(url or '').hostname or '').lower() == 'news.google.com'
    except ValueError:
        return False


class GoogleNewsResolver:
    def __init__(self, settings) -> None:
        self.enricher = ContentEnricher(settings)
        self.path = Path(settings.db_path).with_name('google-news-urls.json')
        try:
            self.cache = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(self.cache, dict):
                self.cache = {}
        except (OSError, ValueError):
            self.cache = {}
        self.pending: dict[str, asyncio.Task] = {}

    async def resolve(self, url, client, semaphore) -> str | None:
        if not is_google_news(url):
            return url
        cached = self.cache.get(url)
        if isinstance(cached, dict) and cached.get('until', 0) > time.time():
            return cached.get('url')
        if url not in self.pending:
            self.pending[url] = asyncio.create_task(self._resolve(url, client, semaphore))
        try:
            return await self.pending[url]
        finally:
            self.pending.pop(url, None)

    async def _resolve(self, url, client, semaphore) -> str | None:
        resolved = None
        try:
            async def fetch():
                page = await self.enricher._get(url, client, semaphore, 'text/html')
                if page is None:
                    return None
                if not is_google_news(page.url):
                    return page.url
                if 'html' not in page.content_type.lower():
                    return None
                soup = BeautifulSoup(page.body, 'html.parser')
                targets = [t.get('href') for t in soup.select('link[rel="canonical"]')]
                targets += [t.get('content') for t in soup.select('meta[property="og:url"]')]
                for tag in soup.select('meta[http-equiv]'):
                    if str(tag.get('http-equiv')).lower() == 'refresh':
                        m = re.search(r'url\s*=\s*(.+)', str(tag.get('content')), re.I)
                        if m:
                            targets.append(m.group(1).strip('"\''))
                for target in targets:
                    if not target:
                        continue
                    destination = urljoin(page.url, str(target))
                    if _is_public_http_url(destination) and not is_google_news(destination):
                        # The existing safe fetch validates DNS and redirects, including Google HTML targets.
                        final = await self.enricher._get(destination, client, semaphore, 'text/html')
                        if final and not is_google_news(final.url):
                            return final.url
                return None
            resolved = await asyncio.wait_for(fetch(), timeout=8)
        except Exception:  # a failed resolver never drops a source
            pass
        self.cache[url] = {'url': resolved, 'until': time.time() + (7 * 86400 if resolved else 3600)}
        self.cache = {key: value for key, value in self.cache.items()
                      if isinstance(value, dict) and value.get('until', 0) > time.time()}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(self.cache), encoding='utf-8')
            temp.replace(self.path)
        except OSError:
            pass
        return resolved
