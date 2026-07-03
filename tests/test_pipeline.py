# tests/test_pipeline.py
import cache as C
import main as M


class E:  # minimal feedparser-like entry
    def __init__(self, id, title, published, link, summary=""):
        self.id = id
        self.title = title
        self.published = published
        self.link = link
        self.summary = summary
        self.companies = None

    def get(self, k, d=None):
        return d


def test_collect_survives_category_fetch_failure(monkeypatch):
    """A transient arXiv failure for one category must not crash the run;
    other categories still contribute (regression for the daily-job crash)."""
    config = {"search_query": "q", "arxiv_category": "cs.IR OR cs.LG"}
    good = E(
        "http://arxiv.org/abs/2501.00001v1",
        "ok",
        "2025-01-01",
        "http://arxiv.org/abs/2501.00001v1",
    )

    def fake_get(query, cat):
        if cat == "cs.IR":
            raise RuntimeError("arXiv API failed after 6 retries")
        return [good]

    monkeypatch.setattr(M, "get_recent_arxiv_papers", fake_get)
    entries = M.collect_new_arxiv_entries(config, seen_ids=set())
    assert [e.id for e in entries] == [good.id]


def test_process_entries_matches_from_cache(monkeypatch):
    domains = ["uber.com"]
    cache = {
        "2603.06586": {
            "arxiv_id": "2603.06586",
            "affiliations": [],
            "emails": ["x@uber.com"],
        }
    }
    entry = E(
        "http://arxiv.org/abs/2603.06586v1",
        "Uber paper",
        "2026-03-01",
        "http://arxiv.org/abs/2603.06586v1",
    )
    created = []
    monkeypatch.setattr(
        M, "create_issue", lambda repo, tok, e, s: created.append(e.title)
    )
    monkeypatch.setattr(M, "summarize_with_ollama", lambda t, a: "sum")

    M.process_entries(
        [entry],
        domains,
        cache,
        seen_ids=set(),
        repo="r",
        token="t",
        cache_path=None,
        download=False,
    )
    assert created == ["Uber paper"]


def test_process_entries_cache_miss_downloads_writes_and_issues(monkeypatch, tmp_path):
    domains = ["uber.com"]
    cache = {}
    cache_file = tmp_path / "email_cache.jsonl"

    entry = E(
        "http://arxiv.org/abs/2603.06586v1",
        "Uber paper",
        "2026-03-01",
        "http://arxiv.org/abs/2603.06586v1",
        summary="An abstract about Uber routing.",
    )
    created = []
    monkeypatch.setattr(M, "extract_emails_from_arxiv_pdf", lambda _i: ["x@uber.com"])
    monkeypatch.setattr(
        M, "create_issue", lambda repo, tok, e, s: created.append(e.title)
    )
    monkeypatch.setattr(M, "summarize_with_ollama", lambda t, a: "sum")

    M.process_entries(
        [entry],
        domains,
        cache,
        seen_ids=set(),
        repo="r",
        token="t",
        cache_path=str(cache_file),
        download=True,
    )

    # (a) an issue was created
    assert created == ["Uber paper"]
    # (b) the normalized arxiv_id is now a key in cache
    assert "2603.06586" in cache
    # (c) the JSONL file has a line for it with expected fields
    loaded = C.load_cache(str(cache_file))
    assert "2603.06586" in loaded
    rec = loaded["2603.06586"]
    assert rec["emails"] == ["x@uber.com"]
    assert rec["url"] == "http://arxiv.org/abs/2603.06586v1"
    assert rec["published"] == "2026-03-01"
    # (d) the abstract is persisted so retroactive summaries aren't title-only
    assert rec["abstract"] == "An abstract about Uber routing."


def test_process_entries_skips_already_seen(monkeypatch):
    domains = ["uber.com"]
    cache = {}

    entry = E(
        "http://arxiv.org/abs/2603.06586v1",
        "Uber paper",
        "2026-03-01",
        "http://arxiv.org/abs/2603.06586v1",
    )
    created = []

    def boom(_i):
        raise AssertionError("should not download a seen entry")

    monkeypatch.setattr(M, "extract_emails_from_arxiv_pdf", boom)
    monkeypatch.setattr(M, "create_issue", lambda *a: created.append(1))
    monkeypatch.setattr(M, "summarize_with_ollama", lambda t, a: "sum")

    M.process_entries(
        [entry],
        domains,
        cache,
        seen_ids={"http://arxiv.org/abs/2603.06586v1"},
        repo="r",
        token="t",
        cache_path=None,
        download=True,
    )

    assert created == []
    assert cache == {}


def test_process_entries_issue_error_isolated(monkeypatch):
    domains = ["uber.com"]
    cache = {
        "2603.06586": {
            "arxiv_id": "2603.06586",
            "affiliations": [],
            "emails": ["x@uber.com"],
        }
    }
    entry = E(
        "http://arxiv.org/abs/2603.06586v1",
        "Uber paper",
        "2026-03-01",
        "http://arxiv.org/abs/2603.06586v1",
    )

    def boom(repo, tok, e, s):
        raise RuntimeError("github down")

    monkeypatch.setattr(M, "create_issue", boom)
    monkeypatch.setattr(M, "summarize_with_ollama", lambda t, a: "sum")

    seen_ids = set()
    # must not raise
    M.process_entries(
        [entry],
        domains,
        cache,
        seen_ids=seen_ids,
        repo="r",
        token="t",
        cache_path=None,
        download=False,
    )

    # link is NOT marked seen because the issue-filing failed
    assert entry.link not in seen_ids


def test_redecide_cache_files_issue_for_newly_added_domain(monkeypatch):
    domains = ["uber.com"]
    cache = {
        "2603.06586": {
            "arxiv_id": "2603.06586",
            "title": "Uber paper",
            "published": "2026-03-01",
            "url": "https://arxiv.org/abs/2603.06586",
            "affiliations": [],
            "emails": ["x@uber.com"],
        }
    }
    created = []
    monkeypatch.setattr(
        M, "create_issue", lambda repo, tok, e, s: created.append(e.title)
    )
    monkeypatch.setattr(M, "summarize_with_ollama", lambda t, a: "sum")

    M.redecide_cache(cache, domains, seen_ids=set(), repo="r", token="t")
    assert created == ["Uber paper"]


def test_redecide_cache_forwards_stored_abstract(monkeypatch):
    domains = ["uber.com"]
    cache = {
        "2603.06586": {
            "arxiv_id": "2603.06586",
            "title": "Uber paper",
            "published": "2026-03-01",
            "url": "https://arxiv.org/abs/2603.06586",
            "affiliations": [],
            "emails": ["x@uber.com"],
            "abstract": "Stored abstract text.",
        }
    }
    captured = {}
    monkeypatch.setattr(M, "create_issue", lambda repo, tok, e, s: None)

    def capture(title, abstract):
        captured["abstract"] = abstract
        return "sum"

    monkeypatch.setattr(M, "summarize_with_ollama", capture)

    M.redecide_cache(cache, domains, seen_ids=set(), repo="r", token="t")
    assert captured["abstract"] == "Stored abstract text."


def test_redecide_skips_already_seen(monkeypatch):
    domains = ["uber.com"]
    cache = {
        "1": {
            "arxiv_id": "1",
            "title": "t",
            "published": "2026",
            "url": "https://arxiv.org/abs/1",
            "affiliations": [],
            "emails": ["x@uber.com"],
        }
    }
    created = []
    monkeypatch.setattr(M, "create_issue", lambda *a: created.append(1))
    monkeypatch.setattr(M, "summarize_with_ollama", lambda t, a: "s")
    M.redecide_cache(
        cache,
        domains,
        seen_ids={"https://arxiv.org/abs/1"},
        repo="r",
        token="t",
    )
    assert created == []
