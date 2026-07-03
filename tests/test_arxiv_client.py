import time

import arxiv_client as ac


def test_is_rate_limited_body():
    assert ac._is_rate_limited_body(b"Rate exceeded.")
    assert ac._is_rate_limited_body(b"  rate exceeded. please slow down")
    assert not ac._is_rate_limited_body(b"<feed>...</feed>")


def test_paced_get_enforces_min_interval(monkeypatch):
    calls = []

    class FakeResp:
        status_code = 200
        content = b"<feed></feed>"
        headers = {}
        text = "<feed></feed>"

    def fake_get(url, timeout, headers):
        calls.append(time.monotonic())
        return FakeResp()

    monkeypatch.setattr(ac.requests, "get", fake_get)
    ac._reset_pacing_for_tests()
    monkeypatch.setattr(ac, "MIN_INTERVAL_SEC", 0.2)

    start = time.monotonic()
    ac._paced_get("http://x/1")
    ac._paced_get("http://x/2")
    assert len(calls) == 2
    assert calls[0] - start < 0.2  # first call is not delayed
    assert calls[1] - calls[0] >= 0.2  # second call waited


def test_build_query_basic_no_dates():
    q = ac._build_query("a b", "cs.IR", 0, 400)
    assert "all:a+b" in q  # quote_plus encodes the space in the multi-word query
    assert "cat:cs.IR" in q
    assert "start=0" in q
    assert "max_results=400" in q
    assert "sortBy=submittedDate&sortOrder=descending" in q
    assert "submittedDate:[" not in q  # no date range when neither bound given


def test_build_query_since_and_until():
    q = ac._build_query("x", "cs.IR", 0, 10, since="202501010000", until="202512312359")
    assert "submittedDate:[202501010000+TO+202512312359]" in q


def test_build_query_since_only_defaults_until():
    q = ac._build_query("x", "cs.IR", 0, 10, since="202501010000")
    assert "submittedDate:[" in q
    assert "202501010000+TO+299912312359" in q  # far-future default upper bound


def test_build_query_until_only_defaults_since():
    q = ac._build_query("x", "cs.IR", 0, 10, until="202512312359")
    assert "submittedDate:[" in q
    assert "197001010000+TO+202512312359" in q  # epoch default lower bound


def test_build_query_pagination():
    q = ac._build_query("x", "cs.IR", 6000, 2000)
    assert "start=6000" in q
    assert "max_results=2000" in q


def test_get_recent_arxiv_papers_returns_entries(monkeypatch):
    """Keep existing behavior: parses the paced GET response and returns entries."""
    captured = {}

    def fake_paced_get(url):
        captured["url"] = url
        return b"<feed></feed>"

    class FakeFeed:
        entries = ["entry1", "entry2"]

    monkeypatch.setattr(ac, "_paced_get", fake_paced_get)
    monkeypatch.setattr(ac.feedparser, "parse", lambda _content: FakeFeed())

    entries = ac.get_recent_arxiv_papers("recsys", "cs.IR")
    assert entries == ["entry1", "entry2"]
    assert captured["url"].startswith(ac.BASE_URL)
    assert "max_results=400" in captured["url"]  # new default
