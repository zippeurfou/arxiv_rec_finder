import re

_ARXIV = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)


def extract_arxiv_id(text: str) -> str | None:
    """Extract a bare arXiv id (no version) from a URL/body; handles /abs/ and /pdf/."""
    if not text:
        return None
    m = _ARXIV.search(text)
    return m.group(1) if m else None
