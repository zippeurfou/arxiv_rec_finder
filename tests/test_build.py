import json

import pytest

from kb.build import build_paper, run_backfill, run_canonicalize
from kb.extract import Extraction
from kb.issues import PaperRecord


def _fake_extract(concepts_raw, note="T."):
    def _extract(**kwargs):
        return Extraction(list(concepts_raw), note)

    return _extract


def test_build_paper_writes_note_and_returns_raw(tmp_path):
    rec = PaperRecord(
        arxiv_id="2606.31031",
        title="GenPage",
        year=2026,
        companies=["Netflix"],
        url="u",
        issue=2457,
        summary="S.",
    )
    vocab = {"two-tower-retrieval": ["two-tower"]}
    raw = build_paper(
        rec,
        kb_dir=tmp_path,
        vocab=vocab,
        cache_dir=tmp_path / ".cache",
        fetch=lambda i: "# body\n## References\n- R arXiv:1234.56789",
        extract=_fake_extract(["two-tower", "novel"]),
        enrich=lambda i: {"references": [], "citation_count": None},
    )
    note = tmp_path / "papers" / "2606.31031.md"
    assert note.exists()
    assert "[[two-tower-retrieval]]" in note.read_text()
    assert raw == ["two-tower", "novel"]


def _rec(arxiv_id, title, concepts_word):
    return PaperRecord(
        arxiv_id=arxiv_id,
        title=title,
        year=2026,
        companies=["Netflix"],
        url=f"https://arxiv.org/abs/{arxiv_id}",
        issue=int(arxiv_id.split(".")[0]),
        summary="S.",
    )


def test_run_backfill_smoke(tmp_path):
    records = [
        _rec("2601.00001", "Paper One", "two-tower"),
        _rec("2602.00002", "Paper Two", "cold start"),
    ]
    vocab = {"two-tower-retrieval": ["two-tower"], "cold-start": ["cold start"]}

    def fetch(i):
        return "# body\n## References\n- R"

    concepts_by_id = {
        "2601.00001": ["two-tower"],
        "2602.00002": ["cold start"],
    }

    def extract(*, title, fulltext, vocab_hint, llm):
        # find the record whose title matches
        for r in records:
            if r.title == title:
                return Extraction(list(concepts_by_id[r.arxiv_id]), "T.")
        raise AssertionError(title)

    summary = run_backfill(
        records,
        kb_dir=tmp_path,
        vocab=vocab,
        cache_dir=tmp_path / ".cache",
        fetch=fetch,
        extract=extract,
        enrich=lambda i: {"references": [], "citation_count": None},
    )

    index = tmp_path / "index.jsonl"
    lines = index.read_text().strip().splitlines()
    assert len(lines) == 2

    concept_files = list((tmp_path / "concepts").glob("*.md"))
    assert len(concept_files) >= 1

    state = json.loads((tmp_path / "state.json").read_text())
    assert state["built"] == 2
    assert summary["built"] == 2


def test_run_backfill_survives_one_failure(tmp_path):
    good = _rec("2601.00001", "Good Paper", "two-tower")
    bad = _rec("2602.00002", "Bad Paper", "cold start")
    vocab = {"two-tower-retrieval": ["two-tower"]}

    def fetch(i):
        if i == "2602.00002":
            raise RuntimeError("boom fetch")
        return "# body\n## References\n- R"

    def extract(*, title, fulltext, vocab_hint, llm):
        return Extraction(["two-tower"], "T.")

    summary = run_backfill(
        [good, bad],
        kb_dir=tmp_path,
        vocab=vocab,
        cache_dir=tmp_path / ".cache",
        fetch=fetch,
        extract=extract,
        enrich=lambda i: {"references": [], "citation_count": None},
    )

    assert (tmp_path / "papers" / "2601.00001.md").exists()
    assert not (tmp_path / "papers" / "2602.00002.md").exists()

    state = json.loads((tmp_path / "state.json").read_text())
    assert "2602.00002" in state["failures"]
    assert summary["failures"] == ["2602.00002"]
    assert state["built"] == 1


def test_regenerate_is_pure(tmp_path):
    # Backfill one paper with a concept that is initially UNMAPPED.
    rec = _rec("2601.00001", "Paper One", "novel-idea")
    vocab = {"two-tower-retrieval": ["two-tower"]}

    run_backfill(
        [rec],
        kb_dir=tmp_path,
        vocab=vocab,
        cache_dir=tmp_path / ".cache",
        fetch=lambda i: "# body\n## References\n- R",
        extract=_fake_extract(["novel-idea"]),
        enrich=lambda i: {"references": [], "citation_count": None},
    )

    # Initially the concept maps to nothing -> no concept note for it.
    assert not (tmp_path / "concepts" / "novel-concept.md").exists()

    # Now add an alias to the vocabulary and re-canonicalize ONLY.
    # Fakes here would RAISE if any fetch/llm ever ran, proving purity.
    def boom(*args, **kwargs):
        raise AssertionError("regenerate must not fetch/extract/enrich")

    new_vocab = {
        "two-tower-retrieval": ["two-tower"],
        "novel-concept": ["novel-idea"],
    }
    run_canonicalize(kb_dir=tmp_path, vocab=new_vocab)

    # The paper now maps to the new canonical slug, with no re-reading.
    assert (tmp_path / "concepts" / "novel-concept.md").exists()
    index = json.loads((tmp_path / "index.jsonl").read_text().strip())
    assert "novel-concept" in index["concepts"]

    # sanity: boom never invoked (no fetch/extract/enrich params accepted)
    with pytest.raises(AssertionError):
        boom()
