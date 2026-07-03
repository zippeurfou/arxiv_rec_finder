# tests/test_cache.py
import cache as C


def test_roundtrip_append_and_load(tmp_path):
    p = tmp_path / "email_cache.jsonl"
    rec = {
        "arxiv_id": "2603.06586",
        "title": "T",
        "published": "2026-03-01",
        "url": "https://arxiv.org/abs/2603.06586",
        "affiliations": [],
        "emails": ["x@uber.com"],
        "checked": "2026-07-03",
    }
    C.append_record(p, rec)
    loaded = C.load_cache(p)
    assert "2603.06586" in loaded
    assert loaded["2603.06586"]["emails"] == ["x@uber.com"]


def test_load_missing_file_returns_empty(tmp_path):
    assert C.load_cache(tmp_path / "nope.jsonl") == {}


def test_append_is_idempotent_last_wins(tmp_path):
    p = tmp_path / "c.jsonl"
    C.append_record(p, {"arxiv_id": "1", "emails": []})
    C.append_record(p, {"arxiv_id": "1", "emails": ["a@meta.com"]})
    loaded = C.load_cache(p)
    assert loaded["1"]["emails"] == ["a@meta.com"]  # later line wins


def test_skips_malformed_lines(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text('{"arxiv_id":"1","emails":[]}\nNOT JSON\n')
    loaded = C.load_cache(p)
    assert set(loaded) == {"1"}
