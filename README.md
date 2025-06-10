# arxiv_rec_finder

A bot that automatically monitors recent arXiv papers and Substack posts related to recommendation, ranking, and retrieval research—flags those authored or affiliated with major tech companies, summarizes them via Ollama, and creates GitHub issues for further review.

---

## Table of Contents

- [Features](#features)  
- [Requirements](#requirements)  
- [Installation](#installation)  
- [Configuration](#configuration)  
- [Usage](#usage)  
- [Directory Structure](#directory-structure)  
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
  - Tracks all previously created issue URLs (arXiv ↔ issue, Substack ↔ issue) and avoids reposting.  

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

## Github Actions Workflow

- File: `.github/workflows/daily.yaml`
- Runs daily (UTC 13:00) or on manual dispatch.
- Steps:
    - Checkout repository.
    - Install UV (astral-sh/setup-uv@v6) and sync dependencies (uv sync).
    - Install and start Ollama server (ollama serve).
    - Pull deepseek-r1:latest model.
    - Run python main.py (requires GITHUB_TOKEN in secrets).

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.






