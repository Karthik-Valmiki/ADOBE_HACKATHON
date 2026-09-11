#!/usr/bin/env python3
"""
utils.py — Shared utilities for all audit checks.
Deterministic helpers: URL normalisation, HTTP client factory,
HTML/DOM parsing helpers, severity constants.
"""
from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

# ── Severity constants ───────────────────────────────────────────────────────
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

AI_USER_AGENTS = {
    "GPTBot": "GPTBot/1.1",
    "ClaudeBot": "ClaudeBot/1.0",
    "PerplexityBot": "PerplexityBot/1.0",
    "OAI-SearchBot": "OAI-SearchBot/1.0",
    "Google-Extended": "Google-Extended/1.0 (compatible; Googlebot/2.1)",
}

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def normalize_url(url: str) -> str:
    """Ensure URL has a scheme. Lowercase host."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    # Lowercase scheme and host; preserve path/query/fragment
    normalised = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
    )
    return urlunparse(normalised)


def validate_url(url: str) -> str:
    """Return root_url (scheme+host) or raise ValueError."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid scheme: {parsed.scheme!r}. Must be http or https.")
    if not parsed.netloc:
        raise ValueError(f"No hostname in URL: {url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def get_root_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def make_client(timeout: float = 10.0, follow_redirects: bool = True, verify: bool = True) -> httpx.AsyncClient:
    """
    Factory for the shared async HTTP client used across all audit checks.

    TLS certificate verification is enabled by default (verify=True).
    An invalid or expired certificate is itself an auditable signal — callers
    that need to probe behind a bad cert should explicitly pass verify=False
    and emit an F-NET-TLS finding with the certificate error as evidence.
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=5.0),
        follow_redirects=follow_redirects,
        headers={**DEFAULT_HEADERS, "User-Agent": BROWSER_UA},
        http2=False,
        verify=verify,
    )


def extract_year_mentions(text: str) -> list[int]:
    """Extract 4-digit years in range 2010-2030 from text."""
    raw = re.findall(r"\b(20[12][0-9])\b", text)
    return [int(y) for y in raw if 2010 <= int(y) <= 2030]


def strip_tags(html: str) -> str:
    """Very lightweight tag stripper for evidence snippets."""
    return re.sub(r"<[^>]+>", " ", html)


def word_count(text: str) -> int:
    """Count non-empty words in text."""
    return len(text.split())


def truncate_evidence(s: str, max_len: int = 400) -> str:
    """Truncate evidence string to max_len characters."""
    if len(s) <= max_len:
        return s
    return s[:max_len - 3] + "..."


def is_waf_challenge_body(html: str) -> bool:
    """
    Detect WAF challenge pages without pixel geometry.
    Uses DOM element ID / script src pattern AST scan (not substring match).
    """
    # Cloudflare patterns
    cf_patterns = [
        r'id=["\']challenge-form["\']',
        r'src=["\'][^"\']*turnstile[^"\']*["\']',
        r'class=["\'][^"\']*cf-browser-verification[^"\']*["\']',
        r'cf-mitigated',
        r'id=["\']cf-please-wait["\']',
    ]
    # Google reCAPTCHA
    recaptcha_patterns = [
        r'src=["\'][^"\']*g-recaptcha[^"\']*["\']',
        r'id=["\']g-recaptcha["\']',
        r'class=["\'][^"\']*g-recaptcha[^"\']*["\']',
    ]
    # Akamai
    akamai_patterns = [
        r'id=["\']akam-sc-blocked["\']',
        r'src=["\'][^"\']*_Incapsula[^"\']*["\']',
    ]
    # Imperva
    imperva_patterns = [
        r'class=["\'][^"\']*incapsula[^"\']*["\']',
        r'src=["\'][^"\']*visitorId[^"\']*["\']',
    ]
    # DataDome
    datadome_patterns = [
        r'src=["\'][^"\']*datadome[^"\']*["\']',
        r'id=["\']ddCaptcha["\']',
    ]

    all_patterns = (
        cf_patterns + recaptcha_patterns + akamai_patterns +
        imperva_patterns + datadome_patterns
    )
    for pat in all_patterns:
        if re.search(pat, html, re.IGNORECASE):
            return True
    return False


def find_json_ld_blocks(html: str) -> list[dict]:
    """Extract all JSON-LD script blocks from raw HTML."""
    import json
    results = []
    pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        raw = match.group(1).strip()
        try:
            data = json.loads(raw)
            results.append(data)
        except (json.JSONDecodeError, ValueError):
            pass
    return results


def extract_text_from_html(html: str) -> str:
    """Extract all visible text from HTML (no CSS layout engine)."""
    # Remove scripts, styles, comments
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    # Replace block-level tags with space
    text = re.sub(r"<(br|p|div|li|tr|td|th|h[1-6]|section|article|header|footer|main|nav)[^>]*>",
                  " ", text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_semantic_text(html: str) -> str:
    """
    Extract text only from semantic containers:
    <p>, <article>, <h1>-<h6>, <main>.
    Used for word-count in CSR hydration check.
    """
    # Find content within semantic tags
    pattern = re.compile(
        r"<(p|article|h[1-6]|main)[^>]*>(.*?)</\1>",
        re.DOTALL | re.IGNORECASE
    )
    parts = []
    for match in pattern.finditer(html):
        inner = match.group(2)
        # Strip tags within
        clean = re.sub(r"<[^>]+>", " ", inner)
        clean = re.sub(r"\s+", " ", clean).strip()
        if clean:
            parts.append(clean)
    return " ".join(parts)


def simple_tfidf_score(term: str, doc: str, corpus: list[str]) -> float:
    """Simplified TF-IDF for a single term against a doc."""
    import math
    doc_words = doc.lower().split()
    tf = doc_words.count(term.lower()) / max(len(doc_words), 1)
    df = sum(1 for d in corpus if term.lower() in d.lower())
    idf = math.log((len(corpus) + 1) / (df + 1)) + 1
    return tf * idf


def get_dom_depth(html: str, target_pattern: str) -> int:
    """
    Estimate DOM depth of the first element matching target_pattern.
    Counts opening tags above the match.
    Returns depth (number of ancestor elements).
    """
    # Find position of target element
    match = re.search(target_pattern, html, re.IGNORECASE)
    if not match:
        return 0
    prefix = html[:match.start()]
    # Count unclosed opening tags
    opens = len(re.findall(r"<[a-z][^/!>]*(?<!/)>", prefix, re.IGNORECASE))
    closes = len(re.findall(r"</[a-z][^>]*>", prefix, re.IGNORECASE))
    return max(0, opens - closes)


def compute_ttfb(start: float, response: httpx.Response) -> float:
    """Compute approximate TTFB from request start time."""
    # httpx doesn't expose TTFB directly; use elapsed as approximation
    elapsed = response.elapsed.total_seconds() if response.elapsed else 0.0
    return elapsed * 1000  # Return in ms


STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "can", "it", "its",
    "this", "that", "these", "those", "your", "our", "their", "we",
    "you", "he", "she", "they", "i", "my", "his", "her", "us"
}


def tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase words, stripping stop words."""
    words = re.findall(r"[a-z][a-z0-9]*", text.lower())
    return {w for w in words if w not in STOP_WORDS and len(w) > 2}
