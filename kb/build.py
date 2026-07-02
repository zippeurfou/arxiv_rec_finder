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
from kb.canonicalize import (
    aliases_of,
    canonicalize,
    intro_of,
    load_vocab,
    unmapped_report,
)
from kb.enrich import safe_enrich
from kb.extract import extract_paper, ollama_llm
from kb.issues import iter_issues
from kb.notes import index_line, render_concept_note, render_paper_note
from kb.refs import parse_references
from kb.relevance import is_recsys_relevant

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "recsys-kb" / "fulltext"


def _noop_enrich(arxiv_id: str) -> dict:
    """Default enrichment: no network, no Semantic Scholar. See ``--enrich``."""
    return {"references": [], "citation_count": None}


def _merge_references(parsed: list[dict], enriched: list[dict]) -> list[dict]:
    """Append enrichment refs whose title is not already present in ``parsed``."""
    seen = {(r.get("title") or "").strip().lower() for r in parsed}
    merged = list(parsed)
    for ref in enriched:
        key = (ref.get("title") or "").strip().lower()
        if key and key not in seen:
            merged.append(ref)
            seen.add(key)
    return merged


def build_paper(rec, *, kb_dir, vocab, fetch, extract, enrich) -> list[str]:
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
    )
    enrichment = enrich(rec.arxiv_id)
    references = _merge_references(references, enrichment.get("references") or [])
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
        try:
            fm = _parse_frontmatter(note_path.read_text(encoding="utf-8"))
            if not isinstance(fm, dict):
                raise ValueError("frontmatter is not a mapping")
            arxiv_id = note_path.stem  # derive from filename, robust
            concepts_raw = list(fm.get("concepts_raw") or [])
            concepts, _unmapped = canonicalize(concepts_raw, vocab)
        except Exception as e:  # one corrupt note must not abort the whole run
            logging.warning("skipping unparseable note %s: %s", note_path.name, e)
            continue
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
            aliases=aliases_of(vocab.get(slug)),
            intro=intro_of(vocab.get(slug)),
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


def run_backfill(records, *, kb_dir, vocab, fetch, extract, enrich, limit=None) -> dict:
    """Build every record (per-paper try/except), then regenerate + write state.

    A single failing paper is logged and skipped -- it must never abort the run.
    """
    kb_dir = Path(kb_dir)
    prior_state = _read_state(kb_dir)
    prior_failures = list(prior_state.get("failures") or [])

    failures: list[str] = []
    built = 0
    max_issue = prior_state.get("last_issue", 0) or 0

    for i, rec in enumerate(records):
        if limit is not None and i >= limit:
            break
        # Advance the watermark on ATTEMPT, not success: a transient failure on
        # the newest paper must not make the next incremental re-fetch old work.
        if rec.issue is not None:
            max_issue = max(max_issue, rec.issue)
        try:
            build_paper(
                rec,
                kb_dir=kb_dir,
                vocab=vocab,
                fetch=fetch,
                extract=extract,
                enrich=enrich,
            )
            built += 1
        except Exception as e:  # one bad paper must not abort a 2455-paper run
            logging.warning("build failed for %s: %s", rec.arxiv_id, e)
            failures.append(rec.arxiv_id)

    regenerate(kb_dir, vocab)

    # Persist cumulative failures so they stay re-runnable: keep prior failures
    # whose note is still missing, union this run's failures.
    papers_dir = kb_dir / "papers"
    kept_prior = [
        aid for aid in prior_failures if not (papers_dir / f"{aid}.md").exists()
    ]
    all_failures = list(dict.fromkeys([*kept_prior, *failures]))

    summary = {"last_issue": max_issue, "failures": all_failures, "built": built}
    (kb_dir / "state.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return summary


def run_incremental(
    records, *, kb_dir, vocab, fetch, extract, enrich, limit=None
) -> dict:
    """Same pipeline as backfill; callers filter ``records`` by ``since_issue``."""
    return run_backfill(
        records,
        kb_dir=kb_dir,
        vocab=vocab,
        fetch=fetch,
        extract=extract,
        enrich=enrich,
        limit=limit,
    )


def run_canonicalize(*, kb_dir, vocab) -> None:
    """Re-canonicalize the corpus from disk only. No fetch, no LLM, no network."""
    regenerate(kb_dir, vocab)


# --- agent-driven pipeline: prepare (plumbing) -> agent -> ingest (plumbing) --
#
# Extraction (concepts_raw + technical_note from full text) is done by an LLM
# AGENT, not a local model. The pipeline is therefore split into two pure-Python,
# LLM-free stages with the agent in the middle:
#
#   prepare  -> fetches+caches full text, parses references, emits a JSONL
#               "pending" list (one paper per line) for the agent to read.
#   <agent>  -> reads each paper's full text, writes an "extractions" JSONL
#               (arxiv_id, concepts_raw, technical_note).
#   ingest   -> joins pending + extractions, builds paper notes, canonicalizes,
#               and regenerates every derived artifact via ``regenerate``.
#
# Both stages are per-paper resilient: one bad paper is logged and skipped, never
# aborting the run.


def prepare(records, *, kb_dir, cache_dir, fetch, out_path) -> dict:
    """Fetch+cache full text and emit a JSONL pending list for the agent.

    No LLM, no extraction here -- only the deterministic plumbing (fetch, cache,
    parse references). ``fetch`` is injected (production: ``kb.acquire.get_fulltext``
    bound to ``cache_dir``, which caches to ``cache_dir/<id>.md``).
    """
    cache_dir = Path(cache_dir)
    out_path = Path(out_path)

    pending: list[dict] = []
    failures: list[str] = []
    for rec in records:
        try:
            fulltext = fetch(rec.arxiv_id)
            references = parse_references(fulltext)
            pending.append(
                {
                    "arxiv_id": rec.arxiv_id,
                    "title": rec.title,
                    "year": rec.year,
                    "companies": list(rec.companies),
                    "url": rec.url,
                    "issue": rec.issue,
                    "summary": rec.summary,
                    "fulltext_path": str(cache_dir / f"{rec.arxiv_id}.md"),
                    "references": references,
                }
            )
        except Exception as e:  # one bad paper must not abort the whole run
            logging.warning("prepare failed for %s: %s", rec.arxiv_id, e)
            failures.append(rec.arxiv_id)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pending),
        encoding="utf-8",
    )
    return {"pending": len(pending), "failures": failures, "out": str(out_path)}


def _read_jsonl(path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def ingest(*, kb_dir, pending_path, extractions_path, vocab) -> dict:
    """Join agent extractions with the pending metadata, build notes, regenerate.

    No LLM, no fetch. Reads ``pending_path`` (from ``prepare``) and
    ``extractions_path`` (from the agent), renders one paper note per matched
    extraction, then rebuilds every derived artifact via ``regenerate``. Papers
    with no matching extraction are recorded as failures so they stay retryable.
    """
    kb_dir = Path(kb_dir)
    pending = {p["arxiv_id"]: p for p in _read_jsonl(pending_path)}
    extractions = _read_jsonl(extractions_path)

    prior_state = _read_state(kb_dir)
    prior_failures = list(prior_state.get("failures") or [])
    prior_last_issue = prior_state.get("last_issue", 0) or 0

    papers_dir = kb_dir / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    ingested = 0
    max_issue = prior_last_issue
    extracted_ids: set[str] = set()
    for ex in extractions:
        arxiv_id = ex.get("arxiv_id")
        meta = pending.get(arxiv_id)
        if meta is None:  # extraction with no matching pending entry: skip
            continue
        try:
            concepts_raw = list(ex.get("concepts_raw") or [])
            concepts, _unmapped = canonicalize(concepts_raw, vocab)
            note = render_paper_note(
                arxiv_id=arxiv_id,
                title=meta.get("title", ""),
                year=meta.get("year"),
                companies=list(meta.get("companies") or []),
                url=meta.get("url", ""),
                issue=meta.get("issue"),
                concepts_raw=concepts_raw,
                concepts=concepts,
                summary=meta.get("summary", ""),
                technical_note=ex.get("technical_note", ""),
                references=list(meta.get("references") or []),
                citation_count=None,
            )
            (papers_dir / f"{arxiv_id}.md").write_text(note, encoding="utf-8")
            ingested += 1
            extracted_ids.add(arxiv_id)
            issue = meta.get("issue")
            if issue is not None:
                max_issue = max(max_issue, issue)
        except Exception as e:  # one bad extraction must not abort the run
            logging.warning("ingest failed for %s: %s", arxiv_id, e)

    regenerate(kb_dir, vocab)

    # Pending papers the agent never extracted stay retryable.
    missing_extraction = [aid for aid in pending if aid not in extracted_ids]

    # Cumulative failures: prior failures whose note is still missing, union the
    # pending ids with no matching extraction. Guard last_issue against regress.
    kept_prior = [
        aid for aid in prior_failures if not (papers_dir / f"{aid}.md").exists()
    ]
    all_failures = list(dict.fromkeys([*kept_prior, *missing_extraction]))

    summary = {
        "last_issue": max(max_issue, prior_last_issue),
        "failures": all_failures,
        "ingested": ingested,
    }
    (kb_dir / "state.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return {
        "ingested": ingested,
        "missing_extraction": missing_extraction,
        "last_issue": summary["last_issue"],
        "failures": all_failures,
    }


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


def _resolve_kb_dir(parser, args) -> Path:
    if not args.kb_dir:
        parser.error("--kb-dir is required (or set RECSYS_KB_DIR)")
    return Path(args.kb_dir)


def _iter_records(args, kb_dir, token):
    """Select records from the GitHub issues per --retry-failed / --incremental."""
    if getattr(args, "retry_failed", False):
        failed = set(_read_state(kb_dir).get("failures") or [])
        return (
            rec
            for rec in iter_issues(args.repo, token, since_issue=0)
            if rec.arxiv_id in failed
        )
    since_issue = args.since_issue
    if since_issue is None:
        since_issue = (
            _read_state(kb_dir).get("last_issue", 0) if args.incremental else 0
        )
    records = iter_issues(args.repo, token, since_issue=since_issue)
    if getattr(args, "recsys_only", False):
        records = (r for r in records if is_recsys_relevant(r.title, r.summary))
    return records


def _cmd_prepare(parser, args) -> None:
    """Fetch+cache full text and emit the pending JSONL. No LLM, no git commit."""
    kb_dir = _resolve_kb_dir(parser, args)
    token = os.environ.get("GITHUB_TOKEN")
    out_path = Path(args.out) if args.out else kb_dir / ".pending.jsonl"

    def fetch(arxiv_id):
        return get_fulltext(arxiv_id, cache_dir=DEFAULT_CACHE_DIR)

    records = _iter_records(args, kb_dir, token)
    if args.limit is not None:
        records = (r for i, r in enumerate(records) if i < args.limit)

    result = prepare(
        records,
        kb_dir=kb_dir,
        cache_dir=DEFAULT_CACHE_DIR,
        fetch=fetch,
        out_path=out_path,
    )
    logging.info(
        "prepared=%s failures=%s out=%s",
        result["pending"],
        len(result["failures"]),
        result["out"],
    )


def _cmd_ingest(parser, args) -> None:
    """Join pending + agent extractions into notes, regenerate, then commit.

    The transient ``.pending.jsonl`` / ``.extractions.jsonl`` are deleted BEFORE
    ``_git_commit`` (which does ``git add -A``) so they never land in the data
    repo -- keeps the commit clean without relying on a .gitignore entry.
    """
    kb_dir = _resolve_kb_dir(parser, args)
    vocab = load_vocab(kb_dir / "vocabulary.yaml")
    pending_path = Path(args.pending) if args.pending else kb_dir / ".pending.jsonl"
    extractions_path = Path(args.extractions)

    result = ingest(
        kb_dir=kb_dir,
        pending_path=pending_path,
        extractions_path=extractions_path,
        vocab=vocab,
    )
    logging.info(
        "ingested=%s missing=%s",
        result["ingested"],
        len(result["missing_extraction"]),
    )

    # Remove transient files before committing so `git add -A` can't stage them.
    pending_path.unlink(missing_ok=True)
    if extractions_path.parent == kb_dir:
        extractions_path.unlink(missing_ok=True)
    _git_commit(kb_dir, "feat: ingest agent extractions into knowledge base")


def _cmd_canonicalize(parser, args) -> None:
    kb_dir = _resolve_kb_dir(parser, args)
    vocab = load_vocab(kb_dir / "vocabulary.yaml")
    run_canonicalize(kb_dir=kb_dir, vocab=vocab)
    _git_commit(kb_dir, "chore: re-canonicalize concepts")


def _cmd_autonomous(parser, args) -> None:
    """The legacy end-to-end path with a LOCAL Ollama LLM in-process.

    Preserved only under this explicit subcommand so no other command can trigger
    Ollama by accident.
    """
    kb_dir = _resolve_kb_dir(parser, args)
    vocab = load_vocab(kb_dir / "vocabulary.yaml")
    token = os.environ.get("GITHUB_TOKEN")
    real_llm = ollama_llm()

    def _extract(*, title, fulltext, vocab_hint):
        return extract_paper(title, fulltext, vocab_hint, llm=real_llm)

    def fetch(arxiv_id):
        return get_fulltext(arxiv_id, cache_dir=DEFAULT_CACHE_DIR)

    # S2 is off by default (its refs were discarded and it burns rate limit);
    # opt in with --enrich to merge real Semantic Scholar references.
    enrich = safe_enrich if args.enrich else _noop_enrich

    records = _iter_records(args, kb_dir, token)
    runner = run_incremental if args.incremental else run_backfill
    summary = runner(
        records,
        kb_dir=kb_dir,
        vocab=vocab,
        fetch=fetch,
        extract=_extract,
        enrich=enrich,
        limit=args.limit,
    )
    logging.info("built=%s failures=%s", summary["built"], len(summary["failures"]))
    _git_commit(kb_dir, "feat: refresh knowledge base from issues")


def _add_selection_args(sub) -> None:
    """Shared record-selection flags for the issue-reading subcommands."""
    sub.add_argument("--repo")
    sub.add_argument("--incremental", action="store_true")
    sub.add_argument("--since-issue", type=int, default=None)
    sub.add_argument("--limit", type=int, default=None)
    sub.add_argument("--retry-failed", action="store_true")
    sub.add_argument(
        "--recsys-only",
        action="store_true",
        help="keep only papers whose title/summary shows a recsys signal",
    )


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Build the recsys knowledge base.")
    parser.add_argument("--kb-dir", default=os.environ.get("RECSYS_KB_DIR"))
    sub = parser.add_subparsers(dest="command", required=True)

    p_prepare = sub.add_parser(
        "prepare", help="fetch+cache full text, emit pending JSONL (no LLM)"
    )
    _add_selection_args(p_prepare)
    p_prepare.add_argument("--out", default=None)
    p_prepare.set_defaults(func=_cmd_prepare)

    p_ingest = sub.add_parser(
        "ingest", help="build notes from agent extractions, then commit"
    )
    p_ingest.add_argument("--pending", default=None)
    p_ingest.add_argument("--extractions", required=True)
    p_ingest.set_defaults(func=_cmd_ingest)

    p_canon = sub.add_parser(
        "canonicalize", help="re-canonicalize the corpus from disk (no LLM)"
    )
    p_canon.set_defaults(func=_cmd_canonicalize)

    p_auto = sub.add_parser(
        "autonomous", help="legacy end-to-end build with a LOCAL Ollama LLM"
    )
    _add_selection_args(p_auto)
    p_auto.add_argument("--enrich", action="store_true")
    p_auto.set_defaults(func=_cmd_autonomous)

    args = parser.parse_args(argv)
    args.func(parser, args)


if __name__ == "__main__":  # pragma: no cover
    main()
