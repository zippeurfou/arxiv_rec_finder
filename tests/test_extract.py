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
