import re
from io import BytesIO

import requests
from PyPDF2 import PdfReader


def download_pdf(arxiv_id):
    """
    Download the full PDF from arXiv given an arXiv ID like '2411.11508v1'
    """
    base_id = arxiv_id.split("v")[0]  # strip version suffix
    pdf_url = f"https://arxiv.org/pdf/{base_id}.pdf"
    print(f"Downloading: {pdf_url}")
    response = requests.get(pdf_url)
    response.raise_for_status()
    return BytesIO(response.content)


def extract_text_from_pdf(pdf_stream):
    """
    Extract all text from the PDF using PyPDF2
    """
    reader = PdfReader(pdf_stream)
    all_text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            all_text += page_text + "\n"
    return all_text


def find_emails(text):
    """
    Return all email-like strings found in the text, including:
    - Grouped addresses like {user1, user2}@domain.com (allows spaces),
      with domain restricted to lowercase so trailing uppercase letters are excluded.
    - Standalone emails like user@domain.com, with domain restricted to lowercase.
    """
    emails = set()

    # 1. Handle grouped emails: {user1, user2}@domain.com (allows spaces),
    #    domain part only lowercase/digits/dots/hyphens to avoid capturing trailing uppercase.
    grouped_pattern = re.compile(
        r"\{\s*([A-Za-z0-9._+\-]+(?:\s*,\s*[A-Za-z0-9._+\-]+)+)\s*\}\s*@"  # {user1, user2}@
        r"([a-z0-9.\-]+\.[a-z]{2,})"  # domain.tld (lowercase)
    )
    for match in grouped_pattern.finditer(text):
        local_group, domain = match.groups()
        users = [u.strip() for u in local_group.split(",")]
        for user in users:
            if user:
                emails.add(f"{user}@{domain}")

    # 2. Handle standalone emails like user@domain.com,
    #    with domain part only lowercase/digits/dots/hyphens.
    standalone_pattern = re.compile(
        r"[A-Za-z0-9._+\-]+@"  # local part
        r"[a-z0-9.\-]+\.[a-z]{2,}"  # domain.tld (lowercase)
    )
    for match in standalone_pattern.finditer(text):
        emails.add(match.group(0))

    return sorted(emails)


def extract_emails_from_arxiv_pdf(arxiv_id):
    pdf_stream = download_pdf(arxiv_id)
    full_text = extract_text_from_pdf(pdf_stream)
    emails = find_emails(full_text)
    return emails


# 🔍 Try it here
# if __name__ == "__main__":
#     arxiv_id = "2410.16780v2"
#     arxiv_id = "2410.20642v1"
#     arxiv_id = "2410.16823v1"
#     arxiv_id = "2410.11150v1"
#     arxiv_id = "2503.12733v2"
#     emails = extract_emails_from_arxiv_pdf(arxiv_id)
#     print(f"Found emails in arXiv paper {arxiv_id}:\n{emails}")
