import logging
import re

from arxiv_parser import extract_emails_from_arxiv_pdf


def extract_affiliations(entry):
    """
    Yield each author‐affiliation (lowercased) from an arXiv entry, if present.
    Args:
        entry: arXiv entry object with authors and metadata.
    """
    for author in entry.get("authors", []):
        if "affiliation" in author:
            yield author["affiliation"].lower()
        elif "arxiv_affiliation" in author:
            yield author["arxiv_affiliation"].lower()


def has_big_tech_author(entry, tech_domains, use_text=False):
    """
    Check if the arXiv entry has any authors affiliated with big tech companies.
    This function performs three checks in order:
    1) Try to detect any of our `tech_domains` in the author‐affiliation fields.
    2) If none found, second pass: look at emails extracted from the arXiv PDF
       and check if any email’s domain matches a tech domain.
    3) Finally (optional; only if `use_text=True`), scan title + summary text
       (whole‐word alias match). Returns True (and sets entry.companies) as soon
    as at least one domain is found; otherwise returns False.

    Note:
        This is a bit of a hacky way to detect big tech affiliations
        but it works reasonably well for most cases.
    Args:
        entry: arXiv entry object with authors and metadata.
        tech_domains: list of big tech domains to check against.
        use_text: if True, also scan title + summary text for matches.
    Returns:
        True if any big tech domain is found, False otherwise.
        If True, sets entry.companies to a list of found company names.
    """
    # Pre‐compile patterns for each domain:
    #   alias = domain without TLD (e.g. "meta" from "meta.com")
    #   we'll match alias as a whole word; matching domain literally is optional,
    #   but we include it in case someone wrote "Meta.com" in their affiliation.
    patterns = []
    for dom in tech_domains:
        alias = dom.split(".")[0].lower()
        alias_pat = re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE)
        domain_pat = re.compile(rf"(?<!\S){re.escape(dom)}(?!\S)", re.IGNORECASE)
        patterns.append((dom, alias, alias_pat, domain_pat))

    # 1) Check author affiliations metadata first
    for aff in extract_affiliations(entry):
        for dom, alias, alias_pat, domain_pat in patterns:
            if alias_pat.search(aff) or domain_pat.search(aff):
                entry.companies = [alias.capitalize()]
                return True

    # 2) Second pass: extract emails from PDF and check domains
    try:
        # entry.id is usually a URL like "http://arxiv.org/abs/2505.15091v3"
        arxiv_id = entry.id.rsplit("/", 1)[-1]
        emails = extract_emails_from_arxiv_pdf(arxiv_id)
        for email in emails:
            email_domain = email.split("@")[-1].lower()
            for dom, alias, _, _ in patterns:
                # match if the email domain ends with the tech domain (e.g. "research.meta.com" endswith "meta.com")
                if email_domain == dom or email_domain.endswith(f".{dom}"):
                    entry.companies = [alias.capitalize()]
                    return True
    except Exception as e:
        logging.warning(f"Failed to extract emails from PDF for {entry.id}: {e}")
        # If PDF download or parsing fails, skip this pass silently
        pass

    # 3) Fallback: look in title + abstract, only if use_text=True
    # This is pretty noisy, so we only do it if explicitly requested.
    if use_text:
        text = (entry.title + " " + entry.summary).lower()
        found = []
        for dom, alias, alias_pat, domain_pat in patterns:
            if alias_pat.search(text) or domain_pat.search(text):
                found.append(alias.capitalize())

        if found:
            entry.companies = sorted(set(found))
            return True

    return False


def _domain_patterns(tech_domains):
    """Compile (alias, alias_pat, domain_pat, domain) tuples for each domain.

    alias = domain without TLD (e.g. "meta" from "meta.com"). alias_pat is a
    whole-word case-insensitive match; domain_pat matches the literal domain.
    """
    pats = []
    for dom in tech_domains:
        alias = dom.split(".")[0].lower()
        pats.append(
            (
                alias,
                re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE),
                re.compile(rf"(?<!\S){re.escape(dom)}(?!\S)", re.IGNORECASE),
                dom,
            )
        )
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
        return {
            "affiliations": rec.get("affiliations", []),
            "emails": rec.get("emails", []),
        }
    emails = []
    try:
        emails = pdf_email_fn(arxiv_id)
    except Exception as e:
        logging.warning(f"email extraction failed for {arxiv_id}: {e}")
    return {"affiliations": list(affiliations or []), "emails": emails}
