import arxiv_parser as ap


def test_download_pdf_uses_timeout_and_ua(monkeypatch):
    seen = {}

    class R:
        content = b"%PDF-1.4"

        def raise_for_status(self):
            pass

    def fake_get(url, timeout=None, headers=None):
        seen["url"] = url
        seen["timeout"] = timeout
        seen["ua"] = (headers or {}).get("User-Agent")
        return R()

    monkeypatch.setattr(ap.requests, "get", fake_get)
    ap.download_pdf("2411.11508v1")
    # value-level assertions: the constants are actually what gets sent
    assert seen["timeout"] == ap.PDF_TIMEOUT
    assert seen["ua"] == ap.UA
    # version suffix is stripped before building the pdf url
    assert seen["url"].endswith("2411.11508.pdf")
