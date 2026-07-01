"""Build orchestration: compose the kb modules into backfill / incremental /
canonicalize runs.

The expensive, read-once step (acquire -> refs -> extract -> enrich) is separated
from the cheap, re-runnable canonicalize step. ``regenerate`` rebuilds every
derived artifact (concept notes, index, unmapped report) purely from what is
already on disk in ``papers/*.md`` -- it never fetches, calls an LLM, or hits the
network. That is what makes "edit vocabulary.yaml + --canonicalize" retroactively
re-tag the whole corpus with no re-reading.
"""

import argparse
import json
import logging
import os
import subprocess
from pathlib import Path

import yaml

from kb.acquire import get_fulltext
from kb.canonicalize import canonicalize, load_vocab, unmapped_report
from kb.enrich import safe_enrich
from kb.extract import extract_paper, ollama_llm
from kb.issues import iter_issues
from kb.notes import index_line, render_concept_note, render_paper_note
from kb.refs import parse_references

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "recsys-kb" / "fulltext"


def build_paper(rec, *, kb_dir, vocab, cache_dir, fetch, extract, enrich) -> list[str]:
    """Read-once pipeline for one paper. Returns the paper's ``concepts_raw``.

    Composes fetch -> parse_references -> extract -> enrich -> canonicalize ->
    render -> write. ``extract`` is an injected callable ``(**kwargs) -> Extraction``
    so the real llm can be bound in production and faked in tests.
    """
    kb_dir = Path(kb_dir)
    fulltext = fetch(rec.arxiv_id)
    references = parse_references(fulltext)
    ex = extract(
        title=rec.title,
        fulltext=fulltext,
        vocab_hint=list(vocab.keys()),
        llm=None,
    )
    enrichment = enrich(rec.arxiv_id)
    concepts, _unmapped = canonicalize(ex.concepts_raw, vocab)

    note = render_paper_note(
        arxiv_id=rec.arxiv_id,
        title=rec.title,
        year=rec.year,
        companies=rec.companies,
        url=rec.url,
        issue=rec.issue,
        concepts_raw=ex.concepts_raw,
        concepts=concepts,
        summary=rec.summary,
        technical_note=ex.technical_note,
        references=references,
        citation_count=enrichment.get("citation_count"),
    )

    papers_dir = kb_dir / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    (papers_dir / f"{rec.arxiv_id}.md").write_text(note, encoding="utf-8")
    return ex.concepts_raw


def _parse_frontmatter(text: str) -> dict:
    """Extract the YAML frontmatter block (between the leading ``---`` fences)."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    return yaml.safe_load(text[3:end]) or {}


def regenerate(kb_dir, vocab) -> None:
    """Rebuild derived artifacts from ``papers/*.md`` alone. No fetch, no LLM.

    For each paper note it re-derives canonical ``concepts`` from the stored
    ``concepts_raw`` and the (possibly updated) vocabulary, then writes:
    concept notes, index.jsonl, and unmapped_concepts.md.
    """
    kb_dir = Path(kb_dir)
    papers_dir = kb_dir / "papers"

    papers: list[dict] = []
    all_raw: list[list[str]] = []
    for note_path in sorted(papers_dir.glob("*.md")):
        fm = _parse_frontmatter(note_path.read_text(encoding="utf-8"))
        arxiv_id = note_path.stem  # derive from filename, robust
        concepts_raw = list(fm.get("concepts_raw") or [])
        concepts, _unmapped = canonicalize(concepts_raw, vocab)
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "title": fm.get("title", ""),
                "year": fm.get("year"),
                "companies": list(fm.get("companies") or []),
                "url": fm.get("url", ""),
                "issue": fm.get("issue"),
                "concepts_raw": concepts_raw,
                "concepts": concepts,
            }
        )
        all_raw.append(concepts_raw)

    # Concept notes: one per canonical slug that has >= 1 paper.
    concepts_dir = kb_dir / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)
    slug_to_papers: dict[str, list[tuple[str, str, int, list[str]]]] = {}
    for p in papers:
        for slug in p["concepts"]:
            slug_to_papers.setdefault(slug, []).append(
                (p["arxiv_id"], p["title"], p["year"], p["companies"])
            )
    for slug, slug_papers in slug_to_papers.items():
        note = render_concept_note(
            slug=slug,
            aliases=list(vocab.get(slug, [])),
            intro="",
            papers=slug_papers,
        )
        (concepts_dir / f"{slug}.md").write_text(note, encoding="utf-8")

    # index.jsonl: one line per paper, sorted by arxiv_id.
    index_lines = [
        index_line(
            arxiv_id=p["arxiv_id"],
            title=p["title"],
            year=p["year"],
            companies=p["companies"],
            concepts=p["concepts"],
            url=p["url"],
            issue=p["issue"],
        )
        for p in sorted(papers, key=lambda p: p["arxiv_id"])
    ]
    (kb_dir / "index.jsonl").write_text(
        "\n".join(index_lines) + ("\n" if index_lines else ""), encoding="utf-8"
    )

    # unmapped_concepts.md: ranked raw concepts with no canonical mapping.
    report = unmapped_report(all_raw, vocab)
    lines = [f"- {concept} ({count})" for concept, count in report]
    (kb_dir / "unmapped_concepts.md").write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
    )


def run_backfill(
    records, *, kb_dir, vocab, cache_dir, fetch, extract, enrich, limit=None
) -> dict:
    """Build every record (per-paper try/except), then regenerate + write state.

    A single failing paper is logged and skipped -- it must never abort the run.
    """
    kb_dir = Path(kb_dir)
    failures: list[str] = []
    built = 0
    max_issue = 0

    for i, rec in enumerate(records):
        if limit is not None and i >= limit:
            break
        try:
            build_paper(
                rec,
                kb_dir=kb_dir,
                vocab=vocab,
                cache_dir=cache_dir,
                fetch=fetch,
                extract=extract,
                enrich=enrich,
            )
            built += 1
            if rec.issue is not None:
                max_issue = max(max_issue, rec.issue)
        except Exception as e:  # one bad paper must not abort a 2455-paper run
            logging.warning("build failed for %s: %s", rec.arxiv_id, e)
            failures.append(rec.arxiv_id)

    regenerate(kb_dir, vocab)

    summary = {"last_issue": max_issue, "failures": failures, "built": built}
    (kb_dir / "state.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return summary


def run_incremental(
    records, *, kb_dir, vocab, cache_dir, fetch, extract, enrich, limit=None
) -> dict:
    """Same pipeline as backfill; callers filter ``records`` by ``since_issue``."""
    return run_backfill(
        records,
        kb_dir=kb_dir,
        vocab=vocab,
        cache_dir=cache_dir,
        fetch=fetch,
        extract=extract,
        enrich=enrich,
        limit=limit,
    )


def run_canonicalize(*, kb_dir, vocab) -> None:
    """Re-canonicalize the corpus from disk only. No fetch, no LLM, no network."""
    regenerate(kb_dir, vocab)


def _git_commit(kb_dir, message) -> None:
    """Stage everything in the data repo and commit; tolerate nothing-to-commit."""
    kb_dir = str(kb_dir)
    subprocess.run(["git", "-C", kb_dir, "add", "-A"], check=True)
    result = subprocess.run(
        ["git", "-C", kb_dir, "commit", "-m", message],
        capture_output=True,
        text=True,
    )
    if (
        result.returncode != 0
        and "nothing to commit" not in (result.stdout + result.stderr).lower()
    ):
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr
        )


def _read_state(kb_dir) -> dict:
    state_path = Path(kb_dir) / "state.json"
    if state_path.exists():
        return json.loads(state_path.read_text(encoding="utf-8"))
    return {}


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Build the recsys knowledge base.")
    parser.add_argument("--kb-dir", default=os.environ.get("RECSYS_KB_DIR"))
    parser.add_argument("--repo")
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--canonicalize", action="store_true")
    parser.add_argument("--since-issue", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    if not args.kb_dir:
        parser.error("--kb-dir is required (or set RECSYS_KB_DIR)")
    kb_dir = Path(args.kb_dir)
    vocab = load_vocab(kb_dir / "vocabulary.yaml")

    if args.canonicalize:
        run_canonicalize(kb_dir=kb_dir, vocab=vocab)
        _git_commit(kb_dir, "chore: re-canonicalize concepts")
        return

    since_issue = args.since_issue
    if since_issue is None:
        since_issue = (
            _read_state(kb_dir).get("last_issue", 0) if args.incremental else 0
        )

    token = os.environ.get("GITHUB_TOKEN")
    records = iter_issues(args.repo, token, since_issue=since_issue)

    llm = ollama_llm()

    def extract(*, title, fulltext, vocab_hint, llm=llm):
        return extract_paper(
            title=title, fulltext=fulltext, vocab_hint=vocab_hint, llm=llm
        )

    def fetch(arxiv_id):
        return get_fulltext(arxiv_id, cache_dir=DEFAULT_CACHE_DIR)

    runner = run_incremental if args.incremental else run_backfill
    summary = runner(
        records,
        kb_dir=kb_dir,
        vocab=vocab,
        cache_dir=DEFAULT_CACHE_DIR,
        fetch=fetch,
        extract=extract,
        enrich=safe_enrich,
        limit=args.limit,
    )
    logging.info("built=%s failures=%s", summary["built"], len(summary["failures"]))
    _git_commit(kb_dir, "feat: refresh knowledge base from issues")


if __name__ == "__main__":  # pragma: no cover
    main()
