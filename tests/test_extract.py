import filter_affiliations as fa
from kb.extract import extract_paper, Extraction


def fake_llm(prompt: str) -> str:
    return '{"concepts_raw": ["two-tower", "in-batch negatives"], "technical_note": "Problem/method/result."}'


def test_extract_paper():
    e = extract_paper(
        title="X",
        fulltext="...body...",
        vocab_hint=["two-tower-retrieval"],
        llm=fake_llm,
    )
    assert isinstance(e, Extraction)
    assert "two-tower" in e.concepts_raw
    assert e.technical_note.startswith("Problem")


def test_extract_paper_strips_think_block_with_braces():
    # deepseek-r1 style: reasoning contains braces that would break a naive slice
    def thinky_llm(prompt: str) -> str:
        return (
            '<think>Let me consider the set {a, b} and example {"x": 1}...</think>\n'
            '{"concepts_raw": ["two-tower"], "technical_note": "Note."}'
        )

    e = extract_paper(title="X", fulltext="body", vocab_hint=[], llm=thinky_llm)
    assert e.concepts_raw == ["two-tower"]
    assert e.technical_note == "Note."


def test_extract_paper_tolerates_wrapping():
    def wrapping_llm(prompt: str) -> str:
        return 'Sure, here you go:\n```json\n{"concepts_raw": ["cold-start"], "technical_note": "N."}\n```'

    e = extract_paper(
        title="X", fulltext="...body...", vocab_hint=["cold-start"], llm=wrapping_llm
    )
    assert isinstance(e, Extraction)
    assert e.concepts_raw == ["cold-start"]
    assert e.technical_note == "N."


def test_decide_companies_from_emails():
    domains = ["meta.com", "uber.com"]
    assert fa.decide_companies([], ["a@uber.com"], domains) == ["Uber"]
    assert fa.decide_companies([], ["a@gmail.com"], domains) == []


def test_decide_companies_from_affiliations():
    domains = ["meta.com", "uber.com"]
    assert fa.decide_companies(["meta ai research"], [], domains) == ["Meta"]


def test_decide_companies_dedup_sorted():
    domains = ["meta.com", "uber.com"]
    got = fa.decide_companies(["meta"], ["x@uber.com", "y@meta.com"], domains)
    assert got == ["Meta", "Uber"]


def test_get_signals_uses_cache_no_download(monkeypatch):
    called = {"n": 0}

    def boom(_id):
        called["n"] += 1
        raise AssertionError("should not download when cached")

    cache = {
        "2603.06586": {
            "arxiv_id": "2603.06586",
            "affiliations": [],
            "emails": ["x@uber.com"],
        }
    }
    sig = fa.get_signals_cached("2603.06586", cache, pdf_email_fn=boom)
    assert sig["emails"] == ["x@uber.com"]
    assert called["n"] == 0
