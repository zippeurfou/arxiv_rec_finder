from kb.relevance import is_recsys_relevant


def test_relevant_positives():
    assert is_recsys_relevant("A two-tower retrieval model", "for recommendation")
    assert is_recsys_relevant("Cold-start CTR prediction for ads ranking", "")
    assert is_recsys_relevant("Sequential recommendation with transformers", "")
    assert is_recsys_relevant("Generative retrieval with semantic IDs", "")
    assert is_recsys_relevant(
        "", "We study collaborative filtering for personalization"
    )


def test_relevant_negatives():
    assert not is_recsys_relevant(
        "A theorem on optimal transport", "convergence proofs"
    )
    assert not is_recsys_relevant(
        "Protein-ligand binding free energy", "molecular dynamics"
    )
    assert not is_recsys_relevant("Video diffusion for text to image", "")
    # bare "ad"/"AD" must NOT trigger (no false positive on ad hoc / auto-diff)
    assert not is_recsys_relevant("Ad hoc theorem proving", "reverse-mode AD")
