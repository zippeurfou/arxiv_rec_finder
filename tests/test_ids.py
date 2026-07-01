import pytest
from kb.ids import extract_arxiv_id


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://arxiv.org/abs/2606.29534v1", "2606.29534"),
        ("https://arxiv.org/pdf/1809.00060v1", "1809.00060"),
        ("https://arxiv.org/abs/2606.29534", "2606.29534"),
        ("see https://arxiv.org/pdf/1809.00060v2 here", "1809.00060"),
        ("no arxiv link", None),
    ],
)
def test_extract_arxiv_id(url, expected):
    assert extract_arxiv_id(url) == expected
