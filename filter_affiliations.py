import logging
import re

from arxiv_parser import extract_emails_from_arxiv_pdf


def extract_affiliations(entry):
    """
    Yield each author‐affiliation (lowercased) from an arXiv entry, if present.
    """
    for author in entry.get("authors", []):
        if "affiliation" in author:
            yield author["affiliation"].lower()
        elif "arxiv_affiliation" in author:
            yield author["arxiv_affiliation"].lower()


def has_big_tech_author(entry, tech_domains, use_text=False):
    """
    1) Try to detect any of our `tech_domains` in the author‐affiliation fields.
    2) If none found, second pass: look at emails extracted from the arXiv PDF
       and check if any email’s domain matches a tech domain.
    3) Finally (optional; only if `use_text=True`), scan title + summary text
       (whole‐word alias match). Returns True (and sets entry.companies) as soon
    as at least one domain is found; otherwise returns False.
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
