# tests/test_acquire.py
from kb.acquire import get_fulltext


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
