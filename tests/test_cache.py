# tests/test_cache.py
import cache as C


def test_compact_collapses_duplicates_keeps_latest(tmp_path):
    p = tmp_path / "c.jsonl"
    C.append_record(p, {"arxiv_id": "1", "emails": ["old@meta.com"]})
    C.append_record(p, {"arxiv_id": "1", "emails": ["new@meta.com"]})
    C.compact(p)
    lines = [ln for ln in p.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    loaded = C.load_cache(p)
    assert loaded["1"]["emails"] == ["new@meta.com"]
    assert not (tmp_path / "c.jsonl.tmp").exists()


def test_compact_sorted_by_arxiv_id(tmp_path):
    p = tmp_path / "c.jsonl"
    for aid in ("2", "1", "3"):
        C.append_record(p, {"arxiv_id": aid, "emails": []})
    C.compact(p)
    import json

    ids = [
        json.loads(ln)["arxiv_id"] for ln in p.read_text().splitlines() if ln.strip()
    ]
    assert ids == ["1", "2", "3"]


def test_load_skips_blank_lines(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text('{"arxiv_id":"1","emails":[]}\n\n   \n')
    loaded = C.load_cache(p)
    assert set(loaded) == {"1"}


def test_unicode_roundtrip(tmp_path):
    p = tmp_path / "c.jsonl"
    rec = {
        "arxiv_id": "1",
        "affiliations": ["Universidad de Málaga"],
        "emails": ["josé@example.com"],
    }
    C.append_record(p, rec)
    loaded = C.load_cache(p)
    assert loaded["1"]["affiliations"] == ["Universidad de Málaga"]
    assert loaded["1"]["emails"] == ["josé@example.com"]
    raw = p.read_bytes()
    assert "Málaga".encode() in raw
    assert "josé".encode() in raw


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
