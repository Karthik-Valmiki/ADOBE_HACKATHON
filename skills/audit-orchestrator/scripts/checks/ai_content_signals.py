#!/usr/bin/env python3
"""
ai_content_signals.py — Beyond-Spec AI Content Signals Audit
Checks: Canonical URL consistency, hreflang correctness, Sitemap presence/freshness,
Core Web Vitals resource hints, robots meta tag conflicts, meta description quality.

Finding IDs produced:
  F-SIGNAL-002  Missing/incorrect canonical URL (Medium)
  F-SIGNAL-003  hreflang errors (Medium)
  F-SIGNAL-004  No XML sitemap or sitemap unreachable (Medium)
  F-SIGNAL-005  Missing meta description or too short/long (Medium)
  F-SIGNAL-006  robots meta tag blocks AI indexing (High)
  F-SIGNAL-007  No preconnect/preload resource hints (Low)
"""
from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

from .utils import BROWSER_UA, get_root_url, make_client, truncate_evidence


async def run_ai_content_signals_audit(url: str, root_url: str) -> dict[str, Any]:
    """Run all bonus content signal checks concurrently."""
    findings: list[dict] = []

    # Fetch main page HTML
    html = ""
    try:
        async with make_client(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": BROWSER_UA})
            html = resp.text
            final_url = str(resp.url)
    except Exception as exc:
        return {"findings": []}

    # Run checks concurrently where independent
    results = await asyncio.gather(
        _check_canonical(url, html, root_url),
        _check_meta_description(html),
        _check_robots_meta(html),
        _check_hreflang(html),
        _check_sitemap(root_url),
        return_exceptions=True,
    )

    for result in results:
        if isinstance(result, Exception):
            continue  # Silently skip failed bonus checks
        if isinstance(result, dict):
            findings.extend(result.get("findings", []))

    # Inline checks (fast, no network)
    findings.extend(_check_resource_hints(html))

    return {"findings": findings}


async def _check_canonical(url: str, html: str, root_url: str) -> dict:
    """F-SIGNAL-002: Canonical URL missing, self-referential, or mismatched."""
    findings: list[dict] = []

    canonical_match = re.search(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
        html, re.IGNORECASE
    ) or re.search(
        r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']',
        html, re.IGNORECASE
    )

    parsed_url = urlparse(url)
    page_path = parsed_url.path.rstrip("/") or "/"

    if not canonical_match:
        findings.append({
            "id": "F-SIGNAL-002",
            "title": "Missing canonical URL tag",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"No <link rel='canonical'> found on {url}. "
                "Without canonical signals, AI crawlers and search engines may index "
                "duplicate URLs (with/without www, http/https, trailing slash variants), "
                "splitting crawl budget and diluting entity signal."
            ),
            "suggested_action": {
                "summary": "Add <link rel='canonical' href='[absolute URL]'> to every page <head>.",
                "priority": "medium",
                "effort": "low",
                "implementation_hint": (
                    f'<link rel="canonical" href="{url}"> '
                    "Use absolute URLs. For CMS: enable canonical tag plugin (Yoast, RankMath). "
                    "For Next.js: use <Head><link rel='canonical' href={router.asPath} /></Head>."
                )
            },
            "check_ref": "CHECK-CANONICAL"
        })
    else:
        canonical_href = canonical_match.group(1).strip()
        canonical_parsed = urlparse(canonical_href)
        canonical_path = canonical_parsed.path.rstrip("/") or "/"

        # Cross-domain canonical = suspicious
        if canonical_parsed.netloc and canonical_parsed.netloc != parsed_url.netloc:
            findings.append({
                "id": "F-SIGNAL-002",
                "title": "Cross-domain canonical URL detected",
                "severity": "medium",
                "type": "defect",
                "evidence": (
                    f"Canonical tag points to '{canonical_href}' — different domain from '{url}'. "
                    "Cross-domain canonicals instruct search engines to credit another site for this content. "
                    "This may cause AI systems to attribute content to the canonical domain instead."
                ),
                "suggested_action": {
                    "summary": "Verify cross-domain canonical is intentional. If not, update to self-referential canonical.",
                    "priority": "medium",
                    "effort": "low",
                    "implementation_hint": f'Update to: <link rel="canonical" href="{url}">'
                },
                "check_ref": "CHECK-CANONICAL"
            })

    return {"findings": findings}


async def _check_meta_description(html: str) -> dict:
    """F-SIGNAL-005: Missing or poorly-formed meta description."""
    findings: list[dict] = []

    meta_desc_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
        html, re.IGNORECASE
    ) or re.search(
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']',
        html, re.IGNORECASE
    )

    if not meta_desc_match:
        findings.append({
            "id": "F-SIGNAL-005",
            "title": "Missing meta description",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                "No <meta name='description'> found on page. "
                "AI assistants and search engines use meta descriptions as primary "
                "content summary signals. Missing description increases risk of "
                "auto-generated or inaccurate AI summaries."
            ),
            "suggested_action": {
                "summary": "Add a concise, keyword-rich meta description (150-160 characters) to every page.",
                "priority": "medium",
                "effort": "low",
                "implementation_hint": (
                    '<meta name="description" content="[150-160 char description including primary keyword]">. '
                    "Write unique descriptions per page. "
                    "Include: what the page is about, key benefit, call to action."
                )
            },
            "check_ref": "CHECK-META"
        })
    else:
        desc = meta_desc_match.group(1).strip()
        desc_len = len(desc)
        if desc_len < 50:
            findings.append({
                "id": "F-SIGNAL-005",
                "title": f"Meta description too short ({desc_len} chars, minimum 50)",
                "severity": "medium",
                "type": "defect",
                "evidence": (
                    f"Meta description: '{desc[:100]}' ({desc_len} characters). "
                    "Very short descriptions provide insufficient context for AI summarisation. "
                    "Minimum 50 characters recommended; 150-160 ideal."
                ),
                "suggested_action": {
                    "summary": "Expand meta description to 150-160 characters with primary keyword and value proposition.",
                    "priority": "medium",
                    "effort": "low",
                    "implementation_hint": "Include: [primary keyword] + [key benefit] + [call to action or differentiator]."
                },
                "check_ref": "CHECK-META"
            })
        elif desc_len > 300:
            findings.append({
                "id": "F-SIGNAL-005",
                "title": f"Meta description too long ({desc_len} chars, maximum 160)",
                "severity": "medium",
                "type": "defect",
                "evidence": (
                    f"Meta description: '{desc[:120]}...' ({desc_len} characters). "
                    "Descriptions > 160 chars are truncated by search engines and AI assistants. "
                    "Truncation may cut off the key value proposition."
                ),
                "suggested_action": {
                    "summary": "Trim meta description to 150-160 characters. Front-load key information.",
                    "priority": "medium",
                    "effort": "low",
                    "implementation_hint": "Put the most important information in the first 150 chars."
                },
                "check_ref": "CHECK-META"
            })

    return {"findings": findings}


async def _check_robots_meta(html: str) -> dict:
    """F-SIGNAL-006: robots meta tag blocking AI indexing."""
    findings: list[dict] = []

    robots_meta_match = re.search(
        r'<meta[^>]+name=["\']robots["\'][^>]+content=["\']([^"\']*)["\']',
        html, re.IGNORECASE
    ) or re.search(
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']robots["\']',
        html, re.IGNORECASE
    )

    if robots_meta_match:
        content = robots_meta_match.group(1).lower()
        blocking_directives = []
        if "noindex" in content:
            blocking_directives.append("noindex")
        if "nofollow" in content:
            blocking_directives.append("nofollow")
        if "none" in content:
            blocking_directives.append("none")

        if blocking_directives:
            findings.append({
                "id": "F-SIGNAL-006",
                "title": f"robots meta tag blocks AI indexing: {', '.join(blocking_directives)}",
                "severity": "high",
                "type": "defect",
                "evidence": (
                    f"<meta name='robots' content='{robots_meta_match.group(1)}'> found. "
                    f"Directives: {', '.join(blocking_directives)}. "
                    "noindex prevents search engines and AI crawlers from indexing this page. "
                    "nofollow prevents link equity and crawl graph traversal. "
                    "Page will not appear in AI assistant knowledge bases."
                ),
                "suggested_action": {
                    "summary": (
                        "Remove blocking directives unless intentionally excluding this page. "
                        "Replace with <meta name='robots' content='index,follow'>."
                    ),
                    "priority": "high",
                    "effort": "low",
                    "implementation_hint": (
                        'Replace with: <meta name="robots" content="index, follow">. '
                        "If using CMS: check SEO plugin settings for accidental noindex flags. "
                        "In WordPress/Yoast: verify 'Search engine visibility' is NOT checked."
                    )
                },
                "check_ref": "CHECK-ROBOTS-META"
            })

    # Check for AI-specific meta tags (GPTBot, etc.)
    for ai_agent in ["gptbot", "claudebot", "perplexitybot", "google-extended"]:
        ai_meta = re.search(
            rf'<meta[^>]+name=["\'](?:{ai_agent})["\'][^>]+content=["\']([^"\']*)["\']',
            html, re.IGNORECASE
        )
        if ai_meta and "noindex" in ai_meta.group(1).lower():
            findings.append({
                "id": "F-SIGNAL-006",
                "title": f"AI-specific meta tag blocks {ai_agent}: noindex",
                "severity": "high",
                "type": "defect",
                "evidence": (
                    f"<meta name='{ai_agent}' content='{ai_meta.group(1)}'> found. "
                    f"Explicitly instructs {ai_agent} not to index this page."
                ),
                "suggested_action": {
                    "summary": f"Remove noindex directive from {ai_agent} meta tag unless intentional.",
                    "priority": "high",
                    "effort": "low",
                    "implementation_hint": f'Remove: <meta name="{ai_agent}" content="noindex"> from page <head>.'
                },
                "check_ref": "CHECK-ROBOTS-META"
            })

    return {"findings": findings}


async def _check_hreflang(html: str) -> dict:
    """F-SIGNAL-003: hreflang tag errors (self-reference, x-default missing)."""
    findings: list[dict] = []

    hreflang_tags = re.findall(
        r'<link[^>]+hreflang=["\']([^"\']*)["\'][^>]+href=["\']([^"\']*)["\']',
        html, re.IGNORECASE
    )
    if not hreflang_tags:
        # Also try reversed attribute order
        hreflang_tags = re.findall(
            r'<link[^>]+href=["\']([^"\']*)["\'][^>]+hreflang=["\']([^"\']*)["\']',
            html, re.IGNORECASE
        )
        if hreflang_tags:
            # Swap to (lang, url) order
            hreflang_tags = [(b, a) for a, b in hreflang_tags]

    if len(hreflang_tags) > 1:  # Only validate if multiple languages declared
        langs = [tag[0] for tag in hreflang_tags]
        has_x_default = "x-default" in langs

        issues = []
        if not has_x_default:
            issues.append("missing x-default hreflang (required for language-selector fallback)")

        # Check for duplicate language codes
        seen_langs = set()
        for lang, _ in hreflang_tags:
            if lang in seen_langs:
                issues.append(f"duplicate hreflang '{lang}'")
            seen_langs.add(lang)

        if issues:
            findings.append({
                "id": "F-SIGNAL-003",
                "title": f"hreflang implementation errors: {'; '.join(issues)}",
                "severity": "medium",
                "type": "defect",
                "evidence": (
                    f"Found {len(hreflang_tags)} hreflang tag(s). "
                    f"Languages: {', '.join(langs[:10])}. "
                    f"Issues: {'; '.join(issues)}. "
                    "hreflang errors cause AI assistants to serve wrong-language content "
                    "and split ranking signals across language variants."
                ),
                "suggested_action": {
                    "summary": "Fix hreflang implementation: add x-default, remove duplicates, ensure bidirectional references.",
                    "priority": "medium",
                    "effort": "medium",
                    "implementation_hint": (
                        'Add: <link rel="alternate" hreflang="x-default" href="[default URL]">. '
                        "Ensure every language variant includes hreflang tags pointing to ALL other variants. "
                        "Validate at: https://technicalseo.com/tools/hreflang/"
                    )
                },
                "check_ref": "CHECK-HREFLANG"
            })

    return {"findings": findings}


async def _check_sitemap(root_url: str) -> dict:
    """F-SIGNAL-004: XML sitemap missing, unreachable, or stale."""
    findings: list[dict] = []

    sitemap_candidates = [
        f"{root_url}/sitemap.xml",
        f"{root_url}/sitemap_index.xml",
        f"{root_url}/sitemap-index.xml",
        f"{root_url}/sitemaps/sitemap.xml",
    ]

    sitemap_url: str | None = None
    sitemap_content: str = ""
    lastmod_dates: list[str] = []

    try:
        async with make_client(timeout=8.0, follow_redirects=True) as client:
            for candidate in sitemap_candidates:
                try:
                    resp = await client.get(candidate)
                    if resp.status_code == 200 and ("xml" in resp.headers.get("content-type", "") or
                                                     resp.text.strip().startswith("<?xml")):
                        sitemap_url = candidate
                        sitemap_content = resp.text
                        break
                except Exception:
                    continue
    except Exception:
        return {"findings": []}

    if not sitemap_url:
        # Check robots.txt for Sitemap: directive
        try:
            async with make_client(timeout=5.0) as client:
                robots_resp = await client.get(f"{root_url}/robots.txt")
                if robots_resp.status_code == 200:
                    sitemap_directive = re.search(
                        r"^Sitemap:\s*(.+)$", robots_resp.text, re.MULTILINE | re.IGNORECASE
                    )
                    if sitemap_directive:
                        sitemap_from_robots = sitemap_directive.group(1).strip()
                        resp2 = await client.get(sitemap_from_robots)
                        if resp2.status_code == 200:
                            sitemap_url = sitemap_from_robots
                            sitemap_content = resp2.text
        except Exception:
            pass

    if not sitemap_url:
        findings.append({
            "id": "F-SIGNAL-004",
            "title": "No XML sitemap found",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"Checked: {', '.join(sitemap_candidates)}. None returned valid XML sitemap. "
                "No Sitemap: directive in robots.txt. "
                "AI crawlers use sitemaps to discover and prioritise content pages. "
                "Without a sitemap, deep pages may never be discovered or indexed."
            ),
            "suggested_action": {
                "summary": "Create and submit an XML sitemap at /sitemap.xml.",
                "priority": "medium",
                "effort": "medium",
                "implementation_hint": (
                    "Generate sitemap with your CMS plugin (Yoast, RankMath, Next.js sitemap). "
                    "Add: 'Sitemap: https://yourdomain.com/sitemap.xml' to robots.txt. "
                    "Submit to Google Search Console and Bing Webmaster Tools."
                )
            },
            "check_ref": "CHECK-SITEMAP"
        })
    else:
        # Parse sitemap for freshness
        try:
            root_el = ET.fromstring(sitemap_content)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            lastmod_els = root_el.findall(".//sm:lastmod", ns)
            lastmod_dates = [el.text.strip() for el in lastmod_els if el.text]
        except Exception:
            pass

        if lastmod_dates:
            # Check for stale lastmod dates
            current_year = datetime.now(timezone.utc).year
            oldest_date = min(lastmod_dates)
            oldest_year_match = re.search(r"(20\d{2})", oldest_date)
            if oldest_year_match:
                oldest_year = int(oldest_year_match.group(1))
                if current_year - oldest_year >= 2:
                    findings.append({
                        "id": "F-SIGNAL-004",
                        "title": f"Sitemap contains stale entries (oldest lastmod: {oldest_date})",
                        "severity": "medium",
                        "type": "defect",
                        "evidence": (
                            f"Sitemap found at {sitemap_url} with {len(lastmod_dates)} lastmod entries. "
                            f"Oldest lastmod: {oldest_date} ({current_year - oldest_year} years ago). "
                            "Stale lastmod dates reduce crawl priority for those URLs. "
                            "AI crawlers may deprioritise or skip old-lastmod content."
                        ),
                        "suggested_action": {
                            "summary": "Update sitemap lastmod dates to reflect actual content modification dates.",
                            "priority": "medium",
                            "effort": "low",
                            "implementation_hint": (
                                "Configure CMS to auto-update lastmod on content change. "
                                "For static sites: use build timestamp as lastmod. "
                                "For Next.js: use getStaticProps revalidation date."
                            )
                        },
                        "check_ref": "CHECK-SITEMAP"
                    })

    return {"findings": findings}


def _check_resource_hints(html: str) -> list[dict]:
    """F-SIGNAL-007: Missing preconnect/preload hints (Core Web Vitals proxy)."""
    findings: list[dict] = []

    has_preconnect = bool(re.search(r'<link[^>]+rel=["\']preconnect["\']', html, re.IGNORECASE))
    has_preload = bool(re.search(r'<link[^>]+rel=["\']preload["\']', html, re.IGNORECASE))
    has_dns_prefetch = bool(re.search(r'<link[^>]+rel=["\']dns-prefetch["\']', html, re.IGNORECASE))

    # Detect third-party resources (fonts, analytics, CDN)
    has_google_fonts = "fonts.googleapis.com" in html
    has_analytics = any(d in html for d in ["google-analytics.com", "segment.io", "mixpanel.com"])
    has_cdn = any(d in html for d in ["cdn.jsdelivr.net", "cdnjs.cloudflare.com", "unpkg.com"])

    needs_hints = has_google_fonts or has_analytics or has_cdn

    if needs_hints and not (has_preconnect or has_dns_prefetch):
        third_party = []
        if has_google_fonts:
            third_party.append("Google Fonts (fonts.googleapis.com)")
        if has_analytics:
            third_party.append("Analytics (GA/Segment/Mixpanel)")
        if has_cdn:
            third_party.append("Third-party CDN")

        findings.append({
            "id": "F-SIGNAL-007",
            "title": "Missing resource hints for third-party origins",
            "severity": "low",
            "type": "defect",
            "evidence": (
                f"Third-party origins detected: {', '.join(third_party)}. "
                "No <link rel='preconnect'> or <link rel='dns-prefetch'> found. "
                "Missing resource hints increase Time-To-First-Byte for critical resources, "
                "degrading Core Web Vitals (LCP/FID) which AI crawlers use as quality signals."
            ),
            "suggested_action": {
                "summary": "Add preconnect hints for all third-party origins used above the fold.",
                "priority": "low",
                "effort": "low",
                "implementation_hint": (
                    "Add to <head>:\n"
                    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
                    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
                    '<link rel="dns-prefetch" href="https://www.google-analytics.com">'
                )
            },
            "check_ref": "CHECK-RESOURCE-HINTS"
        })

    return findings
