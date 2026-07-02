# tests/test_acquire.py
from kb.acquire import _looks_thin, get_fulltext


def test_looks_thin():
    assert _looks_thin("")
    assert _looks_thin("   \n  ")
    assert _looks_thin("short arXiv boilerplate stub with no body")
    assert not _looks_thin("x" * 1000)


class _Resp:
    def __init__(self, text="", content=b""):
        self.text = text
        self.content = content
        self.encoding = ""

    def raise_for_status(self):
        pass


def test_pdf_fulltext_success(monkeypatch):
    import kb.acquire as A

    monkeypatch.setattr(A.requests, "get", lambda *a, **k: _Resp(content=b"%PDF"))

    class _P:
        returncode = 0
        stdout = "x" * 1000

    monkeypatch.setattr(A.subprocess, "run", lambda *a, **k: _P())
    assert len(A._pdf_fulltext("1234.56789")) == 1000


def test_pdf_fulltext_failure_returns_empty(monkeypatch):
    import kb.acquire as A

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(A.requests, "get", boom)
    assert A._pdf_fulltext("1234.56789") == ""


def test_default_fetcher_falls_back_to_pdf_when_thin(monkeypatch):
    import kb.acquire as A

    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    monkeypatch.setattr(A.requests, "get", lambda *a, **k: _Resp(text="thin stub"))
    monkeypatch.setattr(A, "_pdf_fulltext", lambda i: "y" * 1000)
    assert A._default_fetcher("1234.56789") == "y" * 1000


def test_default_fetcher_keeps_arxiv2md_when_substantial(monkeypatch):
    import kb.acquire as A

    body = "z" * 1000
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    monkeypatch.setattr(A.requests, "get", lambda *a, **k: _Resp(text=body))

    def _must_not_run(i):
        raise AssertionError("PDF fallback should not run for substantial text")

    monkeypatch.setattr(A, "_pdf_fulltext", _must_not_run)
    assert A._default_fetcher("1234.56789") == body


def test_uses_cache_and_fetcher(tmp_path):
    calls = []

    def fake_fetch(arxiv_id):
        calls.append(arxiv_id)
        return f"# body {arxiv_id}"

    # first call fetches + writes cache
    md1 = get_fulltext("2606.31031", cache_dir=tmp_path, fetcher=fake_fetch)
    # second call reads cache, no fetch
    md2 = get_fulltext("2606.31031", cache_dir=tmp_path, fetcher=fake_fetch)
    assert md1 == md2 == "# body 2606.31031"
    assert calls == ["2606.31031"]
    assert (tmp_path / "2606.31031.md").exists()


def test_empty_result_is_not_cached(tmp_path):
    calls = []

    def empty_fetch(arxiv_id):
        calls.append(arxiv_id)
        return "   \n"

    # empty/whitespace result must not be cached, so it retries next run
    md1 = get_fulltext("1234.56789", cache_dir=tmp_path, fetcher=empty_fetch)
    md2 = get_fulltext("1234.56789", cache_dir=tmp_path, fetcher=empty_fetch)
    assert md1 == md2 == "   \n"
    assert calls == ["1234.56789", "1234.56789"]  # fetched twice, never cached
    assert not (tmp_path / "1234.56789.md").exists()
