import logging


def parse_s2_references(payload: dict) -> list[dict]:
    out = []
    for item in payload.get("data", []):
        c = item.get("citedPaper", {}) or {}
        ext = c.get("externalIds") or {}
        out.append(
            {
                "title": c.get("title"),
                "year": c.get("year"),
                "arxiv_id": ext.get("ArXiv"),
                "doi": ext.get("DOI"),
            }
        )
    return out


def _default_getter(arxiv_id: str) -> dict:
    import requests

    base = f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}"
    refs = requests.get(
        f"{base}/references",
        params={"fields": "title,year,externalIds", "limit": 100},
        timeout=30,
    )
    refs.raise_for_status()
    return {"refs": refs.json()}


def safe_enrich(arxiv_id: str, getter=_default_getter) -> dict:
    try:
        data = getter(arxiv_id)
        return {"references": parse_s2_references(data["refs"]), "citation_count": None}
    except Exception as e:  # rate limit / not indexed / network
        logging.info("S2 enrich skipped for %s: %s", arxiv_id, e)
        return {"references": [], "citation_count": None}
