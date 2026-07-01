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
