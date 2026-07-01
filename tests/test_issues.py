from kb.issues import PaperRecord, parse_issue

BODY = """🧠 **Title:** GenPage
📅 **Published:** 2026-06-30T02:00:05Z
🔗 **URL:** https://arxiv.org/abs/2606.31031v1
🧑‍💼 **Companies:** Netflix

📝 **Summary:**
Here is a 3-sentence summary of the Netflix GenPage paper:
It does X. It does Y."""


def test_parse_issue():
    r = parse_issue(
        number=2457,
        title="[arXiv 2026] GenPage (Netflix)",
        body=BODY,
        labels=["Netflix", "2026"],
    )
    assert isinstance(r, PaperRecord)
    assert r.arxiv_id == "2606.31031"
    assert r.year == 2026
    assert r.companies == ["Netflix"]
    assert r.issue == 2457
    # leaked preamble stripped
    assert not r.summary.lower().startswith("here is a 3-sentence")
    assert "It does X." in r.summary
