import re

# arxiv2md renders each reference as a multi-line entry:
#   - <authors> (<year>)
#   <title>.
#   [Note: arXiv:<id>] / [External Links: <id>] / <venue> / <pages>
#   Cited by: [...]
# Entries begin with a "- " (or "* ") bullet; continuation lines have no bullet.

_ENTRY_ARXIV = re.compile(r"arxiv:\s*(\d{4}\.\d{4,5})", re.IGNORECASE)
_EXT_ARXIV = re.compile(r"external links:\s*(\d{4}\.\d{4,5})", re.IGNORECASE)
_ANY_ARXIV = re.compile(r"\b(\d{4}\.\d{4,5})\b")
_CITED_BY = re.compile(r"^cited by:", re.IGNORECASE)
_LINK_ONLY = re.compile(r"^\[[^\]]*\]\([^)]*\)[.,]?$")  # stray markdown-link line


def _entry_arxiv(entry_text: str) -> str | None:
    for rx in (_ENTRY_ARXIV, _EXT_ARXIV, _ANY_ARXIV):
        m = rx.search(entry_text)
        if m:
            return m.group(1)
    return None


def parse_references(markdown: str) -> list[dict]:
    """Parse the arxiv2md References section into one dict per reference:
    {"title": <paper title, best effort>, "arxiv_id": <id or None>}.
    Multi-line entries are grouped by their leading "- "/"* " bullet.
    """
    m = re.search(r"##+\s*References\s*(.*)", markdown, re.DOTALL | re.IGNORECASE)
    if not m:
        return []

    entries: list[list[str]] = []
    current: list[str] = []
    for raw in m.group(1).splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("- ", "* ")):
            if current:
                entries.append(current)
            current = [line[2:].strip()]
        elif current:
            current.append(line)
        # lines before the first bullet are ignored
    if current:
        entries.append(current)

    out: list[dict] = []
    for lines in entries:
        # drop trailing "Cited by:" / stray link-only continuation lines for the title
        body = [
            ln for ln in lines if not _CITED_BY.match(ln) and not _LINK_ONLY.match(ln)
        ]
        if not body:
            continue
        entry_text = " ".join(lines)
        # First line is authors (year); the title is the second line when present.
        title = (body[1] if len(body) > 1 else body[0]).rstrip(".")
        out.append({"title": title, "arxiv_id": _entry_arxiv(entry_text)})
    return out
