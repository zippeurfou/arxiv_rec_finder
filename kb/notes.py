import datetime
import json

import yaml


class _Quoted(str):
    """A string emitted as a double-quoted YAML scalar."""


def _represent_quoted(dumper: yaml.Dumper, data: _Quoted) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style='"')


yaml.SafeDumper.add_representer(_Quoted, _represent_quoted)


def _frontmatter(data: dict) -> str:
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return f"---\n{body}---\n"


def _paper_frontmatter(arxiv_id: str, rest: dict) -> str:
    # arXiv ids resemble floats (e.g. 2606.31031); emit the id as a plain
    # unquoted scalar (matching the KB schema) and YAML-dump the rest.
    body = yaml.safe_dump(rest, sort_keys=False, allow_unicode=True)
    return f"---\narxiv_id: {arxiv_id}\n{body}---\n"


def render_paper_note(
    *,
    arxiv_id: str,
    title: str,
    year: int,
    companies: list[str],
    url: str,
    issue: int,
    concepts_raw: list[str],
    concepts: list[str],
    summary: str,
    technical_note: str,
    references: list[dict],
    citation_count: int | None,
) -> str:
    fm = _paper_frontmatter(
        arxiv_id,
        {
            "title": _Quoted(title),
            "year": year,
            "companies": list(companies),
            "url": url,
            "issue": issue,
            "concepts_raw": list(concepts_raw),
            "concepts": list(concepts),
            "citation_count": citation_count,
            "last_built": datetime.date.today().isoformat(),
        },
    )

    concept_links = " ".join(f"[[{slug}]]" for slug in concepts)

    ref_lines = []
    for ref in references:
        line = f"- {ref['title']}"
        if ref.get("arxiv_id"):
            line += f" (arXiv:{ref['arxiv_id']})"
        ref_lines.append(line)
    references_block = "\n".join(ref_lines)

    return (
        f"{fm}\n"
        f"Concepts: {concept_links}\n\n"
        f"## Summary\n\n{summary}\n\n"
        f"## Technical note\n\n{technical_note}\n\n"
        f"## References\n\n{references_block}\n"
    )


def render_concept_note(
    *,
    slug: str,
    aliases: list[str],
    intro: str,
    papers: list[tuple[str, str, int, list[str]]],
) -> str:
    fm = _frontmatter({"slug": slug, "aliases": list(aliases)})

    paper_lines = []
    for arxiv_id, title, year, companies in papers:
        company_str = ", ".join(companies)
        paper_lines.append(f"- [[{arxiv_id}]] {title} ({company_str}, {year})")
    papers_block = "\n".join(paper_lines)

    return f"{fm}\n## What it is\n\n{intro}\n\n## Papers\n\n{papers_block}\n"


def index_line(
    *,
    arxiv_id: str,
    title: str,
    year: int,
    companies: list[str],
    concepts: list[str],
    url: str,
    issue: int,
) -> str:
    return json.dumps(
        {
            "arxiv_id": arxiv_id,
            "title": title,
            "year": year,
            "companies": companies,
            "concepts": concepts,
            "url": url,
            "issue": issue,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
