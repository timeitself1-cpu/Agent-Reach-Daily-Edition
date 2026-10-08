"""Website publishing (agent_reach.daily.publish): the public copy of an edition, one atomic commit per publication
against a fake GitHub, idempotent retries, a failed upload that leaves the site as it was, withdraw and corrections."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path
from xml.etree import ElementTree

import httpx
import pytest

from agent_reach.daily import publish as P
from agent_reach.daily.edition import DailyEdition

REAL = Path(__file__).parent / "fixtures" / "real"


def real_edition(name: str = "2026-10-07-rc12d2-r2.json") -> DailyEdition:
    return DailyEdition.model_validate(json.loads((REAL / name).read_text(encoding="utf-8")))


class FakeGitHub:
    """Just enough of GitHub's git data API: refs, commits, trees, blobs, contents. ``fail`` maps a
    'METHOD path-prefix' to a status code returned once."""

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.blobs: dict[str, bytes] = {}
        self.trees: dict[str, dict[str, bytes]] = {}
        self.commits: dict[str, dict] = {}
        self.fail: dict[str, int] = {}
        self.calls: list[str] = []
        self.head = self._commit(dict(files or {}), [], "initial")
        self.auth: set[str] = set()

    def _sha(self, data: bytes) -> str:
        return hashlib.sha1(data).hexdigest()

    def _commit(self, tree: dict[str, bytes], parents: list[str], message: str) -> str:
        tsha = self._sha(json.dumps({k: base64.b64encode(v).decode() for k, v in sorted(tree.items())}).encode())
        self.trees[tsha] = tree
        csha = self._sha(f"{tsha}{parents}{message}{len(self.commits)}".encode())
        self.commits[csha] = {"tree": tsha, "parents": parents, "message": message}
        return csha

    @property
    def files(self) -> dict[str, bytes]:
        return self.trees[self.commits[self.head]["tree"]]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.auth.add(request.headers.get("Authorization", ""))
        path = request.url.path.split("/repos/owner/site", 1)[1]
        key = f"{request.method} {path}"
        self.calls.append(key)
        for prefix, status in list(self.fail.items()):
            if key.startswith(prefix):
                del self.fail[prefix]
                return httpx.Response(status, json={"message": "nope"})
        if request.method == "GET" and path == "/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": self.head}})
        if request.method == "GET" and path.startswith("/git/commits/"):
            return httpx.Response(200, json={"tree": {"sha": self.commits[path.rsplit("/", 1)[1]]["tree"]}})
        if request.method == "GET" and path.startswith("/contents/"):
            ref = request.url.params["ref"]
            tree = self.trees[self.commits[ref]["tree"]]
            name = path[len("/contents/"):]
            if name not in tree:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"encoding": "base64", "content": base64.b64encode(tree[name]).decode()})
        body = json.loads(request.content or b"{}")
        if request.method == "POST" and path == "/git/blobs":
            data = base64.b64decode(body["content"])
            sha = self._sha(data)
            self.blobs[sha] = data
            return httpx.Response(201, json={"sha": sha})
        if request.method == "POST" and path == "/git/trees":
            tree = dict(self.trees[body["base_tree"]])
            for entry in body["tree"]:
                if entry["sha"] is None:
                    tree.pop(entry["path"], None)
                else:
                    tree[entry["path"]] = self.blobs[entry["sha"]]
            tsha = self._sha(json.dumps({k: base64.b64encode(v).decode() for k, v in sorted(tree.items())}).encode())
            self.trees[tsha] = tree
            return httpx.Response(201, json={"sha": tsha})
        if request.method == "POST" and path == "/git/commits":
            csha = self._sha(f"{body['tree']}{body['parents']}{body['message']}{len(self.commits)}".encode())
            self.commits[csha] = {"tree": body["tree"], "parents": body["parents"], "message": body["message"]}
            return httpx.Response(201, json={"sha": csha})
        if request.method == "PATCH" and path == "/git/refs/heads/main":
            if self.head not in self.commits[body["sha"]]["parents"]:
                return httpx.Response(422, json={"message": "Update is not a fast forward"})
            self.head = body["sha"]
            return httpx.Response(200, json={"object": {"sha": self.head}})
        return httpx.Response(500, json={"message": f"unhandled {key}"})

    def target(self, token: str = "github_pat_test") -> P.GitHubTarget:
        return P.GitHubTarget("owner/site", "main", token, client=httpx.Client(transport=httpx.MockTransport(self.handler)))


# ---------------------------------------------------------------------------------------------------- public copy
def test_public_edition_carries_the_news_and_nothing_private():
    ed = real_edition()
    pub = P.public_edition(ed)
    text = json.dumps(pub)
    assert pub["edition_date"] == "2026-10-07" and pub["revision"] == 2 and len(pub["stories"]) == 44
    assert pub["stories"][0]["headline"] == "Computing Pioneer Margaret Hamilton Dies at 90"
    assert len(pub["top"]) == 8 and {s["category"] for s in pub["sections"]} >= {"News", "Tech", "Science & AI"}
    # publisher excerpts, run ids, feed lists and diagnostics never go up
    for s in ed.stories:
        for ev in s.evidence:
            if ev.excerpt and len(ev.excerpt) > 200:  # (a summary may quote one sentence of a lead, never the excerpt)
                assert ev.excerpt not in text
    for word in ('"excerpt"', ed.run_id, '"config_fingerprint"', '"source_health"', '"feed"', '"item_id"', '"notes"'):
        assert word not in text
    # every link is an absolute web link; kinds separate reporting from repeats and signals
    kinds = {src["kind"] for s in pub["stories"] for src in s["sources"]}
    assert kinds == {"report", "repeat", "signal"}
    assert all(src["url"] is None or src["url"].startswith(("https://", "http://"))
               for s in pub["stories"] for src in s["sources"])
    pike = next(s for s in pub["stories"] if s["headline"].startswith("Christa Pike"))
    assert pike["coverage"]["independent_reports"] >= sum(src["kind"] == "report" for src in pike["sources"])
    assert {"CNBC", "South China Morning Post"} <= {src["outlet"] for s in pub["stories"] for src in s["sources"]}
    assert P.public_edition(ed) == pub  # deterministic: a retry produces the same bytes


def test_text_that_looks_like_a_local_path_is_never_published():
    ed = real_edition()
    ed.stories[3].sentences[0] = r"Saved to C:\Users\someone\AppData\Local\AgentReachDaily\cache."
    with pytest.raises(P.PublishError, match="file path"):
        P.public_edition(ed)


def test_demo_editions_are_never_published():
    from tests.daily_fakes import make_edition

    with pytest.raises(P.PublishError, match="demo"):
        P.public_edition(make_edition(demo=True))


# ---------------------------------------------------------------------------------------------------- folder target
def test_folder_publish_is_idempotent_and_withdraw_moves_latest_back(daily_paths, tmp_path):
    site = P.FolderTarget(tmp_path / "site")
    older = real_edition("2026-10-07-selftest-r1.json").model_copy(deep=True)
    older.edition_date = older.edition_date.replace(day=6)  # stand-in for the previous day's edition
    r = P.publish_edition(daily_paths, older, site)
    assert r.state == "published"
    r = P.publish_edition(daily_paths, real_edition(), site)
    assert r.state == "published" and set(r.changed) == {"editions/2026-10-07.json", "editions/index.json",
                                                         "daily/2026-10-07/index.html", "feed.xml", "sitemap.xml",
                                                         "search/2026-10.json"}
    index = json.loads((tmp_path / "site/editions/index.json").read_text())
    assert index["latest"] == "2026-10-07" and [e["date"] for e in index["editions"]] == ["2026-10-07", "2026-10-06"]
    # the RSS feed and the sitemap follow the archive list: valid XML, one feed item per date, newest first
    feed = ElementTree.fromstring((tmp_path / "site/feed.xml").read_bytes())
    links = [i.findtext("link") for i in feed.iter("item")]
    assert links == ["https://getagentreach.dev/daily/2026-10-07/", "https://getagentreach.dev/daily/2026-10-06/"]
    assert feed.find("channel/item/title").text.startswith("October 7, 2026: ")
    sitemap = (tmp_path / "site/sitemap.xml").read_text()
    ElementTree.fromstring(sitemap)
    assert "/daily/2026-10-06/</loc><lastmod>" in sitemap and "<loc>https://getagentreach.dev/about/</loc>" in sitemap
    page = (tmp_path / "site/daily/2026-10-07/index.html").read_text()
    assert 'data-date="2026-10-07"' in page and "Margaret Hamilton" in page
    assert P.publish_edition(daily_paths, real_edition(), site).state == "unchanged"  # a retry adds nothing
    assert P.load_status(daily_paths).edition_date == "2026-10-07"

    # an older revision of the same date never replaces a newer one on the site
    r = P.publish_edition(daily_paths, real_edition("2026-10-07-rc12d2-r1.json"), site)
    assert r.state == "failed" and "newer revision" in r.message
    assert json.loads((tmp_path / "site/editions/2026-10-07.json").read_text())["revision"] == 2

    r = P.withdraw(daily_paths, "2026-10-07", site)
    assert r.state == "withdrawn"
    assert not (tmp_path / "site/editions/2026-10-07.json").exists()
    assert json.loads((tmp_path / "site/editions/index.json").read_text())["latest"] == "2026-10-06"
    assert "/daily/2026-10-07/" not in (tmp_path / "site/feed.xml").read_text()
    assert "/daily/2026-10-07/" not in (tmp_path / "site/sitemap.xml").read_text()
    assert {x["d"] for x in json.loads((tmp_path / "site/search/2026-10.json").read_text())["stories"]} == {"2026-10-06"}
    # automatic publishing does not bring the withdrawn edition back; a newer revision of that day would
    assert P.publish_edition(daily_paths, real_edition(), site, automatic=True).state == "skipped"
    newer = real_edition().model_copy(update={"revision": 3})
    assert P.publish_edition(daily_paths, newer, site, automatic=True).state == "published"
    assert "2026-10-07" not in P.load_settings(daily_paths).withdrawn


# ---------------------------------------------------------------------------------------------------- GitHub target
def test_github_publication_is_one_commit_and_a_retry_makes_none(daily_paths):
    gh = FakeGitHub({"index.html": b"<html>site</html>"})
    r = P.publish_edition(daily_paths, real_edition(), gh.target())
    assert r.state == "published" and r.commit == gh.head
    assert gh.commits[gh.head]["message"] == "Publish the 2026-10-07 edition (revision 2)"
    assert set(gh.files) == {"index.html", "editions/2026-10-07.json", "editions/index.json",
                             "daily/2026-10-07/index.html", "feed.xml", "sitemap.xml", "search/2026-10.json"}
    assert sum(c.startswith("PATCH") for c in gh.calls) == 1
    before = gh.head
    r = P.publish_edition(daily_paths, real_edition(), gh.target())
    assert r.state == "unchanged" and gh.head == before  # no duplicate commit
    assert gh.auth == {"Bearer github_pat_test"}


def test_a_failed_upload_leaves_the_website_as_it_was(daily_paths):
    gh = FakeGitHub({"index.html": b"<html>site</html>"})
    P.publish_edition(daily_paths, real_edition("2026-10-07-rc12d2-r1.json"), gh.target())
    live = gh.head
    gh.fail["PATCH /git/refs"] = 500
    r = P.publish_edition(daily_paths, real_edition(), gh.target())
    assert r.state == "failed" and "previous edition" in r.message
    assert gh.head == live and json.loads(gh.files["editions/2026-10-07.json"])["revision"] == 1
    status = P.load_status(daily_paths)
    assert status.state == "failed" and status.revision == 1  # the last success is still what the site has
    assert P.status_lines(daily_paths)["headline"] == "Publication failed: previous edition preserved"
    gh.fail["POST /git/trees"] = 401
    r = P.publish_edition(daily_paths, real_edition(), gh.target())
    assert r.state == "failed" and "access key" in r.message and gh.head == live


def test_a_branch_that_moved_is_reread_never_overwritten(daily_paths):
    gh = FakeGitHub({"index.html": b"<html>site</html>"})
    original = gh.handler

    def someone_pushes_first(request):
        if request.method == "PATCH" and not gh.fail.get("pushed"):
            gh.fail["pushed"] = 1  # never matches a request: just a flag
            gh.head = gh._commit({**gh.files, "about/index.html": b"new page"}, [gh.head], "site change")
        return original(request)

    target = P.GitHubTarget("owner/site", "main", "k", client=httpx.Client(transport=httpx.MockTransport(someone_pushes_first)))
    r = P.publish_edition(daily_paths, real_edition(), target)
    assert r.state == "published"
    assert "about/index.html" in gh.files and "editions/2026-10-07.json" in gh.files  # both changes kept


def test_hide_story_republishes_without_it(daily_paths):
    gh = FakeGitHub()
    ed = real_edition()
    P.publish_edition(daily_paths, ed, gh.target())
    pike = next(s for s in ed.stories if s.headline.startswith("Christa Pike"))
    r = P.hide_story(daily_paths, ed, pike.story_id, gh.target())
    assert r.state == "published"
    pub = json.loads(gh.files["editions/2026-10-07.json"])
    assert len(pub["stories"]) == 43 and pike.story_id[:12] not in pub["top"]
    assert "Christa Pike" not in gh.files["daily/2026-10-07/index.html"].decode()
    assert "Christa Pike" not in gh.files["search/2026-10.json"].decode()


def test_archive_search_files_per_month_repair_themselves(daily_paths, tmp_path):
    """search/YYYY-MM.json holds what the search page shows, newest date first; a month whose file is missing
    (editions published before search existed) is rebuilt from the edition files on the next publication."""
    site = P.FolderTarget(tmp_path / "site")
    older = real_edition("2026-10-07-selftest-r1.json").model_copy(deep=True)
    older.edition_date = older.edition_date.replace(day=6)
    september = real_edition().model_copy(deep=True)
    september.edition_date = september.edition_date.replace(month=9, day=30)
    for ed in (september, older):
        assert P.publish_edition(daily_paths, ed, site).state == "published"
    (tmp_path / "site/search/2026-10.json").unlink()  # as on a site published before search existed
    assert P.publish_edition(daily_paths, real_edition(), site).state == "published"
    month = json.loads((tmp_path / "site/search/2026-10.json").read_text())
    days = [x["d"] for x in month["stories"]]
    assert days == sorted(days, reverse=True) and set(days) == {"2026-10-07", "2026-10-06"}
    first = month["stories"][0]
    assert first["h"] == "Computing Pioneer Margaret Hamilton Dies at 90" and first["r"] == 1
    assert set(first) == {"d", "id", "r", "t", "c", "h", "s", "o", "l"} and len(first["s"]) <= P.SEARCH_SUMMARY_CHARS + 1
    assert json.loads((tmp_path / "site/search/2026-09.json").read_text())["stories"][0]["d"] == "2026-09-30"
    # withdrawing the only date of a month removes that month's file
    assert P.withdraw(daily_paths, "2026-09-30", site).state == "withdrawn"
    assert not (tmp_path / "site/search/2026-09.json").exists()


# ---------------------------------------------------------------------------------------------------- key and hook
def test_access_key_is_stored_outside_the_repo_and_forgotten(daily_paths, monkeypatch):
    monkeypatch.delenv(P.TOKEN_ENV, raising=False)
    assert P.load_token(daily_paths) is None and not P.has_token(daily_paths)
    with pytest.raises(P.PublishError):
        P.save_token(daily_paths, "two words")
    P.save_token(daily_paths, "  github_pat_abc123  ")
    assert P.load_token(daily_paths) == "github_pat_abc123"
    assert P.key_file(daily_paths).is_relative_to(daily_paths.root)
    if sys.platform == "win32":
        assert b"github_pat_abc123" not in P.key_file(daily_paths).read_bytes()  # DPAPI-encrypted
    else:
        assert P.key_file(daily_paths).stat().st_mode & 0o077 == 0
    P.forget_token(daily_paths)
    assert not P.has_token(daily_paths)


def test_refresh_hook_is_off_by_default_and_never_raises(daily_paths, monkeypatch):
    monkeypatch.delenv(P.TOKEN_ENV, raising=False)
    ed = real_edition()
    assert P.publish_after_refresh(daily_paths, ed) is None
    P.save_settings(daily_paths, P.PublishSettings(enabled=True))
    r = P.publish_after_refresh(daily_paths, ed)
    assert r is not None and r.state == "failed" and "no access key" in r.message
    P.save_token(daily_paths, "k")

    def offline(request):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(P, "github_target", lambda paths, settings=None, client=None:
                        P.GitHubTarget("owner/site", "main", "k", client=httpx.Client(transport=httpx.MockTransport(offline))))
    r = P.publish_after_refresh(daily_paths, ed)
    assert r.state == "failed" and "online" in r.message
