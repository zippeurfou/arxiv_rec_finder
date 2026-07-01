from collections import Counter
from pathlib import Path

import yaml


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("-", " ").split())


def load_vocab(path: Path) -> dict[str, list[str]]:
    return yaml.safe_load(Path(path).read_text()) or {}


def _alias_index(vocab: dict[str, list[str]]) -> dict[str, str]:
    idx = {}
    for slug, aliases in vocab.items():
        idx[_norm(slug)] = slug
        for a in aliases:
            idx[_norm(a)] = slug
    return idx


def canonicalize(concepts_raw: list[str], vocab: dict) -> tuple[list[str], list[str]]:
    idx = _alias_index(vocab)
    mapped, unmapped, seen = [], [], set()
    for c in concepts_raw:
        slug = idx.get(_norm(c))
        if slug:
            if slug not in seen:
                seen.add(slug)
                mapped.append(slug)
        else:
            unmapped.append(c)
    return mapped, unmapped


def unmapped_report(all_raw: list[list[str]], vocab: dict) -> list[tuple[str, int]]:
    counter = Counter()
    for raw in all_raw:
        _, unmapped = canonicalize(raw, vocab)
        counter.update(_norm(u) for u in unmapped)
    return counter.most_common()
