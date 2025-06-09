import re


def extract_affiliations(entry):
    """
    Yield each author‐affiliation (lowercased) from an arXiv entry, if present.
    """
    for author in entry.get("authors", []):
        if "affiliation" in author:
            yield author["affiliation"].lower()
        elif "arxiv_affiliation" in author:
            yield author["arxiv_affiliation"].lower()


def has_big_tech_author(entry, tech_domains):
    """
    1) Try to detect any of our `tech_domains` in the author‐affiliation fields.
    2) If none found, fall back to scanning title+summary text (again, whole‐word alias).
    Returns True (and sets entry.companies) as soon as at least one domain is found.
    """
    # Pre‐compile patterns for each domain:
    #   alias = domain without TLD (e.g. "meta" from "meta.com")
    #   we'll match alias as a whole word; matching domain literally is optional,
    #   but we include it in case someone wrote "Meta.com" in their affiliation.
    patterns = []
    for dom in tech_domains:
        alias = dom.split(".")[0].lower()
        # \b ensures we only match "meta" as its own word (not "metadata")
        alias_pat = re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE)
        # for the full domain (e.g. "meta.com"), we also do a whole‐token match:
        #   (?<!\S) and (?!\S) ensure that "meta.com" is surrounded by whitespace or start/end
        domain_pat = re.compile(rf"(?<!\S){re.escape(dom)}(?!\S)", re.IGNORECASE)
        patterns.append((dom, alias, alias_pat, domain_pat))

    # 1) Check author affiliations first
    for aff in extract_affiliations(entry):
        for dom, alias, alias_pat, domain_pat in patterns:
            if alias_pat.search(aff) or domain_pat.search(aff):
                # Found a match → assign the capitalized alias (e.g. "Meta") and return
                entry.companies = [alias.capitalize()]
                return True

    # 2) Fallback: look in title + abstract
    text = (entry.title + " " + entry.summary).lower()
    found = []
    for dom, alias, alias_pat, domain_pat in patterns:
        if alias_pat.search(text) or domain_pat.search(text):
            found.append(alias.capitalize())

    if found:
        # Deduplicate in case “meta” appeared twice
        entry.companies = sorted(set(found))
        return True

    return False
