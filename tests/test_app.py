import asyncio
import socket

import pytest
from fastapi.testclient import TestClient

from app import audit
from app.fetch import FetchError, PublicResolver, validate_url
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_site_files(monkeypatch):
    """robots.txt / llms.txt default to 404 so tests never touch the network."""
    async def missing(url):
        return 404, "", "text/html"
    monkeypatch.setattr(audit, "fetch_text", missing)


def audit_checks(monkeypatch, html, robots=None, final_url="https://example.com/page"):
    async def page(url):
        return final_url, html, ""

    async def site_file(url):
        if robots is not None and url.endswith("/robots.txt"):
            return 200, robots, "text/plain"
        return 404, "", "text/html"

    monkeypatch.setenv("XAI_API_KEY", "")
    monkeypatch.setattr(audit, "fetch_page", page)
    monkeypatch.setattr(audit, "fetch_text", site_file)
    report = client.post("/api/audit", json={"url": "https://example.com/page"}).json()
    return {c["label"]: c for s in report["sections"].values() for c in s["checks"]}


@pytest.mark.parametrize("url", [
    "file:///secret", "https://example.com:8443/", "http://user@example.com/",
    "http://127.0.0.1/", "http://127.1/", "http://2130706433/", "http://[::1]/",
    "http://169.254.169.254/", "http://224.0.0.1/", "https://foo.localhost/",
    "https://example.com\\path", "http://127.0.0.1./", "https://",
])
def test_unsafe_urls(url):
    with pytest.raises(FetchError):
        validate_url(url)


def test_resolver_rejects_mixed_results(monkeypatch):
    async def run():
        async def fake_dns(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
                    for ip in ("8.8.8.8", "192.168.0.2")]

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_dns)
        with pytest.raises(FetchError):
            await PublicResolver().resolve("example.com", 443)
    asyncio.run(run())


def test_resolver_returns_numeric_addresses(monkeypatch):
    async def run():
        async def fake_dns(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_dns)
        result = await PublicResolver().resolve("example.com", 443)
        assert result[0]["host"] == "8.8.8.8"
        assert result[0]["flags"] == socket.AI_NUMERICHOST
    asyncio.run(run())


def test_api_validation():
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.post("/api/audit", json={}).status_code == 422
    assert client.post("/api/audit", json={"url": "http://localhost"}).status_code == 422


def test_report_without_key(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "")

    async def page(url):
        return url, """
        <title>A descriptive page title about website audits</title>
        <link rel="canonical" href="https://example.com/">
        <h1>Website audits</h1><h2>How does it work?</h2>
        <p>This paragraph contains twenty words to demonstrate that the audit will find a
        paragraph of suitable length on the page.</p>
        <script type="application/ld+json">{"@context":"https://schema.org","@graph":[
          {"@type":"WebPage","name":"Audits"},
          {"@type":"FAQPage","mainEntity":[{"@type":"Question","name":"How does it work?",
            "acceptedAnswer":{"@type":"Answer","text":"It checks the page."}}]}]}</script>
        """, "noindex"

    monkeypatch.setattr(audit, "fetch_page", page)
    response = client.post("/api/audit", json={"url": "https://example.com/"})
    assert response.status_code == 200
    report = response.json()
    checks = {c["label"]: c["passed"] for s in report["sections"].values() for c in s["checks"]}
    for label in ("HTTPS", "Page title", "Canonical link", "Crawlable in robots.txt",
                  "AI answer-engine crawler access", "Question headings", "Answer-first sections",
                  "Structured data syntax", "Answer-focused schema type", "Schema required properties",
                  "Schema matches visible content"):
        assert checks[label], label
    for label in ("No generic noindex directive", "Meta description", "XML sitemap declared",
                  "llms.txt (emerging)"):
        assert not checks[label], label
    assert all(0 <= s["score"] <= 100 for s in report["sections"].values())
    assert report["ai_status"] == "disabled"


def test_robots_and_ai_crawler_checks(monkeypatch):
    robots = ("User-agent: GPTBot\nDisallow: /\n\nUser-agent: PerplexityBot\nDisallow: /\n\n"
              "User-agent: *\nAllow: /\n\nSitemap: https://example.com/sitemap.xml\n")
    checks = audit_checks(monkeypatch, "<h1>Hi</h1>", robots=robots)
    assert checks["Crawlable in robots.txt"]["passed"]
    assert checks["XML sitemap declared"]["passed"]
    ai = checks["AI answer-engine crawler access"]
    assert not ai["passed"]
    assert "PerplexityBot" in ai["evidence"] and "GPTBot" in ai["evidence"]


def test_page_level_checks(monkeypatch):
    html = """<html lang="en"><head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <link rel="canonical" href="https://example.com/other">
      <script src="http://cdn.example.com/a.js"></script></head><body>
      <h1>Guide</h1><h2>What is it?</h2><h4>Skipped</h4>
      <h2>Why use it?</h2><p>It saves time and helps teams publish content that is easy to find.</p>
      <img src="a.png"><img src="b.png" alt="">
      <time datetime="2026-01-02">Jan 2</time><span class="byline">Jo</span>
      <ol><li>a</li><li>b</li><li>c</li></ol></body></html>"""
    checks = audit_checks(monkeypatch, html)
    assert checks["Language declared"]["passed"]
    assert checks["Mobile viewport"]["passed"]
    assert not checks["Canonical link"]["passed"]
    assert "different URL" in checks["Canonical link"]["evidence"]
    assert not checks["No mixed content"]["passed"]
    assert not checks["Heading structure"]["passed"]
    assert "H2→H4" in checks["Heading structure"]["evidence"]
    assert not checks["Image alt text"]["passed"]
    assert "1/2 images" in checks["Image alt text"]["evidence"]
    assert checks["Author attribution"]["passed"]
    assert checks["Published or updated date"]["passed"]
    assert checks["Lists and tables"]["passed"]
    assert "1/2 question headings" in checks["Answer-first sections"]["evidence"]
    assert not checks["Answer-first sections"]["passed"]


def test_schema_checks_flag_incomplete_markup(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "")

    async def page(url):
        return url, """
        <script type="application/ld+json">{"@type":"WebPage"}</script>
        <script type="application/ld+json">{"@context":"https://schema.org","@type":"FAQPage",
          "mainEntity":[{"@type":"Question","name":"Why?"}]}</script>
        """, ""

    monkeypatch.setattr(audit, "fetch_page", page)
    checks = {c["label"]: c for c in
              client.post("/api/audit", json={"url": "https://example.com/"}).json()
              ["sections"]["AEO"]["checks"]}
    assert not checks["Structured data syntax"]["passed"]
    assert "missing a schema.org @context" in checks["Structured data syntax"]["evidence"]
    assert checks["Answer-focused schema type"]["passed"]
    assert not checks["Schema required properties"]["passed"]
    assert "acceptedAnswer.text" in checks["Schema required properties"]["evidence"]


def test_grok_request_and_fallback(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.delenv("XAI_BASE_URL", raising=False)
    monkeypatch.delenv("XAI_MODEL", raising=False)

    class Stub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def post(self, url, *, headers, json):
            assert url == "https://api.x.ai/v1/responses"
            assert headers["Authorization"] == "Bearer test-key"
            assert json["store"] is False
            assert "tools" not in json
            return self

        def raise_for_status(self):
            pass

        async def json(self):
            return {"status": "completed", "output": [{"type": "message",
                    "content": [{"type": "output_text", "text": "Improve the title."}]}]}

    monkeypatch.setattr(audit.aiohttp, "ClientSession", lambda **kwargs: Stub())
    state = {"report": {"sections": {}, "ai_status": "disabled", "ai_notes": ""}}
    assert asyncio.run(audit.add_grok_notes(state))["report"]["ai_notes"] == "Improve the title."

    async def incomplete(self):
        return {"status": "incomplete", "output": []}

    monkeypatch.setattr(Stub, "json", incomplete)
    assert asyncio.run(audit.add_grok_notes(state))["report"]["ai_status"] == "unavailable"


def test_redirect_revalidates_destination(monkeypatch):
    from app import fetch

    class Stub:
        status = 302
        headers = {"Location": "http://192.168.0.1/"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def get(self, url, *, allow_redirects):
            assert str(url) == "https://example.com/"
            assert allow_redirects is False
            return self

    monkeypatch.setattr(fetch.aiohttp, "ClientSession", lambda **kwargs: Stub())
    monkeypatch.setattr(fetch.aiohttp, "TCPConnector", lambda **kwargs: None)
    with pytest.raises(FetchError):
        asyncio.run(fetch.fetch_page("https://example.com/"))
