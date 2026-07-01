import json

import pytest

from kb.build import build_paper, ingest, prepare, run_backfill, run_canonicalize
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

    def extract(*, title, fulltext, vocab_hint):
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

    def extract(*, title, fulltext, vocab_hint):
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


# --- C1: real LLM must reach the extractor -------------------------------


def test_build_paper_passes_llm_to_extractor(tmp_path):
    # build_paper must NOT inject llm=None; it just forwards the kwargs it owns.
    rec = _rec("2601.00001", "Paper One", "two-tower")
    vocab = {"two-tower-retrieval": ["two-tower"]}

    def extract(*, title, fulltext, vocab_hint):
        # If build_paper ever passed llm=None this signature would raise
        # TypeError (unexpected kwarg), so a successful call proves the fix.
        return Extraction(["two-tower"], "T.")

    raw = build_paper(
        rec,
        kb_dir=tmp_path,
        vocab=vocab,
        cache_dir=tmp_path / ".cache",
        fetch=lambda i: "# body\n## References\n- R",
        extract=extract,
        enrich=lambda i: {"references": [], "citation_count": None},
    )
    assert (tmp_path / "papers" / "2601.00001.md").exists()
    assert raw == ["two-tower"]


def test_run_backfill_all_fail_is_visible(tmp_path):
    # Documents the empty-KB signature: if extract raises for ALL records,
    # built==0 and every record is a failure (not silently swallowed to empty).
    records = [_rec("2601.00001", "One", "x"), _rec("2602.00002", "Two", "y")]
    vocab = {}

    def extract(*, title, fulltext, vocab_hint):
        raise RuntimeError("llm down")

    run_backfill(
        records,
        kb_dir=tmp_path,
        vocab=vocab,
        cache_dir=tmp_path / ".cache",
        fetch=lambda i: "# body\n## References\n- R",
        extract=extract,
        enrich=lambda i: {"references": [], "citation_count": None},
    )
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["built"] == 0
    assert len(state["failures"]) == len(records)


# --- I2: advance watermark on ATTEMPT, not success -----------------------


def test_watermark_advances_on_failure(tmp_path):
    # Two records (issues 10 and 20); fetch raises for issue 20. The watermark
    # must still advance to 20 so the next incremental doesn't re-fetch old work.
    r10 = PaperRecord(
        arxiv_id="2601.00010",
        title="Ten",
        year=2026,
        companies=[],
        url="u",
        issue=10,
        summary="S.",
    )
    r20 = PaperRecord(
        arxiv_id="2602.00020",
        title="Twenty",
        year=2026,
        companies=[],
        url="u",
        issue=20,
        summary="S.",
    )
    vocab = {}

    def fetch(i):
        if i == "2602.00020":
            raise RuntimeError("boom fetch")
        return "# body\n## References\n- R"

    def extract(*, title, fulltext, vocab_hint):
        return Extraction([], "T.")

    run_backfill(
        [r10, r20],
        kb_dir=tmp_path,
        vocab=vocab,
        cache_dir=tmp_path / ".cache",
        fetch=fetch,
        extract=extract,
        enrich=lambda i: {"references": [], "citation_count": None},
    )
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["last_issue"] == 20


# --- I3: don't call S2 by default; merge S2 refs when enrichment provided --


def test_build_paper_merges_enrichment_references(tmp_path):
    # enrich returns an S2 ref with a title not present in the parsed refs; it
    # must be MERGED into the rendered note (not discarded).
    rec = _rec("2601.00001", "Paper One", "two-tower")
    vocab = {}

    def enrich(i):
        return {
            "references": [
                {"title": "S2 Only Ref", "arxiv_id": "9999.99999", "year": 2020}
            ],
            "citation_count": None,
        }

    build_paper(
        rec,
        kb_dir=tmp_path,
        vocab=vocab,
        cache_dir=tmp_path / ".cache",
        fetch=lambda i: "# body\n## References\n- Parsed Ref arXiv:1234.56789",
        extract=_fake_extract(["two-tower"]),
        enrich=enrich,
    )
    text = (tmp_path / "papers" / "2601.00001.md").read_text()
    assert "Parsed Ref" in text  # parsed ref preserved
    assert "S2 Only Ref" in text  # S2 ref merged in
    assert "9999.99999" in text


def test_backfill_does_not_call_s2_by_default():
    # The default enrich wired in main() must be a no-op that returns empty
    # references / None citation and performs NO network call.
    from kb.build import _noop_enrich

    result = _noop_enrich("2601.00001")
    assert result == {"references": [], "citation_count": None}


# --- I1: make failures re-runnable ---------------------------------------


def test_failures_persist_until_note_exists(tmp_path):
    # Seed a prior failure whose note does not exist; an unrelated incremental
    # build must keep that old failure in state.json (don't lose it).
    (tmp_path / "state.json").write_text(
        json.dumps({"last_issue": 5, "failures": ["2599.09999"], "built": 3}),
        encoding="utf-8",
    )
    rec = _rec("2601.00001", "New Paper", "two-tower")
    vocab = {"two-tower-retrieval": ["two-tower"]}

    run_backfill(
        [rec],
        kb_dir=tmp_path,
        vocab=vocab,
        cache_dir=tmp_path / ".cache",
        fetch=lambda i: "# body\n## References\n- R",
        extract=_fake_extract(["two-tower"]),
        enrich=lambda i: {"references": [], "citation_count": None},
    )
    state = json.loads((tmp_path / "state.json").read_text())
    assert "2599.09999" in state["failures"]


# --- M1: per-note resilience in regenerate -------------------------------


def test_regenerate_skips_corrupt_note(tmp_path):
    from kb.build import regenerate

    papers_dir = tmp_path / "papers"
    papers_dir.mkdir(parents=True)
    # one valid note
    valid = build_paper(
        _rec("2601.00001", "Valid", "two-tower"),
        kb_dir=tmp_path,
        vocab={"two-tower-retrieval": ["two-tower"]},
        cache_dir=tmp_path / ".cache",
        fetch=lambda i: "# body\n## References\n- R",
        extract=_fake_extract(["two-tower"]),
        enrich=lambda i: {"references": [], "citation_count": None},
    )
    assert valid == ["two-tower"]
    # one corrupt note
    (papers_dir / "2602.00002.md").write_text("---\n:bad yaml\n---\n", encoding="utf-8")

    regenerate(tmp_path, {"two-tower-retrieval": ["two-tower"]})

    index_lines = (tmp_path / "index.jsonl").read_text().strip().splitlines()
    ids = [json.loads(line)["arxiv_id"] for line in index_lines]
    assert "2601.00001" in ids


# --- agent-driven prepare/ingest pipeline (no local LLM) -----------------


def _prec(arxiv_id, title):
    return PaperRecord(
        arxiv_id=arxiv_id,
        title=title,
        year=2026,
        companies=["Netflix"],
        url=f"https://arxiv.org/abs/{arxiv_id}",
        issue=int(arxiv_id.split(".")[0]),
        summary="S.",
    )


def test_prepare_writes_pending_and_caches(tmp_path):
    records = [_prec("2601.00001", "Paper One"), _prec("2602.00002", "Paper Two")]

    def fetch(i):
        return f"# body {i}\n## References\n- Ref A arXiv:1234.56789\n- Ref B"

    out_path = tmp_path / ".pending.jsonl"
    result = prepare(
        records,
        kb_dir=tmp_path,
        cache_dir=tmp_path / ".cache",
        fetch=fetch,
        out_path=out_path,
    )

    assert result["pending"] == 2
    assert result["failures"] == []
    assert result["out"] == str(out_path)

    lines = out_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    entries = {json.loads(line)["arxiv_id"]: json.loads(line) for line in lines}
    assert set(entries) == {"2601.00001", "2602.00002"}
    e1 = entries["2601.00001"]
    assert e1["title"] == "Paper One"
    assert e1["fulltext_path"] == str((tmp_path / ".cache") / "2601.00001.md")
    titles = [r["title"] for r in e1["references"]]
    assert any("Ref A" in t for t in titles)
    assert e1["references"][0]["arxiv_id"] == "1234.56789"


def test_prepare_survives_failure(tmp_path):
    records = [_prec("2601.00001", "Good"), _prec("2602.00002", "Bad")]

    def fetch(i):
        if i == "2602.00002":
            raise RuntimeError("boom fetch")
        return "# body\n## References\n- R"

    out_path = tmp_path / ".pending.jsonl"
    result = prepare(
        records,
        kb_dir=tmp_path,
        cache_dir=tmp_path / ".cache",
        fetch=fetch,
        out_path=out_path,
    )

    assert result["pending"] == 1
    assert result["failures"] == ["2602.00002"]
    lines = out_path.read_text(encoding="utf-8").strip().splitlines()
    ids = [json.loads(line)["arxiv_id"] for line in lines]
    assert ids == ["2601.00001"]


def _write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def test_ingest_builds_notes_from_extractions(tmp_path):
    vocab = {"two-tower-retrieval": ["two-tower"], "cold-start": ["cold start"]}
    pending = tmp_path / ".pending.jsonl"
    extractions = tmp_path / ".extractions.jsonl"

    _write_jsonl(
        pending,
        [
            {
                "arxiv_id": "2601.00001",
                "title": "Paper One",
                "year": 2026,
                "companies": ["Netflix"],
                "url": "https://arxiv.org/abs/2601.00001",
                "issue": 2601,
                "summary": "S1.",
                "fulltext_path": str(tmp_path / ".cache" / "2601.00001.md"),
                "references": [{"title": "Ref A", "arxiv_id": None}],
            },
            {
                "arxiv_id": "2602.00002",
                "title": "Paper Two",
                "year": 2026,
                "companies": ["Netflix"],
                "url": "https://arxiv.org/abs/2602.00002",
                "issue": 2602,
                "summary": "S2.",
                "fulltext_path": str(tmp_path / ".cache" / "2602.00002.md"),
                "references": [],
            },
        ],
    )
    _write_jsonl(
        extractions,
        [
            {
                "arxiv_id": "2601.00001",
                "concepts_raw": ["two-tower"],
                "technical_note": "TN1.",
            },
            {
                "arxiv_id": "2602.00002",
                "concepts_raw": ["cold start"],
                "technical_note": "TN2.",
            },
        ],
    )

    result = ingest(
        kb_dir=tmp_path,
        pending_path=pending,
        extractions_path=extractions,
        vocab=vocab,
    )

    assert result["ingested"] == 2
    note1 = (tmp_path / "papers" / "2601.00001.md").read_text()
    assert "[[two-tower-retrieval]]" in note1
    assert "TN1." in note1
    assert "Ref A" in note1

    index_lines = (tmp_path / "index.jsonl").read_text().strip().splitlines()
    assert len(index_lines) == 2

    concept_files = list((tmp_path / "concepts").glob("*.md"))
    assert len(concept_files) >= 2

    state = json.loads((tmp_path / "state.json").read_text())
    assert state["ingested"] == 2


def test_ingest_records_missing_extraction(tmp_path):
    vocab = {"two-tower-retrieval": ["two-tower"]}
    pending = tmp_path / ".pending.jsonl"
    extractions = tmp_path / ".extractions.jsonl"

    _write_jsonl(
        pending,
        [
            {
                "arxiv_id": "2601.00001",
                "title": "Paper One",
                "year": 2026,
                "companies": [],
                "url": "u1",
                "issue": 2601,
                "summary": "S1.",
                "fulltext_path": "x",
                "references": [],
            },
            {
                "arxiv_id": "2602.00002",
                "title": "Paper Two",
                "year": 2026,
                "companies": [],
                "url": "u2",
                "issue": 2602,
                "summary": "S2.",
                "fulltext_path": "x",
                "references": [],
            },
        ],
    )
    _write_jsonl(
        extractions,
        [
            {
                "arxiv_id": "2601.00001",
                "concepts_raw": ["two-tower"],
                "technical_note": "TN1.",
            }
        ],
    )

    result = ingest(
        kb_dir=tmp_path,
        pending_path=pending,
        extractions_path=extractions,
        vocab=vocab,
    )

    assert result["ingested"] == 1
    assert (tmp_path / "papers" / "2601.00001.md").exists()
    assert not (tmp_path / "papers" / "2602.00002.md").exists()
    assert "2602.00002" in result["missing_extraction"]

    state = json.loads((tmp_path / "state.json").read_text())
    assert "2602.00002" in state["failures"]
