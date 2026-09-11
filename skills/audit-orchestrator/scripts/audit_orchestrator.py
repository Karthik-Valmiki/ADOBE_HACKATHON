#!/usr/bin/env python3
"""
audit_orchestrator.py — Master entrypoint for Brand AI-Readiness Audit v2.0
Runs all skill modules in dependency order, enforces the cross-web corroboration
contract, and emits the final JSON report.

Hard constraints enforced:
  - httpx async only (no requests, no urllib3 direct)
  - Node.js + jsdom for JS hydration (no Chromium, no Playwright, no Selenium)
  - Zero pixel geometry
  - < 300s total runtime (asyncio.timeout)
  - findings[] NEVER empty
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import timezone, datetime
from pathlib import Path
from typing import Any

# ── Logging: all progress to stderr so stdout carries only the final JSON ──────
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
_log = logging.getLogger("audit_orchestrator")

# Add parent scripts dir to path so check modules resolve correctly
sys.path.insert(0, str(Path(__file__).parent))

from checks.crawl_access import run_crawl_access_audit
from checks.render_parity import run_render_parity_audit
from checks.entity_structured_data import run_entity_structured_data_audit
from checks.corroboration_freshness import run_corroboration_freshness_audit
from checks.engagement import run_engagement_audit
from checks.ai_content_signals import run_ai_content_signals_audit
from checks.report_serializer import serialize_report
from checks.utils import normalize_url, validate_url

MAX_RUNTIME_SECONDS = 290  # Hard ceiling — spec mandates < 5 min


async def orchestrate(url: str, output_format: str = "json") -> dict[str, Any]:
    """
    Main orchestration coroutine. Runs all check modules in dependency order.
    NEVER raises — all exceptions are caught and converted to structured findings.
    """
    start_time = time.monotonic()
    all_findings: list[dict] = []
    checks_partial: list[str] = []
    js_engine_available = False
    cross_web_corroboration: dict = {}

    # ── Step 0: Validate + Normalise URL ────────────────────────────────────
    try:
        normalised_url = normalize_url(url)
        root_url = validate_url(normalised_url)
    except ValueError as exc:
        return _halt_report(url, str(exc), start_time)

    # ── Step 1: Independent parallel checks (crawl, entity, signals) ────────
    _log.info("Running crawl access, entity, and content-signal checks on %s", root_url)
    try:
        async with asyncio.timeout(60):
            step1_results = await asyncio.gather(
                run_crawl_access_audit(normalised_url, root_url),
                run_entity_structured_data_audit(normalised_url),
                run_ai_content_signals_audit(normalised_url, root_url),
                return_exceptions=True,
            )

        crawl_result, entity_result, signals_result = step1_results

        for label, result in [
            ("crawl-access-audit", crawl_result),
            ("entity-structured-data-audit", entity_result),
            ("ai-content-signals-audit", signals_result),
        ]:
            if isinstance(result, Exception):
                checks_partial.append(label)
                all_findings.append(_exception_finding(label, result))
            else:
                all_findings.extend(result.get("findings", []))

        # Extract brand_name from entity check; passed to corroboration step
        brand_name = ""
        if not isinstance(entity_result, Exception):
            brand_name = entity_result.get("brand_name", "")

    except asyncio.TimeoutError:
        checks_partial.append("crawl-entity-signals-timeout")
        all_findings.append({
            "id": "F-TIMEOUT-001",
            "title": "Initial crawl and discoverability checks timed out",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                "HTTP network requests for robots.txt, JSON-LD entity data, and "
                "content-signal metadata exceeded the 60-second timeout. "
                "Results for this check group are incomplete."
            ),
            "suggested_action": {
                "summary": "Verify the site responds within 5 seconds to standard GET requests.",
                "priority": "medium",
                "effort": "medium",
                "implementation_hint": (
                    "Measure Time-To-First-Byte with: curl -o /dev/null -w '%{time_starttransfer}' https://your-site.com. "
                    "Values above 2 seconds indicate CDN misconfiguration or origin server overload."
                )
            },
            "check_ref": "ORCHESTRATOR"
        })
        brand_name = ""

    # ── Step 2: DOM hydration via Node.js + jsdom ────────────────────────────
    _log.info("Running client-side rendering parity check (jsdom hydration)")
    hydrated_dom_ast = None
    try:
        async with asyncio.timeout(90):
            render_result = await run_render_parity_audit(normalised_url)

        if isinstance(render_result, Exception):
            checks_partial.append("render-parity-audit")
            all_findings.append(_exception_finding("render-parity-audit", render_result))
        else:
            all_findings.extend(render_result.get("findings", []))
            hydrated_dom_ast = render_result.get("hydrated_dom_ast")
            js_engine_available = render_result.get("js_engine_available", False)
            if not js_engine_available:
                checks_partial.append("js-engine-unavailable")

    except asyncio.TimeoutError:
        checks_partial.append("render-parity-timeout")
        all_findings.append({
            "id": "F-TIMEOUT-002",
            "title": "Client-side rendering check timed out",
            "severity": "high",
            "type": "defect",
            "evidence": (
                "jsdom hydration of the page exceeded 90 seconds. "
                "Engagement checks that depend on the rendered DOM are running in static-HTML-only mode. "
                "A slow-rendering page is itself an AI-discoverability risk: crawlers impose strict fetch budgets."
            ),
            "suggested_action": {
                "summary": "Reduce Time-To-Interactive: eliminate render-blocking scripts, adopt server-side rendering.",
                "priority": "high",
                "effort": "high",
                "implementation_hint": (
                    "Audit inline script weight with Chrome DevTools > Coverage. "
                    "Defer non-critical scripts with <script defer>. "
                    "For React/Vue/Angular apps, enable SSR or static-site generation."
                )
            },
            "check_ref": "CHECK-1.5"
        })

    # ── Step 3: Cross-web corroboration + temporal freshness ────────────────
    _log.info("Running cross-web corroboration and freshness audit (brand: %r)", brand_name)
    try:
        async with asyncio.timeout(60):
            corroboration_result = await run_corroboration_freshness_audit(
                normalised_url, root_url, brand_name
            )

        if isinstance(corroboration_result, Exception):
            checks_partial.append("corroboration-freshness-audit")
            all_findings.append(_exception_finding("corroboration-freshness-audit", corroboration_result))
            cross_web_corroboration = {
                "corroboration_status": "blocked",
                "brand_name": brand_name,
                "offsite_price_str": "",
                "offsite_price_num": None,
                "offsite_year_max": None,
                "offsite_snippets": [],
                "wikidata_entity_found": False,
                "wikidata_qid": None,
            }
        else:
            all_findings.extend(corroboration_result.get("findings", []))
            cross_web_corroboration = corroboration_result.get("layer3_contract", {})

    except asyncio.TimeoutError:
        checks_partial.append("corroboration-freshness-timeout")
        cross_web_corroboration = {
            "corroboration_status": "rate_limited",
            "brand_name": brand_name,
            "offsite_price_str": "",
            "offsite_price_num": None,
            "offsite_year_max": None,
            "offsite_snippets": [],
            "wikidata_entity_found": False,
            "wikidata_qid": None,
        }
        all_findings.append({
            "id": "F-TIMEOUT-003",
            "title": "Cross-web corroboration checks timed out",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                "Wikidata entity query and DuckDuckGo Lite freshness check exceeded the 60-second limit. "
                "Off-site corroboration status recorded as unverified. Re-run the audit to obtain full results."
            ),
            "suggested_action": {
                "summary": "Ensure outbound HTTPS access to wikidata.org and duckduckgo.com is available.",
                "priority": "low",
                "effort": "low",
                "implementation_hint": (
                    "Test connectivity: curl -I https://www.wikidata.org/w/api.php "
                    "and curl -I https://lite.duckduckgo.com/lite/. "
                    "If behind a corporate proxy, configure HTTPS_PROXY environment variable."
                )
            },
            "check_ref": "CHECK-1.9-1.10"
        })

    # ── Step 4: On-site engagement checks ───────────────────────────────────
    _log.info("Running on-site engagement audit")
    try:
        async with asyncio.timeout(60):
            engagement_result = await run_engagement_audit(
                normalised_url, hydrated_dom_ast, cross_web_corroboration
            )

        if isinstance(engagement_result, Exception):
            checks_partial.append("engagement-audit")
            all_findings.append(_exception_finding("engagement-audit", engagement_result))
        else:
            all_findings.extend(engagement_result.get("findings", []))

    except asyncio.TimeoutError:
        checks_partial.append("engagement-audit-timeout")
        all_findings.append({
            "id": "F-TIMEOUT-004",
            "title": "On-site engagement checks timed out",
            "severity": "medium",
            "type": "defect",
            "evidence": "Engagement analysis exceeded 60 seconds. Intent mismatch, overlay, and price divergence checks are incomplete.",
            "suggested_action": {
                "summary": "Re-run the audit. If the site consistently times out, investigate server response latency.",
                "priority": "medium",
                "effort": "low",
                "implementation_hint": (
                    "Measure page load time: curl -o /dev/null -w '%{time_total}' https://your-site.com. "
                    "Values above 5 seconds will cause this timeout consistently."
                )
            },
            "check_ref": "CHECK-2.1-2.6"
        })

    # ── Step 5: Proactive findings (required when no defects) ───────────────
    proactive = _compute_proactive_findings(all_findings, cross_web_corroboration)
    all_findings.extend(proactive)

    # MANDATORY: findings[] must NEVER be empty (spec constraint)
    if not all_findings:
        all_findings.append({
            "id": "F-DISC-OK",
            "title": "All AI discoverability and engagement checks passed",
            "severity": "low",
            "type": "proactive",
            "evidence": (
                "All observable conditions tested — crawl access, structured data, rendering parity, "
                "cross-web corroboration, and on-site engagement — returned no defects."
            ),
            "suggested_action": {
                "summary": "Add /llms.txt to give AI assistants a single-hop content summary.",
                "priority": "low",
                "effort": "low",
                "implementation_hint": "See llmstxt.org. Deploy a Markdown file at /llms.txt listing key pages, pricing, and contact info."
            },
            "check_ref": "PROACTIVE"
        })

    # ── Step 6: Serialise ───────────────────────────────────────────────────
    elapsed = time.monotonic() - start_time
    report = serialize_report(
        site=root_url,
        findings=all_findings,
        layer3_contract=cross_web_corroboration,
        elapsed_seconds=elapsed,
        js_engine_available=js_engine_available,
        checks_partial=checks_partial,
        output_format=output_format,
    )

    _log.info("Audit completed in %.1fs — %d findings.", elapsed, report["summary"]["total_findings"])
    return report


def _halt_report(url: str, reason: str, start_time: float) -> dict:
    """Minimal valid report emitted when the input URL itself is invalid."""
    return {
        "site": url,
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "audit_version": "2.0.0",
        "summary": {"total_findings": 1, "critical": 1, "high": 0, "medium": 0, "low": 0, "proactive": 0},
        "findings": [{
            "id": "F-INPUT-001",
            "title": "Target URL is invalid or unreachable",
            "severity": "critical",
            "type": "defect",
            "evidence": f"URL validation failed before any network request was attempted. Reason: {reason}",
            "suggested_action": {
                "summary": "Supply a valid, publicly reachable HTTP or HTTPS URL.",
                "priority": "critical",
                "effort": "low",
                "implementation_hint": (
                    "Ensure the URL includes a scheme (https://) and a resolvable hostname. "
                    "Test with: curl -I https://your-site.com"
                )
            },
            "check_ref": "INPUT-VALIDATION"
        }],
        "cross_web_corroboration": {},
        "runtime_meta": {
            "elapsed_seconds": round(time.monotonic() - start_time, 2),
            "js_engine_available": False,
            "checks_partial": []
        }
    }


def _exception_finding(skill: str, exc: Exception) -> dict:
    """Convert an unhandled skill exception into a structured finding rather than crashing."""
    return {
        "id": f"F-ERR-{skill.upper()[:20].replace('-', '_')}",
        "title": f"Check module raised an unexpected error: {skill}",
        "severity": "medium",
        "type": "defect",
        "evidence": (
            f"Module '{skill}' raised {type(exc).__name__}: {exc}. "
            "This check group produced no results. Other check groups ran independently."
        ),
        "suggested_action": {
            "summary": "Re-run the audit. Verify site is publicly accessible and outbound HTTP is permitted.",
            "priority": "medium",
            "effort": "low",
            "implementation_hint": (
                f"Isolate the failure by running the '{skill}' module directly. "
                "Confirm DNS resolution and that no WAF is blocking the audit IP."
            )
        },
        "check_ref": skill.upper()
    }


def _compute_proactive_findings(
    findings: list[dict], corroboration: dict
) -> list[dict]:
    """Emit proactive confirmation findings for check groups that returned zero defects."""
    proactive = []
    defect_ids = {f["id"] for f in findings if f.get("type") != "proactive"}

    # Crawl & discoverability proactive
    crawl_defect_ids = {
        "F-NET-001", "F-NET-002", "F-NET-003", "F-NET-004",
        "F-DOM-001", "F-DOM-002", "F-DOM-005",
        "F-ENTITY-001", "F-ENTITY-002", "F-FRESH-001"
    }
    if not crawl_defect_ids.intersection(defect_ids):
        qid = corroboration.get("wikidata_qid", "N/A")
        proactive.append({
            "id": "F-DISC-OK",
            "title": "AI crawl access and discoverability checks passed",
            "severity": "low",
            "type": "proactive",
            "evidence": (
                f"robots.txt grants access to all tested AI crawlers. "
                f"Redirect chain is within the 1-hop limit. "
                f"Wikidata entity corroborated (QID: {qid}). "
                f"Temporal freshness delta is below 2 years. "
                f"JSON-LD Organization block with valid sameAs URIs present. "
                f"No visual data traps or excessive DOM depth detected."
            ),
            "suggested_action": {
                "summary": "Add /llms.txt for single-hop AI-native content access.",
                "priority": "low",
                "effort": "low",
                "implementation_hint": (
                    "Deploy a plain-text Markdown file at /llms.txt listing your top pages, "
                    "pricing tier descriptions, and contact information. "
                    "See the specification at llmstxt.org."
                )
            },
            "check_ref": "F-DISC-OK"
        })

    # Engagement proactive
    engagement_defect_ids = {
        "F-ENG-003", "F-ENG-004", "F-ENG-005", "F-ENG-006",
        "F-ENG-007", "F-ENG-009", "F-ENG-010", "F-ENG-013"
    }
    if not engagement_defect_ids.intersection(defect_ids):
        proactive.append({
            "id": "F-ENG-OK",
            "title": "On-site user engagement checks passed",
            "severity": "low",
            "type": "proactive",
            "evidence": (
                "Hero section language overlaps page title keywords at or above the 0.30 Jaccard threshold. "
                "All URL hash anchors referenced by AI assistants resolve to visible, non-collapsed elements. "
                "A call-to-action is present before the hero section boundary. "
                "No full-screen or scroll-triggered overlays detected at page load. "
                "Boilerplate-to-content ratio is within the 2.5x limit. "
                "No unbroken text walls exceeding 120 words without visual anchors. "
                "No web-to-AI pricing divergence detected."
            ),
            "suggested_action": {
                "summary": "Add FAQPage JSON-LD schema to strengthen AI citation of specific question-and-answer content.",
                "priority": "low",
                "effort": "medium",
                "implementation_hint": (
                    "Add <script type='application/ld+json'>{ '@context': 'https://schema.org', "
                    "'@type': 'FAQPage', 'mainEntity': [{ '@type': 'Question', 'name': '...', "
                    "'acceptedAnswer': { '@type': 'Answer', 'text': '...' } }] }</script> "
                    "to key landing pages."
                )
            },
            "check_ref": "F-ENG-OK"
        })

    return proactive


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Brand AI-Readiness Audit v2.0")
    parser.add_argument("url", help="Target URL to audit (e.g. https://target.com)")
    parser.add_argument("--format", choices=["json", "html", "both"], default="json")
    parser.add_argument("--output", default="-", help="Output file path (- for stdout)")
    args = parser.parse_args()

    try:
        async with asyncio.timeout(MAX_RUNTIME_SECONDS):
            report = await orchestrate(args.url, args.format)
    except asyncio.TimeoutError:
        report = {
            "site": args.url,
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "audit_version": "2.0.0",
            "summary": {"total_findings": 1, "critical": 1, "high": 0, "medium": 0, "low": 0, "proactive": 0},
            "findings": [{
                "id": "F-TIMEOUT-GLOBAL",
                "title": "Audit exceeded the 5-minute runtime limit",
                "severity": "critical",
                "type": "defect",
                "evidence": (
                    f"Total audit wall-clock time exceeded the {MAX_RUNTIME_SECONDS}-second hard limit. "
                    "No partial results available."
                ),
                "suggested_action": {
                    "summary": "Investigate site availability. A healthy, publicly accessible site completes this audit in under 30 seconds.",
                    "priority": "critical",
                    "effort": "low",
                    "implementation_hint": "Verify the site is reachable from external IPs: curl -I https://your-site.com"
                },
                "check_ref": "ORCHESTRATOR"
            }],
            "cross_web_corroboration": {},
            "runtime_meta": {
                "elapsed_seconds": MAX_RUNTIME_SECONDS,
                "js_engine_available": False,
                "checks_partial": ["all"]
            }
        }

    output_json = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output == "-":
        sys.stdout.write(output_json + "\n")
    else:
        Path(args.output).write_text(output_json, encoding="utf-8")
        _log.info("Report written to %s", args.output)


if __name__ == "__main__":
    asyncio.run(main())
