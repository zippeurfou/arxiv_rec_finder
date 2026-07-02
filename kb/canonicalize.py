from collections import Counter
from pathlib import Path

import yaml


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("-", " ").split())


def load_vocab(path: Path) -> dict:
    """Load vocabulary.yaml. Each value is either a list of aliases (legacy form)
    or a mapping ``{aliases: [...], intro: "..."}``. Both are supported."""
    return yaml.safe_load(Path(path).read_text()) or {}


def aliases_of(value) -> list[str]:
    """Aliases for a vocab entry, accepting the legacy list or the mapping form."""
    if isinstance(value, dict):
        return list(value.get("aliases") or [])
    return list(value or [])


def intro_of(value) -> str:
    """Intro/description for a vocab entry (empty for the legacy list form)."""
    if isinstance(value, dict):
        return value.get("intro") or ""
    return ""


def _alias_index(vocab: dict) -> dict[str, str]:
    idx = {}
    for slug, value in vocab.items():
        idx[_norm(slug)] = slug
        for a in aliases_of(value):
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
