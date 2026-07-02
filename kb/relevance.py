"""Lightweight recsys-relevance heuristic for filtering the discovery feed.

The CI query matches broad terms (recommender/ranking/retrieval/personalization),
which lets a lot of generic LLM / vision / agent papers through. This is a
conservative INCLUSION filter: keep a paper if its title or summary shows a
recommendation-systems signal. It is intentionally recall-biased -- when in doubt
it keeps the paper -- so real recsys work is not dropped. Off-domain papers that
happen to contain a signal term still slip through; that is an acceptable trade to
avoid false negatives.
"""

import re

# Recsys / ranking / retrieval signal terms. Matched case-insensitively on
# word-ish boundaries against title + summary.
_SIGNALS = [
    r"recommend\w*",
    r"recsys",
    r"collaborative filtering",
    r"click[- ]?through",
    r"\bctr\b",
    r"\bcvr\b",
    r"conversion rate",
    r"cold[- ]?start",
    r"two[- ]?tower",
    r"dual[- ]?encoder",
    r"personaliz\w*",
    r"learning[- ]to[- ]rank",
    r"\bltr\b",
    r"user[- ]?item",
    r"item[- ]?to[- ]?item",
    r"sequential recommendation",
    r"session[- ]based",
    r"next[- ]item",
    r"candidate generation",
    r"user (behavior|behaviour|engagement|interest)",
    r"e[- ]?commerce",
    r"\bads?\b",
    r"advertis\w*",
    r"sponsored",
    r"feed ranking",
    r"news feed",
    r"ranking (model|system|function)",
    r"retrieval (model|system|stage|augmented recommendation)",
    r"embedding[- ]based retrieval",
    r"matching (model|network)",
    r"semantic id",
    r"generative (recommendation|retrieval)",
]
_PATTERN = re.compile("|".join(_SIGNALS), re.IGNORECASE)


def is_recsys_relevant(title: str, summary: str) -> bool:
    """True if the title/summary shows a recommendation-systems signal."""
    text = f"{title or ''}\n{summary or ''}"
    return bool(_PATTERN.search(text))
