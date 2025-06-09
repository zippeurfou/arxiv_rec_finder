def extract_affiliations(entry):
    for author in entry.get("authors", []):
        if "affiliation" in author:
            yield author["affiliation"].lower()
        elif "arxiv_affiliation" in author:
            yield author["arxiv_affiliation"].lower()

def has_big_tech_author(entry, tech_domains):
    for aff in extract_affiliations(entry):
        for dom in tech_domains:
            key = dom.split(".")[0]
            if key in aff or dom in aff:
                entry.companies = [key.capitalize()]
                return True
    # fallback: look in title/abstract
    text = (entry.title + " " + entry.summary).lower()
    matches = [d.split(".")[0].capitalize() for d in tech_domains if d.split(".")[0] in text or d in text]
    if matches:
        entry.companies = matches
        return True
    return False

