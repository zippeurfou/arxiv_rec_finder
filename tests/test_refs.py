from kb.refs import parse_references

MD = """## Body text here.

## References
- J. Zhai et al. (2024) Actions speak louder than words. In ICML.
- G. Zhou et al. (2025) OneRec-v2 technical report. arXiv preprint arXiv:2508.20900.
"""


def test_parse_references():
    refs = parse_references(MD)
    titles = [r["title"] for r in refs]
    assert any("Actions speak louder" in t for t in titles)
    onerec = [r for r in refs if "OneRec" in r["title"]][0]
    assert onerec["arxiv_id"] == "2508.20900"


# Real arxiv2md format: each reference spans multiple lines, entry starts with "- ".
REAL_MD = """## References
- P. Agarwal, A. Badrinath, et al. (2025)
PinRec: outcome-conditioned, multi-token generative retrieval for industry-scale recommendation systems.
Note: arXiv:2504.10507
External Links: 2504.10507
Cited by: [1st item](#S1.I2.i1.p1.1).
- L. Bottou, J. Peters, et al. (2013)
Counterfactual reasoning and learning systems: the example of computational advertising.
Journal of Machine Learning Research 14, pp. 3207-3260.
Cited by: [§5.3](#S5.SS3.SSSx1.p1.1).
"""


def test_parse_references_groups_multiline_entries():
    refs = parse_references(REAL_MD)
    # exactly TWO references, not one-per-line
    assert len(refs) == 2
    first, second = refs
    assert first["title"] == (
        "PinRec: outcome-conditioned, multi-token generative retrieval "
        "for industry-scale recommendation systems"
    )
    assert first["arxiv_id"] == "2504.10507"
    assert second["title"].startswith("Counterfactual reasoning and learning systems")
    assert second["arxiv_id"] is None
