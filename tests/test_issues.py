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


@pytest.mark.parametrize(
    "raw_title,expected",
    [
        (
            "[arXiv 2026] GenPage: End-to-End Generative Homepage at Netflix (Netflix)",
            "GenPage: End-to-End Generative Homepage at Netflix",
        ),
        (
            "[arXiv 2018] Aesthetic Features for Photo Recommendation (Shopify)",
            "Aesthetic Features for Photo Recommendation",
        ),
        ("[arXiv 2026] Foo (Google, Meta)", "Foo"),
        ("Plain Title With No Decoration", "Plain Title With No Decoration"),
    ],
)
def test_clean_title(raw_title, expected):
    from kb.issues import _clean_title

    assert _clean_title(raw_title) == expected


def test_iter_issues_requests_ascending_order(monkeypatch):
    from kb.issues import iter_issues

    calls = {}

    class FakeLabel:
        def __init__(self, name):
            self.name = name

    class FakeIssue:
        def __init__(self, num):
            self.number = num
            self.title = "[arXiv 2026] Paper (Netflix)"
            self.body = "**URL:** https://arxiv.org/abs/2606.00001v1\n**Summary:** s."
            self.labels = [FakeLabel("Netflix"), FakeLabel("2026")]

    class FakeRepo:
        def get_issues(self, **kw):
            calls.update(kw)
            return [FakeIssue(1), FakeIssue(2), FakeIssue(3)]

    class FakeGithub:
        def __init__(self, token):
            pass

        def get_repo(self, name):
            return FakeRepo()

    import github

    monkeypatch.setattr(github, "Github", FakeGithub)
    recs = list(iter_issues("owner/repo", "tok", since_issue=1))
    # ascending order requested (so --limit batches + watermark don't skip papers)
    assert calls.get("sort") == "created"
    assert calls.get("direction") == "asc"
    # since_issue filter still applied
    assert [r.issue for r in recs] == [2, 3]


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
