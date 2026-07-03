import backfill as B


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
