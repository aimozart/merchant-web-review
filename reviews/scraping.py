"""
Gathers raw web-presence signals for a merchant's website — the "Web Presence
Review" data-collection step, before LLM synthesis. Deliberately dependency-light
(requests + BeautifulSoup only) since the goal is demonstrating the pattern
(fetch → extract → structure), not building a production-grade web crawler.
"""
from __future__ import annotations

import socket
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "MerchantWebReviewBot/0.1 (+https://example.com/bot)"
REQUEST_TIMEOUT_SECONDS = 10

SOCIAL_DOMAINS = [
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "tiktok.com",
    "youtube.com",
]

# A small, illustrative set — a real underwriting system's prohibited-category
# list is much larger and jurisdiction-specific. This is a demo-scale stand-in.
PROHIBITED_KEYWORDS = [
    "escort",
    "counterfeit",
    "replica watches",
    "unregulated pharmacy",
    "guaranteed returns",
    "get rich quick",
]

REPUTATION_KEYWORDS = ["scam", "fraud", "ripoff", "unauthorized charge", "never delivered"]


@dataclass
class WebPresenceSnapshot:
    url: str
    fetched_at: str
    status_code: int | None = None
    html: str = ""
    title: str = ""
    meta_description: str = ""
    resolved_ip: str | None = None
    social_links: list[str] = field(default_factory=list)
    prohibited_keyword_hits: list[str] = field(default_factory=list)
    reputation_keyword_hits: list[str] = field(default_factory=list)
    fetch_error: str | None = None


def gather_web_presence(url: str) -> WebPresenceSnapshot:
    """Fetch a merchant's site and extract raw signals for LLM synthesis."""
    snapshot = WebPresenceSnapshot(url=url, fetched_at=datetime.utcnow().isoformat())

    parsed = urlparse(url)
    try:
        snapshot.resolved_ip = socket.gethostbyname(parsed.hostname or "")
    except (socket.gaierror, TypeError):
        snapshot.resolved_ip = None

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        snapshot.status_code = resp.status_code
        snapshot.html = resp.text[:200_000]  # cap — this is a demo, not a full archiver
    except requests.RequestException as e:
        snapshot.fetch_error = str(e)
        return snapshot

    soup = BeautifulSoup(snapshot.html, "html.parser")

    if soup.title and soup.title.string:
        snapshot.title = soup.title.string.strip()

    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        snapshot.meta_description = meta["content"].strip()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(domain in href for domain in SOCIAL_DOMAINS):
            snapshot.social_links.append(href)

    page_text_lower = soup.get_text(" ", strip=True).lower()
    snapshot.prohibited_keyword_hits = [
        kw for kw in PROHIBITED_KEYWORDS if kw in page_text_lower
    ]
    snapshot.reputation_keyword_hits = [
        kw for kw in REPUTATION_KEYWORDS if kw in page_text_lower
    ]

    return snapshot
