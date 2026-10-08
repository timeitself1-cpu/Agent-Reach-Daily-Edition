import os

import pytest

from agent_reach import main as M
from agent_reach.config import Settings
from agent_reach.pipeline import clusterer as C
from tests.fakes import FakeOllama, MockAsyncClient

# The suite also runs inside the user's installed folder (the self-test), where the app may update itself: no test,
# and no app process a test starts, ever checks for or installs an update (tests/test_daily_updater.py lifts this).
os.environ["AGENT_REACH_NO_UPDATE"] = "1"


@pytest.fixture
def fake_ollama(monkeypatch):
    fake = FakeOllama()
    monkeypatch.setattr(C.SemanticClusterer, "_get_client", lambda self: fake)
    return fake


@pytest.fixture
def mock_http(monkeypatch):
    monkeypatch.setattr(M.httpx, "AsyncClient", MockAsyncClient)
    async def public_dns(host, port):
        return "93.184.216.34"
    monkeypatch.setattr("agent_reach.pipeline.enricher._resolve_public", public_dns)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        db_path=tmp_path / "test.db", http_backoff_base_s=0.05, reddit_request_spacing_s=0.1, tiktok_request_spacing_s=0.1,
        reddit_subreddits=["popular", "news"], max_items_for_llm=40, min_items_per_source_for_llm=0,
    )


# ------------------------------------------------------------------ Agent Reach Daily fixtures
@pytest.fixture
def daily_paths(tmp_path):
    from agent_reach.daily.paths import DataPaths

    return DataPaths.resolve(tmp_path / "Agent Reach Daily data").ensure()


@pytest.fixture
def daily_env(monkeypatch, daily_paths):
    """Offline daily refresh: fake publisher feeds + fake local model + daily prefs in a temp data folder."""
    import httpx

    from agent_reach.daily.prefs import DailyPrefs, save_prefs
    from tests import daily_fakes as F

    net = F.FakeNet()
    model = F.FakeDailyModel()
    monkeypatch.setattr(httpx, "AsyncClient", net.client_class())
    monkeypatch.setattr(C.SemanticClusterer, "_get_client", lambda self: model)

    async def public_dns(host, port):
        return "93.184.216.34"

    monkeypatch.setattr("agent_reach.pipeline.enricher._resolve_public", public_dns)
    save_prefs(daily_paths, DailyPrefs(enabled_sources=["news_rss", "google_news", "hackernews"],
                                       news_rss_feeds=F.feed_settings_entries()))

    class Env:
        paths = daily_paths
        fakes = F

    Env.net, Env.model = net, model
    return Env
