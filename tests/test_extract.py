from pathlib import Path

import yaml

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


def test_get_signals_cache_miss_calls_pdf_fn():
    sig = fa.get_signals_cached(
        "2603.06586",
        {},
        pdf_email_fn=lambda aid: ["a@meta.com"],
        affiliations=["Meta AI"],
    )
    assert sig["emails"] == ["a@meta.com"]
    assert sig["affiliations"] == ["Meta AI"]


def test_get_signals_cache_miss_pdf_fn_raises_returns_empty():
    def boom(_id):
        raise RuntimeError("download failed")

    sig = fa.get_signals_cached("2603.06586", {}, pdf_email_fn=boom)
    assert sig["emails"] == []
    assert sig["affiliations"] == []


def test_decide_companies_email_subdomain_match():
    assert fa.decide_companies([], ["x@research.meta.com"], ["meta.com"]) == ["Meta"]


def test_decide_companies_alias_case_insensitive():
    assert fa.decide_companies(["Meta AI Research"], [], ["meta.com"]) == ["Meta"]


def test_decide_companies_yandex_team_domain_normalizes_to_yandex():
    # Yandex publishes from the internal yandex-team.ru domain; the label must
    # normalize to "Yandex", not the raw first-label component "Yandex-team".
    assert fa.decide_companies([], ["x@yandex-team.ru"], ["yandex-team.ru"]) == [
        "Yandex"
    ]


def test_config_catches_yandex_papers():
    # Regression guard: config must allowlist Yandex's real publishing domains
    # (yandex.ru + internal yandex-team.ru), not just the public yandex.com,
    # and both must collapse to a single "Yandex" label.
    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    with open(config_path) as f:
        domains = yaml.safe_load(f)["tech_domains"]
    assert "yandex-team.ru" in domains
    assert "yandex.ru" in domains
    # Real signals from arXiv 2606.08604 (Gryphon, Yandex): 1 corp email + gmails.
    gryphon_emails = [
        "daria.m.tikhonovich@gmail.com",
        "ilyamurzin@yandex-team.ru",
        "olegsorokin.ai@gmail.com",
    ]
    assert fa.decide_companies([], gryphon_emails, domains) == ["Yandex"]
    # A paper carrying both domains must dedup to a single label.
    assert fa.decide_companies([], ["a@yandex.ru", "b@yandex-team.ru"], domains) == [
        "Yandex"
    ]
