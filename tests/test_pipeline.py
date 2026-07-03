# tests/test_pipeline.py
import main as M


class E:  # minimal feedparser-like entry
    def __init__(self, id, title, published, link):
        self.id = id
        self.title = title
        self.published = published
        self.link = link
        self.summary = ""
        self.companies = None

    def get(self, k, d=None):
        return d


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
