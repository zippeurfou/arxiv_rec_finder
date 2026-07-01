import pytest

from kb.issues import PaperRecord, _clean_summary, parse_issue

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


@pytest.mark.parametrize(
    "raw,expected",
    [
        # genuine preambles -> stripped
        (
            "Here is a 3-sentence summary of the paper:\nIt does X. It does Y.",
            "It does X. It does Y.",
        ),
        ("Here's a summary: It works well.", "It works well."),
        (
            "Sure! Here is a 3-sentence summary:\nReal content here.",
            "Real content here.",
        ),
        # legit prose that must NOT be over-stripped (period before 'summary' blocks the match)
        (
            "Here is a novel approach. Our summary metric improves.",
            "Here is a novel approach. Our summary metric improves.",
        ),
        (
            "A method for ranking. It beats baselines.",
            "A method for ranking. It beats baselines.",
        ),
    ],
)
def test_clean_summary(raw, expected):
    assert _clean_summary(raw) == expected


def _body(url, summary):
    return f"**Title:** T\n**URL:** {url}\n\n**Summary:**\n{summary}"


@pytest.mark.parametrize(
    "number,title,body,labels,expect_id,expect_year,expect_companies",
    [
        (
            1,
            "T",
            "no arxiv here",
            ["Netflix"],
            None,
            None,
            None,
        ),  # no id -> None record
        (
            2,
            "T",
            _body("https://arxiv.org/pdf/1809.00060v1", "S."),
            ["Shopify", "2018"],
            "1809.00060",
            2018,
            ["Shopify"],
        ),
        (
            3,
            "T",
            _body("https://arxiv.org/abs/2606.31031v1", "S."),
            ["Netflix"],
            "2606.31031",
            None,
            ["Netflix"],
        ),
    ],
)
def test_parse_issue_edges(
    number, title, body, labels, expect_id, expect_year, expect_companies
):
    rec = parse_issue(number, title, body, labels)
    if expect_id is None:
        assert rec is None
        return
    assert rec.arxiv_id == expect_id
    assert rec.year == expect_year
    assert rec.companies == expect_companies
