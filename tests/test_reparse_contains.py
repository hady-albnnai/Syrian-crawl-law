import argparse
import crawler, cli


def test_reparse_forced_by_url_fragment(monkeypatch):
    monkeypatch.setattr(crawler, "REPARSE_URL_CONTAINS", ("details/10918",))
    assert crawler.reparse_forced({"url": "https://www.wipo.int/wipolex/ar/legislation/details/10918"})
    assert not crawler.reparse_forced({"url": "https://www.wipo.int/wipolex/ar/legislation/details/1"})
    assert crawler.reparse_forced({"url": "https://x", "reparse": True})


def test_crawl_cli_sets_reparse_fragment(monkeypatch):
    seen = {}
    monkeypatch.setattr(crawler, "start_crawling", lambda **kw: seen.update(kw))
    monkeypatch.setattr(crawler, "REPARSE_URL_CONTAINS", ())
    cli.cmd_crawl(argparse.Namespace(mode="limited", yes=False, pages=1, domain="d",
                                     reparse_contains="wipolex/ar/legislation/details"))
    assert crawler.REPARSE_URL_CONTAINS == ("wipolex/ar/legislation/details",)
    assert seen["domain"] == "d"
