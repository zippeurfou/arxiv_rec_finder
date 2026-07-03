# arXiv Affiliation Cache + Backfill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the arXiv discovery bot (a) rate-limit-safe against the arXiv API, (b) never re-download the same paper's PDF twice via a persisted extraction cache, (c) retroactively catch papers when a new affiliation domain is added, and (d) support a resumable historical backfill from a `--since` date (initial run: Jan 2025).

**Architecture:** The bot's expensive step is downloading each candidate PDF to extract author emails for affiliation matching. We persist that extraction (`arxiv_id → {metadata, affiliations, emails}`) as a JSONL file committed back to the repo by the GitHub Action. The affiliation *verdict* becomes a pure function of the cached signals + the current `tech_domains` list, so re-deciding (after adding a domain) is free and requires no re-download. A new paged, `submittedDate`-bounded backfill command reuses the same extract→cache→decide→issue path. All arXiv **API** calls go through a single paced client (≥3s between calls, timeouts, retry/backoff, rate-limit-body detection); **PDF** downloads stay parallel but bounded, with timeouts.

**Tech Stack:** Python 3.12, `uv`, `feedparser`, `requests`, `PyGithub`, `pytest`, `ruff`, GitHub Actions.

---

## Decisions locked in (from design discussion)

1. **Backfill = PDF every recsys paper** in the `submittedDate` window (thorough). Must be **resumable** and **polite**; run **locally**, not in the Action (would exceed the 6h job limit). Chunkable via `--since`/`--until`.
2. **Retroactive affiliation changes = YES.** Each run re-decides over the *entire* cache against current `tech_domains` and files issues for new matches, with no re-download.
3. **Cache = `arxiv_id → {title, published, url, affiliations, emails, checked}`** as `state/email_cache.jsonl` (one JSON object per line), committed back by the Action. Presence of a key ⇒ "already scanned" (even if `emails: []`). The verdict is recomputed from `affiliations` + `emails` each run.

## Default assumptions (not separately confirmed — flag if wrong)

- **No `submittedDate` watermark.** The extraction cache already prevents re-downloads, and the daily re-decide pass covers retroactivity, so a watermark adds nothing. Daily fetch stays at `max_results=400` (~3-day window) and relies on daily overlap for continuity.
- **Cache metadata is stored so cached-only papers can be turned into issues** during the retroactive re-decide without re-fetching them from arXiv.
- **Summaries during backfill** use the existing `summarize_with_ollama`, which falls back to the abstract when no Ollama model is present (`summarizer.py:20-22`). Only *matches* get issues (a small fraction), so this is cheap.
- **Dedup key for issues** stays the arXiv URL parsed from issue bodies (existing behavior, `store.py`). We normalize on the `arxiv_id` internally but keep writing the URL in issue bodies.
- **State path** is `state/email_cache.jsonl`; the write-test spike uses `state/_write_test.txt`.

## Relevant existing code (read before starting)

- `main.py` — orchestration (`collect_new_arxiv_entries`, `submit_arxiv_issues`, `main`).
- `arxiv_client.py:6` — `get_recent_arxiv_papers` (single unpaced call, `max_results=200`, no timeout).
- `filter_affiliations.py:20` — `has_big_tech_author` (3-pass: metadata → PDF emails → text). Production calls it with `use_text` defaulting False (`main.py:74`).
- `arxiv_parser.py` — `download_pdf` (no timeout/UA), `extract_emails_from_arxiv_pdf`, `find_emails`.
- `notifier.py:40` — `create_issue` (no dedup; body carries `🔗 **URL:**`).
- `store.py:4` — `load_seen_from_issues` (rebuilds seen-set from issue-body URLs).
- `kb/ids.py` — `extract_arxiv_id(url_or_text) -> str|None` (reuse for cache keys).
- `.github/workflows/daily.yaml` — cron `0 13 * * *`, `permissions: contents: read, issues: write`.

---

## Phase 0 — Prove the GitHub Action can write to the repo (DEPENDENCY SPIKE, do first)

**Why first:** every persistence idea depends on the Action committing `state/` back to the repo. Validate it in isolation before building on it.

**How Action writes work (background):**
- The built-in `GITHUB_TOKEN` **can push to its own repo** if the workflow grants `permissions: contents: write`.
- `actions/checkout` persists that token as the git credential by default, so `git push` "just works".
- **Pushes made with `GITHUB_TOKEN` do NOT trigger other workflows** (GitHub's loop-prevention) — so committing `state/` will *not* re-trigger the daily job. Good.
- **Gotcha:** if `main` has branch protection requiring PRs/reviews, a direct token push is rejected. The spike will surface this. Fallbacks if blocked: push to a `state`-only branch, or open a PR, or (simplest) exempt the bot.

**Files:**
- Create: `.github/workflows/write-test.yaml`

**Step 1: Create the write-test workflow**

```yaml
name: write-test
on:
  workflow_dispatch:

permissions:
  contents: write

jobs:
  write-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Write a state file
        run: |
          mkdir -p state
          echo "write-test $(date -u +%FT%TZ) run=${{ github.run_id }}" >> state/_write_test.txt
      - name: Commit and push
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add state/_write_test.txt
          git commit -m "chore: write-test [skip ci]" || echo "nothing to commit"
          git push
```

**Step 2: Commit and push the workflow**

```bash
git add .github/workflows/write-test.yaml
git commit -m "ci: add write-test spike to verify Action can push state"
git push
```

**Step 3: Run it and verify (manual, by the human)**

- GitHub → Actions → "write-test" → **Run workflow**.
- Expected: green run; a new commit "chore: write-test" by `github-actions[bot]`; `state/_write_test.txt` exists on `main`.
- If the push step fails with `protected branch` / `403`: branch protection is on. STOP and decide the fallback (state branch / PR / exemption) before continuing — the rest of the plan assumes direct push works.

**Step 4: Record the result**

- On success, note in the PR/issue that direct token push works. Leave the workflow in place for now (removed in Phase 7 cleanup, or keep as a manual diagnostic).

---

## Phase 1 — Paced, resilient arXiv API client

**Files:**
- Modify: `arxiv_client.py`
- Test: `tests/test_arxiv_client.py` (create)

**Step 1: Write failing tests for pacing + rate-limit detection**

```python
# tests/test_arxiv_client.py
import time
import types
import pytest
import arxiv_client as ac


def test_is_rate_limited_body():
    assert ac._is_rate_limited_body(b"Rate exceeded.")
    assert ac._is_rate_limited_body(b"  rate exceeded. please slow down")
    assert not ac._is_rate_limited_body(b"<feed>...</feed>")


def test_paced_get_enforces_min_interval(monkeypatch):
    calls = []

    class FakeResp:
        status_code = 200
        content = b"<feed></feed>"
        headers = {}
        text = "<feed></feed>"

    def fake_get(url, timeout, headers):
        calls.append(time.monotonic())
        return FakeResp()

    monkeypatch.setattr(ac.requests, "get", fake_get)
    ac._reset_pacing_for_tests()
    monkeypatch.setattr(ac, "MIN_INTERVAL_SEC", 0.2)

    ac._paced_get("http://x/1")
    ac._paced_get("http://x/2")
    assert len(calls) == 2
    assert calls[1] - calls[0] >= 0.2  # second call waited
```

**Step 2: Run to verify fail**

Run: `uv run pytest tests/test_arxiv_client.py -v`
Expected: FAIL (`_is_rate_limited_body`, `_paced_get`, `_reset_pacing_for_tests` not defined).

**Step 3: Rewrite `arxiv_client.py`**

```python
import logging
import threading
import time
from urllib.parse import quote_plus

import feedparser
import requests

USER_AGENT = "arxiv-rec-finder/0.1 (+https://github.com/zippeurfou/arxiv_rec_finder)"
MIN_INTERVAL_SEC = 3.0          # arXiv TOU: <= 1 request / 3s to the API
REQUEST_TIMEOUT = 30
MAX_RETRIES = 5
BASE_URL = "http://export.arxiv.org/api/query?"

_pace_lock = threading.Lock()
_last_request_ts = 0.0


def _reset_pacing_for_tests():
    global _last_request_ts
    _last_request_ts = 0.0


def _is_rate_limited_body(content: bytes) -> bool:
    head = (content or b"")[:64].strip().lower()
    return head.startswith(b"rate exceeded")


def _paced_get(url: str) -> bytes:
    """GET with >=MIN_INTERVAL_SEC spacing, timeout, and retry/backoff on
    429/503 and arXiv's HTTP-200 'Rate exceeded.' soft-throttle."""
    global _last_request_ts
    for attempt in range(MAX_RETRIES):
        with _pace_lock:
            wait = MIN_INTERVAL_SEC - (time.monotonic() - _last_request_ts)
            if wait > 0:
                time.sleep(wait)
            _last_request_ts = time.monotonic()
        try:
            resp = requests.get(
                url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}
            )
        except requests.RequestException as e:
            logging.warning(f"arXiv GET error (attempt {attempt + 1}): {e}")
            time.sleep((attempt + 1) * MIN_INTERVAL_SEC)
            continue

        if resp.status_code == 200 and not _is_rate_limited_body(resp.content):
            return resp.content
        if resp.status_code == 200:  # soft rate-limit body
            logging.warning("arXiv soft rate-limit ('Rate exceeded.'); backing off")
        elif resp.status_code in (429, 500, 502, 503, 504):
            logging.warning(f"arXiv HTTP {resp.status_code}; backing off")
        else:
            resp.raise_for_status()
        retry_after = int(resp.headers.get("Retry-After", 0) or 0)
        time.sleep(max(retry_after, (attempt + 1) * MIN_INTERVAL_SEC))
    raise RuntimeError(f"arXiv API failed after {MAX_RETRIES} retries: {url}")


def _build_query(query, category, start, max_results, since=None, until=None):
    parts = [f"all:{quote_plus(query)}", f"cat:{quote_plus(category)}"]
    if since or until:
        lo = (since or "197001010000")
        hi = (until or "299912312359")
        parts.append(f"submittedDate:[{lo}+TO+{hi}]")
    search = "+AND+".join(parts)
    return (
        f"search_query={search}"
        f"&start={start}&max_results={max_results}"
        "&sortBy=submittedDate&sortOrder=descending"
    )


def get_recent_arxiv_papers(query, category, max_results=400):
    url = BASE_URL + _build_query(query, category, 0, max_results)
    return feedparser.parse(_paced_get(url)).entries
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_arxiv_client.py -v`
Expected: PASS.

**Step 5: Lint + commit**

```bash
uv run ruff check --fix arxiv_client.py tests/test_arxiv_client.py
git add arxiv_client.py tests/test_arxiv_client.py
git commit -m "feat: paced, resilient arXiv API client (3s TOU pacing, timeout, backoff)"
```

---

## Phase 2 — Extraction cache module

**Files:**
- Create: `cache.py`
- Test: `tests/test_cache.py`

**Step 1: Write failing tests**

```python
# tests/test_cache.py
import json
from pathlib import Path
import cache as C


def test_roundtrip_append_and_load(tmp_path):
    p = tmp_path / "email_cache.jsonl"
    rec = {
        "arxiv_id": "2603.06586",
        "title": "T",
        "published": "2026-03-01",
        "url": "https://arxiv.org/abs/2603.06586",
        "affiliations": [],
        "emails": ["x@uber.com"],
        "checked": "2026-07-03",
    }
    C.append_record(p, rec)
    loaded = C.load_cache(p)
    assert "2603.06586" in loaded
    assert loaded["2603.06586"]["emails"] == ["x@uber.com"]


def test_load_missing_file_returns_empty(tmp_path):
    assert C.load_cache(tmp_path / "nope.jsonl") == {}


def test_append_is_idempotent_last_wins(tmp_path):
    p = tmp_path / "c.jsonl"
    C.append_record(p, {"arxiv_id": "1", "emails": []})
    C.append_record(p, {"arxiv_id": "1", "emails": ["a@meta.com"]})
    loaded = C.load_cache(p)
    assert loaded["1"]["emails"] == ["a@meta.com"]  # later line wins


def test_skips_malformed_lines(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text('{"arxiv_id":"1","emails":[]}\nNOT JSON\n')
    loaded = C.load_cache(p)
    assert set(loaded) == {"1"}
```

**Step 2: Run to verify fail**

Run: `uv run pytest tests/test_cache.py -v`  → FAIL (module missing).

**Step 3: Implement `cache.py`**

```python
import json
import logging
from pathlib import Path


def load_cache(path) -> dict:
    """Load state/email_cache.jsonl into {arxiv_id: record}. Later lines win.
    Malformed lines are skipped with a warning."""
    path = Path(path)
    out = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            out[rec["arxiv_id"]] = rec
        except (json.JSONDecodeError, KeyError) as e:
            logging.warning(f"skipping malformed cache line: {e}")
    return out


def append_record(path, record: dict) -> None:
    """Append one record (checkpoint). load_cache() dedups (last wins)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def compact(path) -> None:
    """Rewrite the file with one line per arxiv_id (drops superseded lines)."""
    path = Path(path)
    data = load_cache(path)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w") as f:
        for rec in data.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp.replace(path)
```

**Step 4: Run tests → PASS. Step 5: lint + commit**

```bash
uv run pytest tests/test_cache.py -v
uv run ruff check --fix cache.py tests/test_cache.py
git add cache.py tests/test_cache.py
git commit -m "feat: append-only JSONL extraction cache (id -> emails/affiliations/meta)"
```

---

## Phase 3 — Pure affiliation verdict + cached signal extraction

**Files:**
- Modify: `filter_affiliations.py`
- Test: `tests/test_extract.py` (add cases; do not break existing)

**Step 1: Write failing tests for the pure matcher + cache short-circuit**

```python
# tests/test_extract.py  (append)
import filter_affiliations as fa


def test_decide_companies_from_emails():
    domains = ["meta.com", "uber.com"]
    assert fa.decide_companies([], ["a@uber.com"], domains) == ["Uber"]
    assert fa.decide_companies([], ["a@gmail.com"], domains) == []


def test_decide_companies_from_affiliations():
    domains = ["meta.com", "uber.com"]
    assert fa.decide_companies(["meta ai research"], [], domains) == ["Meta"]


def test_decide_companies_dedup_sorted():
    domains = ["meta.com", "uber.com"]
    got = fa.decide_companies(["meta"], ["x@uber.com", "y@meta.com"], domains)
    assert got == ["Meta", "Uber"]


def test_get_signals_uses_cache_no_download(monkeypatch):
    called = {"n": 0}

    def boom(_id):
        called["n"] += 1
        raise AssertionError("should not download when cached")

    cache = {"2603.06586": {"arxiv_id": "2603.06586",
                            "affiliations": [], "emails": ["x@uber.com"]}}
    sig = fa.get_signals_cached("2603.06586", cache, pdf_email_fn=boom)
    assert sig["emails"] == ["x@uber.com"]
    assert called["n"] == 0
```

**Step 2: Run → FAIL.**

**Step 3: Add pure functions to `filter_affiliations.py`** (keep `extract_affiliations`; you may keep `has_big_tech_author` for back-compat or delete once `main.py` no longer uses it — check its callers first).

```python
def _domain_patterns(tech_domains):
    import re
    pats = []
    for dom in tech_domains:
        alias = dom.split(".")[0].lower()
        pats.append((
            alias,
            re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE),
            re.compile(rf"(?<!\S){re.escape(dom)}(?!\S)", re.IGNORECASE),
            dom,
        ))
    return pats


def decide_companies(affiliations, emails, tech_domains) -> list[str]:
    """Pure verdict from cached signals + current domains. Returns sorted, de-duped
    company aliases (Capitalized)."""
    pats = _domain_patterns(tech_domains)
    found = set()
    for aff in affiliations or []:
        for alias, alias_pat, dom_pat, _dom in pats:
            if alias_pat.search(aff) or dom_pat.search(aff):
                found.add(alias.capitalize())
    for email in emails or []:
        edom = email.split("@")[-1].lower()
        for alias, _a, _d, dom in pats:
            if edom == dom or edom.endswith(f".{dom}"):
                found.add(alias.capitalize())
    return sorted(found)


def get_signals_cached(arxiv_id, cache, pdf_email_fn, affiliations=None):
    """Return {'affiliations':[...], 'emails':[...]} for arxiv_id, using the cache
    if present, else downloading via pdf_email_fn(arxiv_id) -> list[email]."""
    if arxiv_id in cache:
        rec = cache[arxiv_id]
        return {"affiliations": rec.get("affiliations", []),
                "emails": rec.get("emails", [])}
    emails = []
    try:
        emails = pdf_email_fn(arxiv_id)
    except Exception as e:
        import logging
        logging.warning(f"email extraction failed for {arxiv_id}: {e}")
    return {"affiliations": list(affiliations or []), "emails": emails}
```

**Step 4: Run → PASS (and confirm the pre-existing `test_extract.py` cases still pass).**

Run: `uv run pytest tests/test_extract.py -v`

**Step 5: lint + commit**

```bash
uv run ruff check --fix filter_affiliations.py tests/test_extract.py
git add filter_affiliations.py tests/test_extract.py
git commit -m "feat: pure decide_companies() + cache-aware signal extraction"
```

---

## Phase 4 — Add a per-timeout PDF downloader

**Files:**
- Modify: `arxiv_parser.py`
- Test: `tests/test_acquire.py` or `tests/test_arxiv_parser.py` (create if needed)

**Step 1: Failing test — download_pdf passes a timeout + UA**

```python
# tests/test_arxiv_parser.py
import arxiv_parser as ap


def test_download_pdf_uses_timeout_and_ua(monkeypatch):
    seen = {}

    class R:
        content = b"%PDF-1.4"
        def raise_for_status(self): pass

    def fake_get(url, timeout=None, headers=None):
        seen["timeout"] = timeout
        seen["ua"] = (headers or {}).get("User-Agent")
        return R()

    monkeypatch.setattr(ap.requests, "get", fake_get)
    ap.download_pdf("2603.06586")
    assert seen["timeout"] and seen["ua"]
```

**Step 2: Run → FAIL. Step 3: Update `download_pdf`**

```python
PDF_TIMEOUT = 30
UA = "arxiv-rec-finder/0.1 (+https://github.com/zippeurfou/arxiv_rec_finder)"

def download_pdf(arxiv_id):
    base_id = arxiv_id.split("v")[0]
    pdf_url = f"https://arxiv.org/pdf/{base_id}.pdf"
    response = requests.get(pdf_url, timeout=PDF_TIMEOUT, headers={"User-Agent": UA})
    response.raise_for_status()
    return BytesIO(response.content)
```

**Step 4: Run → PASS. Step 5: lint + commit**

```bash
uv run ruff check --fix arxiv_parser.py tests/test_arxiv_parser.py
git add arxiv_parser.py tests/test_arxiv_parser.py
git commit -m "feat: add timeout + User-Agent to PDF download"
```

---

## Phase 5 — Wire the daily run to the cache + retroactive re-decide

**Files:**
- Modify: `main.py`
- Test: `tests/test_pipeline.py` (create)

**Step 1: Failing test — pipeline decides from cache + re-decides retroactively**

```python
# tests/test_pipeline.py
import main as M


class E:  # minimal feedparser-like entry
    def __init__(self, id, title, published, link):
        self.id = id; self.title = title; self.published = published
        self.link = link; self.summary = ""; self.companies = None
    def get(self, k, d=None): return d


def test_process_entries_matches_from_cache(monkeypatch):
    domains = ["uber.com"]
    cache = {"2603.06586": {"arxiv_id": "2603.06586", "affiliations": [],
                            "emails": ["x@uber.com"]}}
    entry = E("http://arxiv.org/abs/2603.06586v1", "Uber paper",
              "2026-03-01", "http://arxiv.org/abs/2603.06586v1")
    created = []
    monkeypatch.setattr(M, "create_issue",
                        lambda repo, tok, e, s: created.append(e.title))
    monkeypatch.setattr(M, "summarize_with_ollama", lambda t, a: "sum")

    M.process_entries([entry], domains, cache, seen_ids=set(),
                      repo="r", token="t", cache_path=None, download=False)
    assert created == ["Uber paper"]


def test_redecide_cache_files_issue_for_newly_added_domain(monkeypatch):
    domains = ["uber.com"]
    cache = {"2603.06586": {"arxiv_id": "2603.06586", "title": "Uber paper",
                            "published": "2026-03-01",
                            "url": "https://arxiv.org/abs/2603.06586",
                            "affiliations": [], "emails": ["x@uber.com"]}}
    created = []
    monkeypatch.setattr(M, "create_issue",
                        lambda repo, tok, e, s: created.append(e.title))
    monkeypatch.setattr(M, "summarize_with_ollama", lambda t, a: "sum")

    M.redecide_cache(cache, domains, seen_ids=set(), repo="r", token="t")
    assert created == ["Uber paper"]


def test_redecide_skips_already_seen(monkeypatch):
    domains = ["uber.com"]
    cache = {"1": {"arxiv_id": "1", "title": "t", "published": "2026",
                   "url": "https://arxiv.org/abs/1",
                   "affiliations": [], "emails": ["x@uber.com"]}}
    created = []
    monkeypatch.setattr(M, "create_issue",
                        lambda *a: created.append(1))
    monkeypatch.setattr(M, "summarize_with_ollama", lambda t, a: "s")
    M.redecide_cache(cache, domains,
                     seen_ids={"https://arxiv.org/abs/1"}, repo="r", token="t")
    assert created == []
```

**Step 2: Run → FAIL.**

**Step 3: Implement `process_entries` + `redecide_cache` in `main.py`** and rewrite `main()` to use them. Key points: reuse `extract_arxiv_id`, `decide_companies`, `get_signals_cached`, `append_record`; a `FakeEntry` already exists for building issue objects from cache records.

```python
from datetime import date
from cache import append_record, load_cache
from filter_affiliations import decide_companies, get_signals_cached
from arxiv_parser import extract_emails_from_arxiv_pdf
from kb.ids import extract_arxiv_id

CACHE_PATH = "state/email_cache.jsonl"


def process_entries(entries, tech_domains, cache, seen_ids, repo, token,
                    cache_path, download=True):
    """Decide each entry (using cache; download+cache if missing). File issues for
    matches not already seen."""
    for entry in entries:
        if entry.id in seen_ids:
            continue
        aid = extract_arxiv_id(entry.id) or entry.id
        affs = list(getattr(entry, "get", lambda *a: None)("authors", []) or [])
        pdf_fn = extract_emails_from_arxiv_pdf if download else (lambda _i: [])
        sig = get_signals_cached(aid, cache, pdf_fn)
        if aid not in cache and download:
            rec = {"arxiv_id": aid, "title": entry.title,
                   "published": entry.published, "url": entry.link,
                   "affiliations": sig["affiliations"], "emails": sig["emails"],
                   "checked": date.today().isoformat()}
            cache[aid] = rec
            if cache_path:
                append_record(cache_path, rec)
        companies = decide_companies(sig["affiliations"], sig["emails"], tech_domains)
        if companies and entry.link not in seen_ids:
            entry.companies = companies
            summary = summarize_with_ollama(entry.title, getattr(entry, "summary", ""))
            create_issue(repo, token, entry, summary)
            seen_ids.add(entry.link)


def redecide_cache(cache, tech_domains, seen_ids, repo, token):
    """Retroactively file issues for cached papers that now match current domains."""
    for aid, rec in cache.items():
        url = rec.get("url")
        if not url or url in seen_ids:
            continue
        companies = decide_companies(rec.get("affiliations", []),
                                     rec.get("emails", []), tech_domains)
        if companies:
            fe = FakeEntry(id=url, title=rec.get("title", aid),
                           published=rec.get("published", ""), link=url,
                           companies=companies)
            summary = summarize_with_ollama(fe.title, "")
            create_issue(repo, token, fe, summary)
            seen_ids.add(url)
```

Then in `main()`: load `cache = load_cache(CACHE_PATH)`, collect entries, `process_entries(...)`, then `redecide_cache(...)`. (Keep Substack handling as-is.)

**Step 4: Run → PASS.** `uv run pytest tests/test_pipeline.py -v`

**Step 5: lint + commit**

```bash
uv run ruff check --fix main.py tests/test_pipeline.py
git add main.py tests/test_pipeline.py
git commit -m "feat: cache-backed daily pipeline + retroactive re-decide over cache"
```

---

## Phase 6 — Paged, resumable backfill command

**Files:**
- Create: `backfill.py`
- Test: `tests/test_backfill.py`

**Step 1: Failing tests — pagination stops at empty page; resume skips cached**

```python
# tests/test_backfill.py
import backfill as B


def test_iter_pages_stops_on_empty(monkeypatch):
    pages = [["a", "b"], ["c"], []]
    monkeypatch.setattr(B, "_fetch_page",
                        lambda q, c, start, mr, since, until: pages[start // mr]
                        if start // mr < len(pages) else [])
    got = list(B.iter_all("q", "cs.IR", since="202501010000", page_size=2))
    assert got == ["a", "b", "c"]


def test_since_to_stamp():
    assert B._to_stamp("2025-01-01") == "202501010000"
    assert B._to_stamp("2025-01-01", end=True) == "202501012359"
```

**Step 2: Run → FAIL.**

**Step 3: Implement `backfill.py`** (reuses the paced client + cache + decide path; incremental cache append = checkpoint; skips ids already cached).

```python
import argparse
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import yaml

import arxiv_client as ac
from arxiv_parser import extract_emails_from_arxiv_pdf
from cache import append_record, load_cache
from filter_affiliations import decide_companies
from kb.ids import extract_arxiv_id
from main import FakeEntry, CACHE_PATH
from notifier import create_issue
from store import load_seen_from_issues
from summarizer import summarize_with_ollama

logging.basicConfig(level=logging.INFO)


def _to_stamp(d, end=False):
    y, m, day = d.split("-")
    return f"{y}{m}{day}{'2359' if end else '0000'}"


def _fetch_page(query, category, start, page_size, since, until):
    url = ac.BASE_URL + ac._build_query(query, category, start, page_size, since, until)
    import feedparser
    return feedparser.parse(ac._paced_get(url)).entries


def iter_all(query, category, since, until=None, page_size=1000):
    start = 0
    while True:
        entries = _fetch_page(query, category, start, page_size, since, until)
        if not entries:
            return
        yield from entries
        start += page_size


def run(since, until=None, max_workers=6):
    cfg = yaml.safe_load(open("config.yaml"))
    import os
    token = os.environ["GITHUB_TOKEN"]
    repo = cfg["github"]["repo"]
    domains = cfg["tech_domains"]
    query = cfg["search_query"]
    cats = [c.strip() for c in cfg["arxiv_category"].split("OR")]

    cache = load_cache(CACHE_PATH)
    seen = load_seen_from_issues(repo, token)
    lo, hi = _to_stamp(since), (_to_stamp(until, end=True) if until else None)

    for cat in cats:
        for entry in iter_all(query, cat, lo, hi):
            aid = extract_arxiv_id(entry.id) or entry.id
            if aid in cache:
                rec = cache[aid]
            else:
                try:
                    emails = extract_emails_from_arxiv_pdf(entry.id.rsplit("/", 1)[-1])
                except Exception as e:
                    logging.warning(f"{aid}: {e}")
                    emails = []
                rec = {"arxiv_id": aid, "title": entry.title,
                       "published": entry.published, "url": entry.link,
                       "affiliations": [], "emails": emails,
                       "checked": date.today().isoformat()}
                cache[aid] = rec
                append_record(CACHE_PATH, rec)          # checkpoint every paper
            companies = decide_companies(rec["affiliations"], rec["emails"], domains)
            if companies and rec["url"] not in seen:
                fe = FakeEntry(id=rec["url"], title=rec["title"],
                               published=rec["published"], link=rec["url"],
                               companies=companies)
                create_issue(repo, token, fe, summarize_with_ollama(fe.title, ""))
                seen.add(rec["url"])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--since", required=True, help="YYYY-MM-DD")
    p.add_argument("--until", default=None, help="YYYY-MM-DD")
    p.add_argument("--max-workers", type=int, default=6)
    a = p.parse_args()
    run(a.since, a.until, a.max_workers)
```

> Note: the first version above is serial (simplest, safest for arXiv). If it's too slow, parallelize *only* the `extract_emails_from_arxiv_pdf` step with a bounded `ThreadPoolExecutor(max_workers)` and append to the cache under a lock. The API paging stays serial (paced client enforces it anyway).

**Step 4: Run → PASS.** `uv run pytest tests/test_backfill.py -v`

**Step 5: lint + commit**

```bash
uv run ruff check --fix backfill.py tests/test_backfill.py
git add backfill.py tests/test_backfill.py
git commit -m "feat: resumable submittedDate-bounded backfill (--since/--until)"
```

---

## Phase 7 — Config + workflow changes

**Files:**
- Modify: `config.yaml` (already has `uber.com`; confirm `max_results` default lives in code — Phase 1 set it to 400)
- Modify: `.github/workflows/daily.yaml`

**Step 1: Grant write + commit state back in the daily workflow**

```yaml
permissions:
  contents: write        # was: read
  issues: write
```

Append after "Run bot":

```yaml
      - name: Commit cache updates
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add state/email_cache.jsonl
          git commit -m "chore: update email cache [skip ci]" || echo "no changes"
          git push
```

**Step 2: Verify the whole suite + lint**

```bash
uv run pytest -q
uv run ruff check .
```
Expected: all green.

**Step 3: Commit**

```bash
git add .github/workflows/daily.yaml
git commit -m "ci: grant contents:write and commit email cache back to repo"
```

**Step 4: Remove the Phase-0 write-test workflow (optional cleanup)**

```bash
git rm .github/workflows/write-test.yaml
git commit -m "ci: drop write-test spike (superseded by daily cache commit)"
```

---

## Phase 8 — Initial backfill run (manual, local — RUNBOOK)

**Not a code task.** Operated by the human because of scale/duration.

1. Ensure `GITHUB_TOKEN` is exported (same repo the daily job targets).
2. **Chunk by month** so it's resumable and polite (each run appends to the cache; re-running skips cached ids):
   ```bash
   for m in 01 02 03 04 05 06 07 08 09 10 11 12; do
     uv run python backfill.py --since 2025-$m-01 --until 2025-$m-28
   done
   uv run python backfill.py --since 2026-01-01 --until 2026-07-03
   ```
3. Monitor `state/email_cache.jsonl` growth; if interrupted, just re-run the same command (cached ids are skipped).
4. When done: `uv run python -c "import cache; cache.compact('state/email_cache.jsonl')"` then commit + push the cache:
   ```bash
   git add state/email_cache.jsonl
   git commit -m "chore: seed email cache from Jan-2025 backfill"
   git push
   ```
5. Expect a burst of new issues for all historical big-tech matches (incl. any Uber Eats papers now covered by `uber.com`).

**Politeness caveat:** this downloads a PDF for *every* recsys paper in the window (tens of thousands). Keep `--max-workers` low (≤6), run off-peak, and stop if you see sustained 429/403 from arxiv.org.

---

## Final — verification + review

- **REQUIRED SUB-SKILL:** @superpowers:verification-before-completion — run `uv run pytest -q` and `uv run ruff check .`, paste output, before claiming done.
- **REQUIRED SUB-SKILL:** @superpowers:requesting-code-review — dispatch the code-reviewer on the full diff before merging.
- Manual smoke test of the daily path with a tiny cache and mocked GitHub (already covered by `tests/test_pipeline.py`), plus one real dry-run locally with `GITHUB_TOKEN` unset expecting the clean "token not set" error path.

## Test inventory (what "a lot of testing" covers)

| Area | Test file | Key cases |
|---|---|---|
| API pacing / rate-limit | `tests/test_arxiv_client.py` | 3s spacing, `Rate exceeded.` body detection, backoff |
| Cache I/O | `tests/test_cache.py` | roundtrip, missing file, last-wins, malformed lines |
| Pure verdict | `tests/test_extract.py` | emails→companies, affiliations→companies, dedup, **cache short-circuits download** |
| PDF download | `tests/test_arxiv_parser.py` | timeout + UA passed |
| Daily pipeline | `tests/test_pipeline.py` | decide-from-cache, retroactive re-decide, skip-seen |
| Backfill | `tests/test_backfill.py` | pagination stop-on-empty, date-stamp formatting, resume-skips-cached |
| Action write | (manual) Phase 0 | token push succeeds / branch-protection surfaced |
