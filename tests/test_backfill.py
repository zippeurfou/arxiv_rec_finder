import cache as C

import backfill as B


class _Entry:
    """Minimal feedparser-like entry stub."""

    def __init__(self, id, title="T", published="2025-01-01", link=None):
        self.id = id
        self.title = title
        self.published = published
        self.link = link or id


def test_iter_pages_stops_on_empty(monkeypatch):
    pages = [["a", "b"], ["c"], []]
    monkeypatch.setattr(
        B,
        "_fetch_page",
        lambda q, c, start, mr, since, until: (
            pages[start // mr] if start // mr < len(pages) else []
        ),
    )
    got = list(B.iter_all("q", "cs.IR", since="202501010000", page_size=2))
    assert got == ["a", "b", "c"]


def test_since_to_stamp():
    assert B._to_stamp("2025-01-01") == "202501010000"
    assert B._to_stamp("2025-01-01", end=True) == "202501012359"


def test_iter_all_paginates_multiple(monkeypatch):
    pages = [["a", "b"], ["c", "d"], ["e"], []]
    monkeypatch.setattr(
        B,
        "_fetch_page",
        lambda q, c, start, mr, since, until: (
            pages[start // mr] if start // mr < len(pages) else []
        ),
    )
    got = list(B.iter_all("q", "cs.IR", since="202501010000", page_size=2))
    assert got == ["a", "b", "c", "d", "e"]


def _stub_issue_deps(monkeypatch):
    """Monkeypatch summarize + create_issue; return list capturing issue calls."""
    created = []
    monkeypatch.setattr(B, "summarize_with_ollama", lambda title, body: "summary")
    monkeypatch.setattr(
        B, "create_issue", lambda repo, token, fe, summary: created.append(fe)
    )
    return created


def test_process_entry_cache_miss_downloads_appends_issues(monkeypatch, tmp_path):
    cache_path = str(tmp_path / "cache.jsonl")
    created = _stub_issue_deps(monkeypatch)
    monkeypatch.setattr(
        B, "extract_emails_from_arxiv_pdf", lambda arxiv_id: ["x@uber.com"]
    )
    entry = _Entry("http://arxiv.org/abs/2501.00001v1")
    aid = B.extract_arxiv_id(entry.id) or entry.id

    cache = {}
    seen = set()
    processed_ids = set()
    B._process_entry(
        entry,
        cache,
        ["uber.com"],
        seen,
        "owner/repo",
        "tok",
        processed_ids,
        cache_path=cache_path,
        download=True,
    )

    assert len(created) == 1
    assert aid in cache
    assert aid in processed_ids
    on_disk = C.load_cache(cache_path)
    assert aid in on_disk
    assert on_disk[aid]["emails"] == ["x@uber.com"]
    assert on_disk[aid]["url"] == entry.link


def test_process_entry_cache_hit_no_download(monkeypatch, tmp_path):
    cache_path = str(tmp_path / "cache.jsonl")
    created = _stub_issue_deps(monkeypatch)

    def _boom(arxiv_id):
        raise AssertionError("should not download on cache hit")

    monkeypatch.setattr(B, "extract_emails_from_arxiv_pdf", _boom)
    entry = _Entry("http://arxiv.org/abs/2501.00002v1")
    aid = B.extract_arxiv_id(entry.id) or entry.id
    cache = {
        aid: {
            "arxiv_id": aid,
            "title": "T",
            "published": "2025-01-01",
            "url": entry.link,
            "affiliations": [],
            "emails": ["x@uber.com"],
            "checked": "2025-01-01",
        }
    }

    B._process_entry(
        entry,
        cache,
        ["uber.com"],
        set(),
        "owner/repo",
        "tok",
        set(),
        cache_path=cache_path,
        download=True,
    )

    assert len(created) == 1


def test_process_entry_skips_duplicate_within_run(monkeypatch, tmp_path):
    cache_path = str(tmp_path / "cache.jsonl")
    created = _stub_issue_deps(monkeypatch)
    monkeypatch.setattr(
        B, "extract_emails_from_arxiv_pdf", lambda arxiv_id: ["x@uber.com"]
    )
    entry = _Entry("http://arxiv.org/abs/2501.00003v1")
    cache = {}
    seen = set()
    processed_ids = set()
    args = (cache, ["uber.com"], seen, "owner/repo", "tok", processed_ids)

    B._process_entry(entry, *args, cache_path=cache_path, download=True)
    B._process_entry(entry, *args, cache_path=cache_path, download=True)

    assert len(created) <= 1


def test_process_entry_issue_error_is_isolated(monkeypatch, tmp_path):
    cache_path = str(tmp_path / "cache.jsonl")
    monkeypatch.setattr(B, "summarize_with_ollama", lambda title, body: "summary")

    def _boom(repo, token, fe, summary):
        raise RuntimeError("github down")

    monkeypatch.setattr(B, "create_issue", _boom)
    monkeypatch.setattr(
        B, "extract_emails_from_arxiv_pdf", lambda arxiv_id: ["x@uber.com"]
    )
    entry = _Entry("http://arxiv.org/abs/2501.00004v1")
    seen = set()

    # must not raise
    B._process_entry(
        entry,
        {},
        ["uber.com"],
        seen,
        "owner/repo",
        "tok",
        set(),
        cache_path=cache_path,
        download=True,
    )

    assert entry.link not in seen
