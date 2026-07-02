from kb.canonicalize import (
    _norm,
    aliases_of,
    canonicalize,
    intro_of,
    unmapped_report,
)

VOCAB = {
    "two-tower-retrieval": ["two-tower", "dual-encoder"],
    "cold-start": ["cold start"],
}


def test_canonicalize_maps_aliases():
    assert canonicalize(["Two-Tower", "cold start", "novel-thing"], VOCAB) == (
        ["two-tower-retrieval", "cold-start"],
        ["novel-thing"],
    )


def test_unmapped_report_counts():
    rep = unmapped_report([["novel-thing"], ["novel-thing"], ["cold start"]], VOCAB)
    assert rep[0] == ("novel thing", 2)


def test_canonicalize_dedups_and_preserves_order():
    vocab = {
        "two-tower-retrieval": ["two-tower", "two tower"],
        "cold-start": ["cold start"],
    }
    mapped, _ = canonicalize(["two-tower", "Two Tower", "cold start"], vocab)
    assert mapped == ["two-tower-retrieval", "cold-start"]


def test_norm_is_case_and_hyphen_insensitive():
    assert _norm("Two-Tower") == _norm("two tower") == "two tower"


def test_aliases_and_intro_of_both_shapes():
    # legacy list form
    assert aliases_of(["a", "b"]) == ["a", "b"]
    assert intro_of(["a"]) == ""
    # new mapping form
    v = {"aliases": ["x", "y"], "intro": "desc"}
    assert aliases_of(v) == ["x", "y"]
    assert intro_of(v) == "desc"
    # missing / None
    assert aliases_of(None) == []
    assert intro_of({"aliases": ["x"]}) == ""


def test_canonicalize_works_with_dict_shape_vocab():
    vocab = {
        "two-tower-retrieval": {
            "aliases": ["two-tower", "dual-encoder"],
            "intro": "Separate user/item encoders.",
        }
    }
    mapped, unmapped = canonicalize(["Dual-Encoder", "novel"], vocab)
    assert mapped == ["two-tower-retrieval"]
    assert unmapped == ["novel"]
