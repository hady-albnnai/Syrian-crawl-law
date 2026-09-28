"""سياسات robots/redirect — fixtures محلية بلا اتصالات خارجية."""
import requests

import fetcher


class _Response:
    def __init__(self, status, text="", headers=None, url=""):
        self.status_code = status
        self.text = text
        self.headers = headers or {}
        self.url = url
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"
        self.content = text.encode("utf-8")


def _quiet(monkeypatch):
    monkeypatch.setattr(fetcher, "polite_sleep", lambda: None)
    monkeypatch.setattr(fetcher.time, "sleep", lambda _s: None)
    monkeypatch.setattr(fetcher, "insert_log", lambda *a, **kw: None)
    monkeypatch.setattr(fetcher, "MAX_RETRIES", 1)


def test_same_host_redirect_rechecks_robots_and_returns_final_url(monkeypatch):
    _quiet(monkeypatch)
    requested, checked = [], []
    responses = [
        _Response(302, headers={"Location": "/legal/final"}),
        _Response(200, "نص قانوني", url="https://law.example/legal/final"),
    ]

    def fake_get(url, **kwargs):
        requested.append((url, kwargs.get("allow_redirects")))
        return responses.pop(0)

    monkeypatch.setattr(fetcher.SESSION, "get", fake_get)
    monkeypatch.setattr(fetcher, "is_allowed",
                        lambda url, **_kw: checked.append(url) or True)
    result = fetcher.fetch("https://law.example/start")
    assert result["ok"] is True
    assert result["final_url"] == "https://law.example/legal/final"
    assert [u for u, _ in requested] == [
        "https://law.example/start", "https://law.example/legal/final"]
    assert all(allow is False for _, allow in requested)
    assert checked == ["https://law.example/start", "https://law.example/legal/final"]


def test_cross_host_redirect_is_blocked_without_following(monkeypatch):
    _quiet(monkeypatch)
    requested = []
    monkeypatch.setattr(fetcher.SESSION, "get", lambda url, **kw: (
        requested.append(url) or _Response(
            302, headers={"Location": "https://evil.example/collect"})))
    monkeypatch.setattr(fetcher, "is_allowed", lambda _url, **_kw: True)
    result = fetcher.fetch("https://law.example/start")
    assert result["ok"] is False
    assert result["error"] == "redirect_cross_origin"
    assert requested == ["https://law.example/start"]
    assert fetcher.classify_error(result["error"]) == "block"


def test_redirect_target_disallowed_by_robots_is_not_requested(monkeypatch):
    _quiet(monkeypatch)
    requested, checked = [], []
    monkeypatch.setattr(fetcher.SESSION, "get", lambda url, **kw: (
        requested.append(url) or _Response(302, headers={"Location": "/private"})))

    def allowed(url, **_kw):
        checked.append(url)
        return not url.endswith("/private")

    monkeypatch.setattr(fetcher, "is_allowed", allowed)
    result = fetcher.fetch("https://law.example/start")
    assert result["error"] == "blocked_by_robots_redirect"
    assert requested == ["https://law.example/start"]
    assert checked == ["https://law.example/start", "https://law.example/private"]


def test_robots_network_error_fails_closed(monkeypatch):
    _quiet(monkeypatch)
    fetcher._ROBOT_CACHE.clear()

    def fail(*_args, **_kwargs):
        raise requests.ConnectionError("offline fixture")

    monkeypatch.setattr(fetcher.SESSION, "get", fail)
    parser = fetcher._load_robot_parser("offline.example", "https")
    assert parser.can_fetch(fetcher.USER_AGENT, "https://offline.example/") is False


def test_robots_404_means_no_published_policy(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(fetcher.SESSION, "get",
                        lambda *_a, **_kw: _Response(404))
    parser = fetcher._load_robot_parser("missing.example", "https")
    assert parser.can_fetch(fetcher.USER_AGENT, "https://missing.example/legal") is True


def test_fetch_preview_suppresses_database_event_writes(monkeypatch):
    _quiet(monkeypatch)
    fetcher._ROBOT_CACHE.clear()

    def fail_log(*_a, **_kw):
        raise AssertionError("dry-run must not write crawl_log")

    monkeypatch.setattr(fetcher, "insert_log", fail_log)

    def fake_get(url, **_kwargs):
        if url.endswith("/robots.txt"):
            return _Response(404)
        return _Response(200, "نص قانوني", url=url)

    monkeypatch.setattr(fetcher.SESSION, "get", fake_get)
    result = fetcher.fetch("https://law.example/legal", record_log=False)
    assert result["ok"] is True


def test_redirect_policy_rejects_https_downgrade_and_foreign_host():
    assert fetcher._same_host_redirect(
        "http://law.example/a", "https://law.example/b") is True
    assert fetcher._same_host_redirect(
        "https://law.example/a", "http://law.example/b") is False
    assert fetcher._same_host_redirect(
        "https://law.example/a", "https://other.example/b") is False
    assert fetcher._same_host_redirect(
        "https://law.example/a", "javascript:alert(1)") is False
