---
name: arxiv-backfill
description: >-
  Run the arxiv_rec_finder historical backfill locally to ingest older big-tech
  recommendation/ranking/retrieval papers that the daily job's recent-window
  scan misses. Use this whenever the task involves backfilling a date range of
  arXiv papers for this repo (e.g. "backfill January 2025", "catch older Uber
  Eats papers", "seed the email cache since 2025"), running backfill.py with
  --since/--until, extending state/email_cache.jsonl, or filing GitHub issues
  for historical big-tech matches. Also use when a newly added affiliation
  domain needs older papers reconsidered beyond the daily recent window.
---

# arXiv historical backfill (local)

## What it does

`backfill.py` pages the arXiv API over a `submittedDate` window, downloads each
candidate paper's PDF once, extracts author emails/affiliations into
`state/email_cache.jsonl` (a per-paper, fsync'd checkpoint), decides big-tech
affiliation via `config.yaml:tech_domains`, and files a GitHub issue for each
match — the exact same extract → cache → decide → issue path as the daily
`main.py`. It is **serial and resumable**, and meant to be run **locally** (it
is far too long for the 6h GitHub Action limit).

## Prerequisites

- Run from the repo root (`~/Projects/arxiv_rec_finder`).
- Export a GitHub token with `repo` scope: `export GITHUB_TOKEN=<token>`.
- Ollama is optional — with no model present, summaries fall back to the paper
  abstract (harmless warnings in the log).

## Running it (chunk by month, in the background)

arXiv is often slow/degraded and the run is long, so background it and monitor.
Each run resumes from whatever is already cached, so re-running is safe.

```bash
export GITHUB_TOKEN=<token>
nohup uv run python backfill.py --since 2025-01-01 --until 2025-01-31 \
    > /tmp/backfill_2025_01.log 2>&1 &
```

Monitor (the fsync'd cache count is the reliable progress signal; `Downloading:`
lines are block-buffered stdout and lag):

```bash
wc -l state/email_cache.jsonl                     # grows per paper
grep -Ei 'HTTP 4|HTTP 5|rate exceeded' /tmp/backfill_2025_01.log | grep -vi ollama
```

To process the whole history, repeat month by month (`--since 2025-02-01
--until 2025-02-28`, …) up to the present.

## Resumability & robustness

- **Interrupted?** Re-run the identical command — cached IDs are skipped (no
  re-download), so it continues where it stopped.
- Per-category and per-paper failures are isolated: a transient arXiv 429/timeout
  or one bad PDF logs a warning and the run continues.
- **Expected imperfections:** ~15-25% of papers yield no extractable emails
  (404/withdrawn, timeouts, or emails not in the first PDF pages) — cached as
  scanned, not retried. arXiv's `submittedDate` filter bleeds a few adjacent-month
  papers into each window; harmless because the next chunk skips them via the cache.

## Committing the cache (mind `uv.lock`!)

**Every `uv run` may rewrite `uv.lock` to point at a private package index.**
Always discard that and stage ONLY the cache file:

```bash
git checkout -- uv.lock             # drop the private-index rewrite uv made
git status -s                       # sanity: only state/email_cache.jsonl should matter
git add state/email_cache.jsonl     # NEVER `git add -A`
git commit -m "chore: seed email cache from <window> backfill"
git pull --rebase origin main       # integrate any concurrent daily-bot cache commit
git push
```

No manual `compact` needed — the file is one line per paper, and the daily Action
compacts it on its next run.

**Safe push — never `git push --force`.** The daily bot may commit the cache while a
local backfill runs; a force-push would DROP its cached papers. If `git push` is
rejected, or `git pull --rebase` conflicts on `state/email_cache.jsonl`, reconcile by
UNION — the cache is dedup-by-`arxiv_id`, so concatenating both sides and compacting is
lossless:

```bash
git rebase --abort 2>/dev/null || true      # if a rebase is mid-conflict
git fetch origin main
git show origin/main:state/email_cache.jsonl > /tmp/remote_cache.jsonl
cat /tmp/remote_cache.jsonl state/email_cache.jsonl > /tmp/union.jsonl
mv /tmp/union.jsonl state/email_cache.jsonl
uv run python -c "import cache; cache.compact('state/email_cache.jsonl')"  # dedup+sort
git checkout -- uv.lock
git reset --soft origin/main                # linear: sit on latest remote (cache is all we commit)
git add state/email_cache.jsonl
git commit -m "chore: union backfill cache with remote"
git push
```

## Verify a completed run

```bash
uv run python -c "
import json, collections, yaml
from filter_affiliations import decide_companies
dom = yaml.safe_load(open('config.yaml'))['tech_domains']
c = collections.Counter(); matches = 0
for l in open('state/email_cache.jsonl'):
    r = json.loads(l); c[r['arxiv_id'][:4]] += 1
    if decide_companies(r.get('affiliations', []), r.get('emails', []), dom): matches += 1
print('by month:', dict(sorted(c.items())))
print('total papers:', sum(c.values()), '| affiliation matches (issues):', matches)
"
git checkout -- uv.lock
```

Confirm the month distribution is dominated by the requested window with **no
far-future IDs** (e.g. no `2606`/`2607`); a far-future leak means the arXiv query
lost its `submittedDate`/`cat` filter (the OR group must stay parenthesized in
`arxiv_client._build_query`).

## After backfilling: refresh the recsys knowledge base

A large backfill files many GitHub issues. To pull them into the recsys-industry
knowledge base, run the **recsys-industry-kb** skill's refresh; for hundreds of
new issues, dispatch parallel subagents for the extraction step.
