# arxiv_rec_finder

A bot that automatically monitors recent arXiv papers and Substack posts related to recommendation, ranking, and retrieval research—flags those authored or affiliated with major tech companies, summarizes them via Ollama, and creates GitHub issues for further review.

---

## Table of Contents

- [Features](#features)  
- [Requirements](#requirements)  
- [Installation](#installation)  
- [Usage](#usage)  
- [GitHub Actions Workflow](#github-actions-workflow)  
- [License](#license)  

---

## Features

- **arXiv Monitoring**  
  - Queries arXiv API for the latest papers in specified categories/keywords.  
  - Filters entries by big‑tech author affiliations (metadata, PDF email parsing, or title/abstract fallback).  
  - Summarizes accepted papers via Ollama (3‑sentence summary).  
  - Opens a GitHub issue per qualifying paper with year‑ and company‑labels, metadata, and summary.  

- **Substack Monitoring**  
  - Fetches user subscriptions for given Substack usernames.  
  - Retrieves latest posts, skips already‐seen URLs, summarizes via Ollama, and creates GitHub issues.  

- **Deduplication**  
  - Tracks all previously created issue URLs (arXiv ↔ issue, Substack ↔ issue) and avoids reposting.  

- **Persistent extraction cache**  
  - Stores each paper's extracted author emails/affiliations in `state/email_cache.jsonl`, so a PDF is downloaded at most once.  
  - The affiliation verdict is recomputed from the cache each run, so adding a new company to `config.yaml` retroactively files issues for already‑cached papers (no re‑download).  
  - The daily Action commits the updated cache back to the repo.  

- **Deterministic Issue Labeling**  
  - Creates “year” and “company” labels with deterministic hex colors (MD5‑based).  

- **GitHub Actions Integration**  
  - Daily scheduled run (`.github/workflows/daily.yaml`), installs dependencies, starts Ollama, and executes `main.py`.  

---

## Requirements

- Python 3.12  
- GitHub Personal Access Token (with “repo” privileges to create issues)  
- Ollama installed (for local testing and GitHub Actions)  

---

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/<your-org>/arxiv_rec_finder.git
   cd arxiv_rec_finder
   ```
2. Install dependencies:
   ```bash
    uv sync
    ```
3. Set up Ollama:
    - Install Ollama from [ollama.com](https://ollama.com/).
    - Start the Ollama server:
      ```bash
      ollama serve
      ```
## Usage

### Locally

1. Set up your envirnonment variables:
    ```bash
    export GITHUB_TOKEN=<your_github_token>
    ```

2. Run the script:
    ```bash
    uv run main.py
    ```

### Backfill (historical papers)

The daily job only scans the most recent submissions. To ingest older papers,
use the resumable, date-bounded backfill. It pages the arXiv API within a
`submittedDate` window, downloads each candidate's PDF once, records the
extraction in `state/email_cache.jsonl` (a per-paper checkpoint), decides
affiliations, and files issues for matches — the same path as the daily run.

```bash
export GITHUB_TOKEN=<your_github_token>

# one month at a time (recommended); run in the background — it can take a while
nohup uv run python backfill.py --since 2025-01-01 --until 2025-01-31 \
    > /tmp/backfill_2025_01.log 2>&1 &

# monitor
tail -f /tmp/backfill_2025_01.log      # "Downloading:" progress
wc -l state/email_cache.jsonl          # cache grows
```

- **Resumable:** if interrupted, re-run the exact same command — cached IDs are
  skipped (no re-download), so it continues where it left off.
- **Commit the cache afterward** (stage *only* the cache file):
  ```bash
  git checkout -- uv.lock            # discard any private-index rewrite `uv` made
  git add state/email_cache.jsonl    # never `git add -A`
  git commit -m "chore: seed email cache from <window> backfill"
  git push
  ```
- **Adding a new affiliation later?** Add the domain to `config.yaml` and the
  next daily run re-decides over the whole cache and files issues for already
  cached papers — no re-download needed.

> Note: every `uv run` may rewrite `uv.lock` to point at a private package
> index. Always `git checkout -- uv.lock` before committing, and never commit it.

## Github Actions Workflow

- File: `.github/workflows/daily.yaml`
- Runs daily (UTC 13:00) or on manual dispatch.
- Steps:
    - Checkout repository.
    - Install UV (astral-sh/setup-uv@v6) and sync dependencies (uv sync).
    - Install and start Ollama server (ollama serve).
    - Pull deepseek-r1:latest model.
    - Run python main.py (requires GITHUB_TOKEN in secrets).
    - Commit the updated `state/email_cache.jsonl` back to the repo (requires `contents: write` permission).

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.






