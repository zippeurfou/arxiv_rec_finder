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

    ac._paced_get("http://x/1")
    ac._paced_get("http://x/2")
    assert len(calls) == 2
    assert calls[1] - calls[0] >= 0.2  # second call waited


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
