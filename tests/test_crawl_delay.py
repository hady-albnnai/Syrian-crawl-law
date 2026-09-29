"""احترام Crawl-delay في robots.txt — دون شبكة."""
from urllib.robotparser import RobotFileParser

import fetcher


def _parser(text):
    rp = RobotFileParser()
    rp.parse(text.splitlines())
    return rp


def test_crawl_delay_is_recorded_and_capped(monkeypatch):
    monkeypatch.setattr(fetcher, "RESPECT_ROBOTS", True)
    monkeypatch.setattr(fetcher, "_ROBOT_CACHE", {
        "https://slow.example": _parser("User-agent: *\nCrawl-delay: 5\n"),
        "https://huge.example": _parser("User-agent: *\nCrawl-delay: 999\n"),
        "https://none.example": _parser("User-agent: *\nDisallow: /x\n")})
    monkeypatch.setattr(fetcher, "_CRAWL_DELAY", {})
    assert fetcher.is_allowed("https://slow.example/a")
    assert fetcher.is_allowed("https://huge.example/a")
    assert fetcher.is_allowed("https://none.example/a")
    assert fetcher.crawl_delay_for("https://slow.example/a") == 5.0
    assert fetcher.crawl_delay_for("https://huge.example/a") == fetcher.MAX_CRAWL_DELAY
    assert fetcher.crawl_delay_for("https://none.example/a") == 0.0


def test_honor_crawl_delay_sleeps_between_requests_to_same_origin(monkeypatch):
    slept = []
    monkeypatch.setattr(fetcher.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(fetcher, "_CRAWL_DELAY", {"https://slow.example": 5.0})
    monkeypatch.setattr(fetcher, "_ORIGIN_LAST", {})
    fetcher.honor_crawl_delay("https://slow.example/a")      # أول طلب: لا انتظار
    fetcher.honor_crawl_delay("https://slow.example/b")      # الثاني: ينتظر ~5ث
    fetcher.honor_crawl_delay("https://other.example/a")     # موقع آخر: لا شيء
    assert len(slept) == 1 and 4.0 <= slept[0] <= 5.0
