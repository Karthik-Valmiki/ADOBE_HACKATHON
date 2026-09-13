#!/usr/bin/env python3
"""
crawl_access.py — Crawl Access Audit
Checks: robots.txt AI-agent disallow, multi-UA WAF detection,
redirect hop counting, llms.txt / llms-full.txt discovery.

Finding IDs produced:
  F-NET-001  robots.txt AI-agent disallow (Critical)
  F-NET-002  HTTP 403/429/503 or WAF silent block (Critical)
  F-NET-003  TTFB throttle ratio > 2.5x or delta > 500ms (High)
  F-NET-004  Redirect chain > 1 hop (High)
  F-NET-TLS  TLS certificate invalid or expired (High)
  F-LLMS-001 /llms.txt absent (Medium)
  F-LLMS-OK  /llms.txt found (proactive, Low)
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from .utils import (
    AI_USER_AGENTS, BROWSER_UA, DEFAULT_HEADERS, get_root_url,
    is_waf_challenge_body, make_client, truncate_evidence,
)

AI_AGENT_NAMES = list(AI_USER_AGENTS.keys())
AI_AGENT_STRINGS = list(AI_USER_AGENTS.values())


async def run_crawl_access_audit(
    url: str,
    root_url: str,
    *,
    prefetched_robots_content: str = "",
    prefetched_robots_status: int = 0,
) -> dict[str, Any]:
    """
    Run all crawl access checks. Returns findings list + metadata.

    prefetched_robots_content / prefetched_robots_status: If provided (from the
    orchestrator's single pre-fetch), the robots.txt is NOT re-fetched here.
    """
    findings: list[dict] = []

    # Run checks concurrently where independent
    results = await asyncio.gather(
        _check_robots_txt(
            root_url,
            prefetched_content=prefetched_robots_content,
            prefetched_status=prefetched_robots_status,
        ),
        _check_multi_ua_waf(url),
        _check_redirect_hops(url),
        _check_llms_txt(root_url),
        return_exceptions=True,
    )

    robots_result, waf_result, redirect_result, llms_result = results

    for label, result in [
        ("robots_txt", robots_result),
        ("multi_ua_waf", waf_result),
        ("redirect_hops", redirect_result),
        ("llms_txt", llms_result),
    ]:
        if isinstance(result, Exception):
            # Emit unverified finding rather than crashing
            findings.append({
                "id": f"F-ERR-CRAWL-{label.upper()}",
                "title": f"Crawl check could not complete: {label}",
                "severity": "medium",
                "type": "defect",
                "evidence": (
                    f"Check '{label}' raised {type(result).__name__}: {result}. "
                    "This check group produced no results. Other checks ran independently."
                ),
                "suggested_action": {
                    "summary": "Verify the target site is publicly reachable and retry the audit.",
                    "priority": "medium",
                    "effort": "low",
                    "implementation_hint": (
                        f"Isolate the failure: run 'curl -I {label}' from the audit host. "
                        "Confirm DNS resolves and the origin is not returning 5xx under load."
                    )
                },
                "check_ref": f"CHECK-{label.upper()}"
            })
        else:
            findings.extend(result.get("findings", []))

    return {"findings": findings}


# ── Check 1.1 — robots.txt AI Agent Disallow ─────────────────────────────────

async def _check_robots_txt(
    root_url: str,
    *,
    prefetched_content: str = "",
    prefetched_status: int = 0,
) -> dict:
    """
    F-NET-001: Parse robots.txt for AI-agent Disallow rules.
    Algorithm: fetch (or use prefetched) → line-by-line parse → per-agent block analysis.

    If prefetched_content/prefetched_status are provided by the orchestrator,
    the network fetch is skipped entirely to avoid duplicate requests.
    """
    findings: list[dict] = []
    robots_url = f"{root_url}/robots.txt"

    if prefetched_status > 0:
        # Use the content already fetched by the orchestrator
        if prefetched_status == 404:
            return {"findings": []}  # Absence = no restriction
        if prefetched_status != 200:
            return {"findings": []}
        content = prefetched_content
    else:
        # Fallback: fetch ourselves (e.g. when called standalone)
        try:
            async with make_client(timeout=5.0, follow_redirects=True) as client:
                resp = await client.get(robots_url, headers={"User-Agent": BROWSER_UA})
        except httpx.ConnectError as ssl_exc:
            if "SSL" in str(ssl_exc) or "certificate" in str(ssl_exc).lower():
                return {
                    "findings": [{
                        "id": "F-NET-TLS",
                        "title": "TLS certificate error prevents AI crawler access",
                        "severity": "high",
                        "type": "defect",
                        "evidence": (
                            f"TLS handshake to {robots_url} failed: {ssl_exc}. "
                            "AI crawlers with strict TLS enforcement (ClaudeBot, GPTBot) will refuse to connect."
                        ),
                        "suggested_action": {
                            "summary": "Renew or replace the TLS certificate and verify the full chain is installed.",
                            "priority": "high",
                            "effort": "low",
                            "implementation_hint": (
                                "Check certificate status: echo | openssl s_client -connect your-site.com:443 -servername your-site.com 2>/dev/null | openssl x509 -noout -dates. "
                                "Use Let's Encrypt (certbot) for free auto-renewing certificates."
                            )
                        },
                        "check_ref": "CHECK-1.0-TLS"
                    }]
                }
            return {"findings": []}  # Other connection errors
        except Exception:
            return {"findings": []}

        if resp.status_code == 404:
            return {"findings": []}
        if resp.status_code != 200:
            return {"findings": []}
        content = resp.text

    blocked_agents = _parse_robots_txt(content, root_url)

    if blocked_agents:
        agent_summary = "; ".join(
            f"{agent}: Disallow: {path}" for agent, path in blocked_agents.items()
        )
        count = len(blocked_agents)
        findings.append({
            "id": "F-NET-001",
            "title": "robots.txt explicitly blocks AI crawlers",
            "severity": "critical",
            "type": "defect",
            "evidence": (
                f"robots.txt disallows {count} of {len(AI_AGENT_NAMES)} tested AI crawlers. "
                f"{agent_summary}. "
                f"Compliant AI crawlers (GPTBot, ClaudeBot, PerplexityBot) abort at this gate "
                f"regardless of all other optimisations."
            ),
            "suggested_action": {
                "summary": (
                    f"Remove or modify Disallow rules for blocked AI agents: "
                    f"{', '.join(blocked_agents.keys())}. "
                    "If content must be protected, use more granular path restrictions rather than Disallow: /."
                ),
                "priority": "critical",
                "effort": "low",
                "implementation_hint": (
                    "Edit robots.txt. Replace 'Disallow: /' under AI agent blocks with "
                    "'Allow: /' or remove the agent blocks entirely. "
                    "Test at https://www.google.com/search/docs/crawling-indexing/robots/robots_txt"
                )
            },
            "check_ref": "CHECK-1.1"
        })

    return {"findings": findings, "blocked_agents": blocked_agents}


def _parse_robots_txt(content: str, root_url: str) -> dict[str, str]:
    """
    Parse robots.txt line by line. Return dict of {agent_name: disallow_path}
    for AI agents that are blocked at the target path.
    """
    lines = content.splitlines()
    current_agents: list[str] = []
    blocked: dict[str, str] = {}
    target_path = urlparse(root_url).path or "/"

    for raw_line in lines:
        line = raw_line.split("#")[0].strip()  # Strip inline comments
        if not line:
            current_agents = []
            continue

        if line.lower().startswith("user-agent:"):
            agent_val = line.split(":", 1)[1].strip()
            current_agents.append(agent_val)
            continue

        if line.lower().startswith("disallow:"):
            disallow_path = line.split(":", 1)[1].strip()
            for ua_name, ua_string in AI_USER_AGENTS.items():
                # Match if any current agent block matches this AI agent
                for current_agent in current_agents:
                    if (current_agent == "*" or
                            ua_name.lower() in current_agent.lower() or
                            current_agent.lower() in ua_name.lower()):
                        # Check if disallow path covers the target
                        if disallow_path in ("/", "") or target_path.startswith(disallow_path):
                            if ua_name not in blocked:
                                blocked[ua_name] = disallow_path

    return blocked


# ── Check 1.2 — Multi-Agent UA Emulation (TTFB Variance) ─────────────────────

async def _check_multi_ua_waf(url: str) -> dict:
    """
    F-NET-002: Absolute block (HTTP 403/429/503 or WAF challenge body).
    F-NET-003: Relative TTFB throttle (R_TTFB > 2.5x or delta > 500ms).
    Algorithm: 5 parallel requests with different UAs, compare status + TTFB.
    """
    findings: list[dict] = []

    # Build all UA request tasks with stagger to avoid simultaneous burst
    # that trips WAF bot-defence (Cloudflare, Akamai).
    # Stagger: 0ms, 200ms, 400ms, 600ms, 800ms, 1000ms
    async def fetch_with_ua(ua_name: str, ua_string: str, stagger_delay: float = 0.0) -> dict:
        if stagger_delay > 0:
            await asyncio.sleep(stagger_delay)
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=5.0),
                follow_redirects=True,
                verify=False,
                headers={**DEFAULT_HEADERS, "User-Agent": ua_string}
            ) as client:
                t_start = time.monotonic()
                resp = await client.get(url)
                ttfb_ms = (time.monotonic() - t_start) * 1000
                return {
                    "ua_name": ua_name,
                    "status": resp.status_code,
                    "ttfb_ms": ttfb_ms,
                    "body_sample": resp.text[:2000],
                    "error": None,
                }
        except Exception as exc:
            return {"ua_name": ua_name, "status": 0, "ttfb_ms": 9999, "body_sample": "", "error": str(exc)}

    # Browser baseline first (no stagger), then AI UAs with 200ms stagger each
    tasks = [fetch_with_ua("Browser", BROWSER_UA, stagger_delay=0.0)]
    for idx, (ua_name, ua_string) in enumerate(AI_USER_AGENTS.items()):
        tasks.append(fetch_with_ua(ua_name, ua_string, stagger_delay=(idx + 1) * 0.2))

    results = await asyncio.gather(*tasks)
    browser_result = results[0]
    ai_results = results[1:]

    ttfb_baseline = browser_result["ttfb_ms"]
    if ttfb_baseline <= 0:
        ttfb_baseline = 1.0

    absolute_blocked: list[str] = []
    waf_silent_blocked: list[str] = []
    throttled_agents: list[tuple[str, float, float]] = []  # (name, R_TTFB, delta_ms)

    for r in ai_results:
        ua_name = r["ua_name"]
        status = r["status"]
        ttfb = r["ttfb_ms"]
        body = r["body_sample"]

        # Absolute block check
        if status in (403, 429, 503):
            absolute_blocked.append(f"{ua_name} (HTTP {status})")

        # WAF silent block check (200 but challenge body)
        elif status == 200 and is_waf_challenge_body(body):
            waf_silent_blocked.append(f"{ua_name} (HTTP 200 + WAF challenge)")

        # TTFB throttle check
        else:
            r_ttfb = ttfb / ttfb_baseline
            delta = ttfb - ttfb_baseline
            if r_ttfb > 2.5 or delta > 500:
                throttled_agents.append((ua_name, r_ttfb, delta))

    # Emit F-NET-002 for absolute blocks
    if absolute_blocked or waf_silent_blocked:
        all_blocked = absolute_blocked + waf_silent_blocked
        findings.append({
            "id": "F-NET-002",
            "title": "Site actively blocks AI crawlers at WAF/edge layer",
            "severity": "critical",
            "type": "defect",
            "evidence": (
                f"Browser UA received HTTP {browser_result['status']}. "
                f"Blocked AI agents: {'; '.join(all_blocked)}. "
                "Site uses WAF rules to drop or challenge AI crawler requests. "
                "AI assistants (ChatGPT, Perplexity) cannot index this site."
            ),
            "suggested_action": {
                "summary": (
                    "Update WAF/CDN rules to allow known AI crawlers. "
                    "Whitelist: GPTBot, ClaudeBot, PerplexityBot, OAI-SearchBot, Google-Extended "
                    "by User-Agent string in Cloudflare/Akamai/Imperva rule sets."
                ),
                "priority": "critical",
                "effort": "medium",
                "implementation_hint": (
                    "In Cloudflare: Security > WAF > Custom Rules — add 'Allow' rule for "
                    "http.user_agent contains 'GPTBot' OR 'ClaudeBot' OR 'PerplexityBot'. "
                    "For Akamai/Imperva: consult vendor bot management documentation."
                )
            },
            "check_ref": "CHECK-1.2"
        })

    # Emit F-NET-003 for throttled agents
    if throttled_agents:
        throttle_summary = "; ".join(
            f"{name} R={r:.1f}x, Δ={delta:.0f}ms"
            for name, r, delta in throttled_agents
        )
        findings.append({
            "id": "F-NET-003",
            "title": "AI crawlers are being throttled (TTFB variance)",
            "severity": "high",
            "type": "defect",
            "evidence": (
                f"Browser baseline TTFB: {ttfb_baseline:.0f}ms. "
                f"Throttled AI agents: {throttle_summary}. "
                "Edge WAF is rate-shaping AI crawler requests. "
                "Slow TTFB causes AI crawlers with hard timeouts to abort."
            ),
            "suggested_action": {
                "summary": "Remove AI-UA-specific rate limiting at edge/WAF layer.",
                "priority": "high",
                "effort": "medium",
                "implementation_hint": (
                    "Review WAF rate-limit rules for bot UAs. "
                    "Apply separate, more permissive rate limits for known benign AI crawlers. "
                    "Monitor via WAF logs filtered by User-Agent."
                )
            },
            "check_ref": "CHECK-1.2"
        })

    return {"findings": findings}


# ── Check 1.3 — Redirect Hop Counter ─────────────────────────────────────────

async def _check_redirect_hops(url: str) -> dict:
    """
    F-NET-004: Redirect chain > 1 hop.
    Algorithm: manual hop-by-hop tracking with follow_redirects=False.
    """
    findings: list[dict] = []
    hop_count = 0
    hop_chain: list[str] = [url]
    current_url = url

    try:
        async with make_client(timeout=5.0, follow_redirects=False) as client:
            for _ in range(10):  # Max 10 hops safety ceiling
                try:
                    resp = await client.get(current_url)
                except Exception:
                    break

                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location", "")
                    if not location:
                        break
                    # Handle relative redirects
                    if location.startswith("/"):
                        parsed = urlparse(current_url)
                        location = f"{parsed.scheme}://{parsed.netloc}{location}"
                    hop_count += 1
                    current_url = location
                    hop_chain.append(current_url)
                else:
                    break

    except Exception as exc:
        return {"findings": []}  # Network error = skip check

    if hop_count > 1:
        chain_str = " → ".join(hop_chain)
        estimated_overhead_ms = hop_count * 150  # ~150ms per round-trip
        findings.append({
            "id": "F-NET-004",
            "title": f"Excessive redirect chain: {hop_count} hops",
            "severity": "high",
            "type": "defect",
            "evidence": (
                f"Redirect chain length: {hop_count} hops (threshold: 1). "
                f"Full chain: {chain_str}. "
                f"Estimated overhead: ~{estimated_overhead_ms}ms. "
                "AI crawlers with strict timeout budgets may abort before reaching content."
            ),
            "suggested_action": {
                "summary": (
                    f"Consolidate redirect chain from {hop_count} to ≤1 hop. "
                    "Configure server to redirect directly to canonical HTTPS URL."
                ),
                "priority": "high",
                "effort": "low",
                "implementation_hint": (
                    "Update nginx/Apache/CDN config to redirect http:// directly to https://www. "
                    "Avoid intermediate step-hops like http→https→www. "
                    "Test with: curl -I -L --max-redirs 10 <url>"
                )
            },
            "check_ref": "CHECK-1.3"
        })

    return {"findings": findings, "hop_count": hop_count, "hop_chain": hop_chain}


# ── Check 1.4 — llms.txt / llms-full.txt Discovery ───────────────────────────

async def _check_llms_txt(root_url: str) -> dict:
    """
    F-LLMS-001: Neither /llms.txt nor /llms-full.txt found (Medium).
    F-LLMS-OK:  Found and valid (proactive, Low).
    Validation: HTTP 200, text/* or markdown Content-Type, valid Markdown
    (no HTML scaffold, no JS), ≥1 heading, >200 bytes.
    """
    findings: list[dict] = []
    found_path: str | None = None
    found_details: dict = {}

    candidates = ["/llms.txt", "/llms-full.txt"]

    try:
        async with make_client(timeout=5.0, follow_redirects=True) as client:
            for path in candidates:
                target = f"{root_url}{path}"
                try:
                    resp = await client.get(target, headers={"User-Agent": BROWSER_UA})
                except Exception:
                    continue

                if resp.status_code != 200:
                    continue

                content_type = resp.headers.get("content-type", "").lower()
                body = resp.text
                body_bytes = len(resp.content)

                # Validate: text/* or markdown, no HTML scaffold, no JS, ≥1 heading, >200 bytes
                is_text = "text/" in content_type or "markdown" in content_type
                has_no_html_scaffold = not re.search(r"<!DOCTYPE|<html|<head|<body", body, re.IGNORECASE)
                has_no_js = "<script" not in body.lower()
                has_heading = bool(re.search(r"^#{1,6}\s+\S", body, re.MULTILINE))
                heading_count = len(re.findall(r"^#{1,6}\s+\S", body, re.MULTILINE))
                is_large_enough = body_bytes > 200

                if is_text and has_no_html_scaffold and has_no_js and has_heading and is_large_enough:
                    found_path = path
                    found_details = {
                        "path": path,
                        "size_bytes": body_bytes,
                        "heading_count": heading_count,
                        "content_type": content_type,
                    }
                    break

    except Exception:
        pass

    if found_path:
        findings.append({
            "id": "F-LLMS-OK",
            "title": f"AI-native fast-lane endpoint found: {found_path}",
            "severity": "low",
            "type": "proactive",
            "evidence": (
                f"Found {found_path} (HTTP 200, {found_details['size_bytes']} bytes, "
                f"valid Markdown, {found_details['heading_count']} headings, "
                f"Content-Type: {found_details['content_type']}). "
                "AI crawlers can fetch structured content in a single hop without HTML parsing."
            ),
            "suggested_action": {
                "summary": "Keep /llms.txt updated with current pricing, features, and contact info.",
                "priority": "low",
                "effort": "low",
                "implementation_hint": (
                    "Add a CI/CD step to regenerate /llms.txt when content changes. "
                    "Include: brand description, key pages, pricing, API docs, contact."
                )
            },
            "check_ref": "CHECK-1.4"
        })
    else:
        findings.append({
            "id": "F-LLMS-001",
            "title": "No AI-native fast-lane endpoint (/llms.txt) found",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"Neither /llms.txt nor /llms-full.txt returned HTTP 200 with valid Markdown content. "
                "AI crawlers must parse full HTML, execute JavaScript, and navigate navigation structure "
                "to extract facts. A /llms.txt provides clean structured content in one hop."
            ),
            "suggested_action": {
                "summary": "Create /llms.txt at the domain root with Markdown-formatted brand summary.",
                "priority": "medium",
                "effort": "low",
                "implementation_hint": (
                    "Create a file at /llms.txt with: # Brand Name\\n\\n"
                    "## About\\n[1-2 sentence description]\\n\\n"
                    "## Key Pages\\n- [URL]: [description]\\n\\n"
                    "## Pricing\\n[pricing info]\\n\\n"
                    "## Contact\\n[email/phone]. See llmstxt.org for spec."
                )
            },
            "check_ref": "CHECK-1.4"
        })

    return {"findings": findings}
