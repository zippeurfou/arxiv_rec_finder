import arxiv_parser as ap


def test_download_pdf_uses_timeout_and_ua(monkeypatch):
    seen = {}

    class R:
        content = b"%PDF-1.4"

        def raise_for_status(self):
            pass

    def fake_get(url, timeout=None, headers=None):
        seen["timeout"] = timeout
        seen["ua"] = (headers or {}).get("User-Agent")
        return R()

    monkeypatch.setattr(ap.requests, "get", fake_get)
    ap.download_pdf("2603.06586")
    assert seen["timeout"] and seen["ua"]
