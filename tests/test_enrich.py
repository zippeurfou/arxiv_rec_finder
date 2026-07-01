from kb.enrich import parse_s2_references, safe_enrich

S2 = {
    "data": [
        {
            "citedPaper": {
                "title": "Aesthetic-based Clothing Recommendation",
                "year": 2018,
                "externalIds": {"ArXiv": "1809.05822", "DOI": "10.1145/x"},
            }
        },
        {"citedPaper": {"title": "No IDs here", "year": 2016, "externalIds": {}}},
    ]
}


def test_parse_s2_references():
    refs = parse_s2_references(S2)
    assert refs[0] == {
        "title": "Aesthetic-based Clothing Recommendation",
        "year": 2018,
        "arxiv_id": "1809.05822",
        "doi": "10.1145/x",
    }
    assert refs[1]["arxiv_id"] is None


def test_safe_enrich_swallows_errors():
    def boom(_):
        raise RuntimeError("429")

    assert safe_enrich("1809.00060", getter=boom) == {
        "references": [],
        "citation_count": None,
    }
