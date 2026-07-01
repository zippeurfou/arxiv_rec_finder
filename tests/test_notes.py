import json

from kb.notes import index_line, render_concept_note, render_paper_note


def test_render_paper_note_has_frontmatter_and_links():
    md = render_paper_note(
        arxiv_id="2606.31031",
        title="GenPage",
        year=2026,
        companies=["Netflix"],
        url="https://arxiv.org/abs/2606.31031",
        issue=2457,
        concepts_raw=["two-tower"],
        concepts=["two-tower-retrieval"],
        summary="S.",
        technical_note="T.",
        references=[{"title": "R", "arxiv_id": None}],
        citation_count=3,
    )
    assert md.startswith("---")
    assert "arxiv_id: 2606.31031" in md
    assert "[[two-tower-retrieval]]" in md
    assert "## Technical note" in md


def test_index_line_is_json():
    line = index_line(
        arxiv_id="x",
        title="T",
        year=2026,
        companies=["Netflix"],
        concepts=["cold-start"],
        url="u",
        issue=1,
    )
    assert json.loads(line)["concepts"] == ["cold-start"]


def test_index_line_single_line():
    line = index_line(
        arxiv_id="x",
        title="T",
        year=2026,
        companies=["Netflix"],
        concepts=["cold-start", "two-tower-retrieval"],
        url="u",
        issue=1,
    )
    assert "\n" not in line
    assert json.loads(line)["concepts"] == ["cold-start", "two-tower-retrieval"]


def test_render_concept_note_has_backlinks():
    md = render_concept_note(
        slug="two-tower-retrieval",
        aliases=["two-tower", "dual-encoder"],
        intro="A retrieval architecture.",
        papers=[("2606.31031", "GenPage", 2026, ["Netflix"])],
    )
    assert "[[2606.31031]]" in md
    assert "## Papers" in md
