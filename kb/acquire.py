# kb/acquire.py
import os
import subprocess
import tempfile
import time
from pathlib import Path

import requests

ARXIV2MD_API = "https://arxiv2md.org/api/markdown"
ARXIV_PDF = "https://arxiv.org/pdf/{}"

# Below this length, arxiv2md almost certainly returned an arXiv page stub
# (no HTML/source rendering available) rather than the paper body.
_THIN_THRESHOLD = 800


def _looks_thin(md: str) -> bool:
    """True if the markdown is too short to be a real paper body (boilerplate)."""
    return len((md or "").strip()) < _THIN_THRESHOLD


def _pdf_fulltext(arxiv_id: str, timeout: int = 90) -> str:
    """Best-effort PDF fallback: download the arXiv PDF and extract text via
    pdftotext. Returns "" on any failure (missing pdftotext, network, etc.)."""
    try:
        resp = requests.get(ARXIV_PDF.format(arxiv_id), timeout=timeout)
        resp.raise_for_status()
        with tempfile.TemporaryDirectory() as td:
            pdf_path = Path(td) / f"{arxiv_id}.pdf"
            pdf_path.write_bytes(resp.content)
            out = subprocess.run(
                ["pdftotext", str(pdf_path), "-"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return out.stdout if out.returncode == 0 else ""
    except Exception:
        return ""


def _default_fetcher(arxiv_id: str) -> str:
    """Fetch clean markdown incl. references via the hosted arxiv2md.org API,
    falling back to PDF text extraction when arxiv2md returns only a stub."""
    # Politeness / rate-limit delay; override via ARXIV2MD_SLEEP for bulk backfill.
    time.sleep(float(os.environ.get("ARXIV2MD_SLEEP", "3")))
    resp = requests.get(
        ARXIV2MD_API,
        params={"url": arxiv_id, "remove_refs": "false"},
        timeout=90,
    )
    resp.raise_for_status()
    resp.encoding = "utf-8"
    md = resp.text
    if _looks_thin(md):
        pdf_text = _pdf_fulltext(arxiv_id)
        if not _looks_thin(pdf_text):
            return pdf_text
    return md


def get_fulltext(arxiv_id: str, cache_dir: Path, fetcher=_default_fetcher) -> str:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{arxiv_id}.md"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    md = fetcher(arxiv_id)
    # Do not cache an empty/whitespace-only result: it would poison every
    # future run. Return it so the caller can decide; next run retries.
    if md.strip():
        cached.write_text(md, encoding="utf-8")
    return md
