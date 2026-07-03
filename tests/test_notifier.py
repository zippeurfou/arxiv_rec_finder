# tests/test_notifier.py
import notifier as N


def test_labels_drops_empty_year():
    # published="" -> year="" must be filtered out
    assert N._labels("", ["Uber"]) == ["Uber"]


def test_labels_keeps_year_and_companies():
    assert N._labels("2026", ["Uber", "Meta"]) == ["2026", "Uber", "Meta"]


def test_labels_drops_empty_companies():
    assert N._labels("2026", ["Uber", "", None]) == ["2026", "Uber"]


def test_create_issue_drops_empty_year_label(monkeypatch):
    """With published="", the labels requested from GitHub contain no ""."""

    class Entry:
        published = ""
        companies = ["Uber"]
        title = "A paper"
        link = "http://arxiv.org/abs/2603.06586v1"

    created_labels = []
    ensured_labels = []

    class FakeRepo:
        def get_label(self, name):
            ensured_labels.append(name)
            return object()

        def create_label(self, name, color):
            created_labels.append(name)

        def create_issue(self, title, body, labels):
            created_labels.extend(labels)

    class FakeGithub:
        def __init__(self, token):
            pass

        def get_repo(self, repo_name):
            return FakeRepo()

    monkeypatch.setattr(N, "Github", FakeGithub)

    N.create_issue("owner/repo", "tok", Entry(), "summary")

    assert "" not in ensured_labels
    assert "" not in created_labels
    assert "Uber" in created_labels
