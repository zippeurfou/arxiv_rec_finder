import re

_ARXIV_INLINE = re.compile(r"arXiv:(\d{4}\.\d{4,5})", re.IGNORECASE)


def parse_references(markdown: str) -> list[dict]:
    m = re.search(r"##+\s*References\s*(.*)", markdown, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        line = line.strip().lstrip("-* ").strip()
        if not line:
            continue
        aid = _ARXIV_INLINE.search(line)
        out.append({"title": line, "arxiv_id": aid.group(1) if aid else None})
    return out
