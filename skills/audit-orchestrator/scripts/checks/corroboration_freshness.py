#!/usr/bin/env python3
"""
corroboration_freshness.py — Cross-Web Corroboration + Temporal Freshness Audit
Checks: Wikidata entity corroboration, DuckDuckGo Lite freshness delta.

Finding IDs produced:
  F-ENTITY-002         Entity not in Wikidata (Medium)
  F-ENTITY-003         Entity corroborated in Wikidata (proactive, Low)
  F-ENTITY-UNVERIFIED  Wikidata check failed/rate-limited (Medium)
  F-FRESH-001          Temporal freshness delta >= 2 years (High)
  F-FRESH-UNVERIFIED   DuckDuckGo check failed/blocked (Medium)

Emits Cross-Web Output Contract:
  {
    brand_name, offsite_price_str, offsite_price_num, offsite_year_max,
    offsite_snippets[], wikidata_entity_found, wikidata_qid,
    corroboration_status: "ok|rate_limited|blocked"
  }
"""
from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote

import httpx

from .utils import (
    BROWSER_UA, DEFAULT_HEADERS, extract_year_mentions,
    is_waf_challenge_body, make_client, truncate_evidence,
)


async def run_corroboration_freshness_audit(
    url: str, root_url: str, brand_name: str,
    *,
    prefetched_html: str = "",
    prefetched_status: int = 0,
) -> dict[str, Any]:
    """
    Run Wikidata + DuckDuckGo Lite checks concurrently.
    Returns findings + cross_web_contract (corroboration output consumed by engagement audit).

    prefetched_html / prefetched_status: provided by the orchestrator from its
    single shared homepage fetch.  If status > 0, no new network request is made.
    """
    findings: list[dict] = []

    # ── Obtain on-site HTML for year-extraction ─────────────────────────────
    site_html = ""
    if prefetched_status > 0:
        # Use prefetched; only use content if it's a real 200 page
        if 200 <= prefetched_status < 300:
            site_html = prefetched_html
    else:
        try:
            async with make_client(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(url)
                if 200 <= resp.status_code < 300:
                    site_html = resp.text
        except Exception:
            pass


    # Extract on-site year references
    all_text = re.sub(r"<[^>]+>", " ", site_html)
    site_years = extract_year_mentions(all_text)
    y_site = max(site_years) if site_years else 0

    # Run Wikidata + DDG concurrently
    wikidata_result, ddg_result = await asyncio.gather(
        _check_wikidata(brand_name),
        _check_duckduckgo_freshness(brand_name, y_site, site_html),
        return_exceptions=True,
    )

    # Process Wikidata result
    layer3: dict = {
        "brand_name": brand_name,
        "offsite_price_str": "",
        "offsite_price_num": None,
        "offsite_year_max": None,
        "offsite_snippets": [],
        "wikidata_entity_found": False,
        "wikidata_qid": None,
        "corroboration_status": "blocked",
    }

    if isinstance(wikidata_result, Exception):
        findings.append({
            "id": "F-ENTITY-UNVERIFIED",
            "title": "Wikidata corroboration check failed",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"Wikidata entity search raised exception: "
                f"{type(wikidata_result).__name__}: {wikidata_result}. "
                "Unable to verify entity presence. Treating as unverified — not passing."
            ),
            "suggested_action": {
                "summary": "Re-run audit. Ensure outbound HTTPS to wikidata.org is available.",
                "priority": "medium", "effort": "low",
                "implementation_hint": "Test: curl https://www.wikidata.org/w/api.php?action=query&format=json"
            },
            "check_ref": "CHECK-1.9"
        })
    else:
        findings.extend(wikidata_result.get("findings", []))
        layer3.update({
            "wikidata_entity_found": wikidata_result.get("found", False),
            "wikidata_qid": wikidata_result.get("qid"),
            "corroboration_status": wikidata_result.get("status", "blocked"),
        })

    # Process DDG freshness result
    if isinstance(ddg_result, Exception):
        findings.append({
            "id": "F-FRESH-UNVERIFIED",
            "title": "DuckDuckGo freshness check failed",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"DuckDuckGo Lite temporal freshness check raised: "
                f"{type(ddg_result).__name__}: {ddg_result}. "
                "Temporal freshness delta cannot be computed."
            ),
            "suggested_action": {
                "summary": "Re-run audit. Ensure outbound HTTPS to duckduckgo.com is available.",
                "priority": "low", "effort": "low",
                "implementation_hint": "Test: curl 'https://lite.duckduckgo.com/lite/?q=test'"
            },
            "check_ref": "CHECK-1.10"
        })
    else:
        findings.extend(ddg_result.get("findings", []))
        layer3.update({
            "offsite_price_str": ddg_result.get("offsite_price_str", ""),
            "offsite_price_num": ddg_result.get("offsite_price_num"),
            "offsite_year_max": ddg_result.get("offsite_year_max"),
            "offsite_snippets": ddg_result.get("snippets", []),
        })
        if ddg_result.get("status") == "ok" and layer3.get("corroboration_status") == "ok":
            layer3["corroboration_status"] = "ok"
        elif ddg_result.get("status") in ("rate_limited", "blocked"):
            if layer3.get("corroboration_status") != "blocked":
                layer3["corroboration_status"] = "rate_limited"

    return {"findings": findings, "layer3_contract": layer3}


# ── Wikidata Entity Corroboration ─────────────────────────────────────────────

async def _check_wikidata(brand_name: str) -> dict:
    """
    Search Wikidata for brand entity. Handle rate limits and timeouts gracefully.
    """
    findings: list[dict] = []

    if not brand_name:
        findings.append({
            "id": "F-ENTITY-UNVERIFIED",
            "title": "Wikidata check skipped: no brand name extracted",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                "No brand_name available from JSON-LD entity check. "
                "Wikidata corroboration skipped. Add Organization JSON-LD with name field."
            ),
            "suggested_action": {
                "summary": "Add JSON-LD Organization with name field (see F-ENTITY-001).",
                "priority": "medium", "effort": "low",
                "implementation_hint": "Fix F-ENTITY-001 first — brand_name is extracted from Organization.name."
            },
            "check_ref": "CHECK-1.9"
        })
        return {"findings": findings, "found": False, "qid": None, "status": "blocked"}

    # Search Wikidata
    search_url = (
        f"https://www.wikidata.org/w/api.php"
        f"?action=wbsearchentities"
        f"&search={quote(brand_name)}"
        f"&language=en"
        f"&format=json"
        f"&limit=3"
    )

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=5.0),
            follow_redirects=True,
            headers={"User-Agent": "BrandAIAuditBot/2.0 (https://github.com/adobe-hackathon; contact@example.com)"},
            verify=False,
        ) as client:
            resp = await client.get(search_url)
    except httpx.TimeoutException:
        findings.append({
            "id": "F-ENTITY-UNVERIFIED",
            "title": "Wikidata corroboration timed out",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"Wikidata entity search for '{brand_name}' timed out after 8s. "
                "Unable to verify entity presence. Treating as unverified."
            ),
            "suggested_action": {
                "summary": "Network timeout to Wikidata. Re-run later.",
                "priority": "low", "effort": "low",
                "implementation_hint": "Test: curl https://www.wikidata.org/w/api.php?action=query&format=json"
            },
            "check_ref": "CHECK-1.9"
        })
        return {"findings": findings, "found": False, "qid": None, "status": "rate_limited"}
    except Exception as exc:
        raise exc

    if resp.status_code == 429:
        findings.append({
            "id": "F-ENTITY-UNVERIFIED",
            "title": "Wikidata corroboration rate-limited (HTTP 429)",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"Wikidata returned HTTP 429 Too Many Requests for brand '{brand_name}'. "
                "Treating as unverified — not passing."
            ),
            "suggested_action": {
                "summary": "Re-run audit after 60 seconds.",
                "priority": "low", "effort": "low",
                "implementation_hint": "Wikidata rate limits anonymous API access. Add delay between audits."
            },
            "check_ref": "CHECK-1.9"
        })
        return {"findings": findings, "found": False, "qid": None, "status": "rate_limited"}

    if resp.status_code != 200:
        findings.append({
            "id": "F-ENTITY-UNVERIFIED",
            "title": f"Wikidata corroboration failed (HTTP {resp.status_code})",
            "severity": "medium",
            "type": "defect",
            "evidence": f"Wikidata API returned HTTP {resp.status_code} for brand '{brand_name}'.",
            "suggested_action": {
                "summary": "Wikidata API error. Re-run later.",
                "priority": "low", "effort": "low",
                "implementation_hint": "Check Wikidata API status at https://www.wikidata.org/wiki/Wikidata:System"
            },
            "check_ref": "CHECK-1.9"
        })
        return {"findings": findings, "found": False, "qid": None, "status": "blocked"}

    try:
        data = resp.json()
    except Exception:
        findings.append({
            "id": "F-ENTITY-UNVERIFIED",
            "title": "Wikidata response parse error",
            "severity": "medium",
            "type": "defect",
            "evidence": "Wikidata API returned non-JSON response.",
            "suggested_action": {
                "summary": "Re-run audit.", "priority": "low", "effort": "low",
                "implementation_hint": "Wikidata API may be serving maintenance page."
            },
            "check_ref": "CHECK-1.9"
        })
        return {"findings": findings, "found": False, "qid": None, "status": "blocked"}

    search_results = data.get("search", [])

    if not search_results:
        findings.append({
            "id": "F-ENTITY-002",
            "title": f"Brand '{brand_name}' not found in Wikidata knowledge graph",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"Wikidata entity search for '{brand_name}' returned 0 results. "
                "Brand has no external knowledge-graph entry. "
                "AI assistants rely on Wikidata for entity resolution and fact cross-checking. "
                "Absence increases risk of hallucination and entity confusion."
            ),
            "suggested_action": {
                "summary": (
                    f"Create a Wikidata entry for '{brand_name}'. "
                    "Add the resulting QID to JSON-LD sameAs array."
                ),
                "priority": "medium",
                "effort": "medium",
                "implementation_hint": (
                    "1. Create account at wikidata.org. "
                    f"2. Create new item: label='{brand_name}', description='[industry] company'. "
                    "3. Add P18 (logo), P856 (website), P112 (founder), P571 (inception date). "
                    "4. Copy QID (Q-number) and add to JSON-LD sameAs."
                )
            },
            "check_ref": "CHECK-1.9"
        })
        return {"findings": findings, "found": False, "qid": None, "status": "ok"}

    # Entity found
    top = search_results[0]
    qid = top.get("id", "")
    label = top.get("label", "")
    description = top.get("description", "")

    findings.append({
        "id": "F-ENTITY-003",
        "title": f"Wikidata entity confirmed: {qid} — '{label}'",
        "severity": "low",
        "type": "proactive",
        "evidence": (
            f"Wikidata entity {qid} ('{label}') confirmed: {description}. "
            "External knowledge-graph corroboration verified. "
            "AI assistants can resolve this brand entity unambiguously."
        ),
        "suggested_action": {
            "summary": f"Keep Wikidata entry {qid} updated with current description, logo URL, and website.",
            "priority": "low", "effort": "low",
            "implementation_hint": f"Wikidata entry: https://www.wikidata.org/wiki/{qid}"
        },
        "check_ref": "CHECK-1.9"
    })

    return {"findings": findings, "found": True, "qid": qid, "status": "ok"}


# ── DuckDuckGo Lite Temporal Freshness Delta ──────────────────────────────────

async def _check_duckduckgo_freshness(
    brand_name: str, y_site: int, site_html: str
) -> dict:
    """
    Check temporal freshness delta using DuckDuckGo Lite (plain HTML, no JS needed).
    F-FRESH-001 if delta >= 2 years.
    """
    findings: list[dict] = []

    if not brand_name or y_site == 0:
        return {
            "findings": [], "offsite_price_str": "", "offsite_price_num": None,
            "offsite_year_max": None, "snippets": [], "status": "ok"
        }

    # Extract claim keyword from highest TF-IDF sentence containing y_site
    all_text = re.sub(r"<[^>]+>", " ", site_html)
    sentences = [s.strip() for s in re.split(r"[.!?]", all_text) if str(y_site) in s and len(s.strip()) > 10]
    claim_keyword = ""
    if sentences:
        # Take highest-word-count sentence as most informative
        best_sentence = max(sentences, key=len)
        # Extract 2-3 content words
        words = [w for w in re.findall(r"[A-Za-z]{4,}", best_sentence)
                 if w.lower() not in {"that", "this", "with", "from", "have", "been", "will"}]
        claim_keyword = " ".join(words[:3])

    query = f'"{brand_name}"'
    if claim_keyword:
        query += f' "{claim_keyword}"'

    ddg_url = f"https://lite.duckduckgo.com/lite/?q={quote(query)}"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=True,
            headers={
                **DEFAULT_HEADERS,
                "User-Agent": "Mozilla/5.0 (compatible; AuditBot/2.0)",
            },
            verify=False,
        ) as client:
            resp = await client.get(ddg_url)
    except httpx.TimeoutException:
        findings.append({
            "id": "F-FRESH-UNVERIFIED",
            "title": "DuckDuckGo freshness check timed out",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"DuckDuckGo Lite freshness check timed out after 10s for query '{query}'. "
                "Temporal freshness delta cannot be computed."
            ),
            "suggested_action": {
                "summary": "Re-run audit later.",
                "priority": "low", "effort": "low",
                "implementation_hint": "Test: curl 'https://lite.duckduckgo.com/lite/?q=test'"
            },
            "check_ref": "CHECK-1.10"
        })
        return {
            "findings": findings, "offsite_price_str": "", "offsite_price_num": None,
            "offsite_year_max": None, "snippets": [], "status": "rate_limited"
        }
    except Exception as exc:
        raise exc

    if resp.status_code != 200 or is_waf_challenge_body(resp.text):
        status_desc = f"HTTP {resp.status_code}" if resp.status_code != 200 else "CAPTCHA/challenge body"
        findings.append({
            "id": "F-FRESH-UNVERIFIED",
            "title": f"DuckDuckGo freshness check blocked ({status_desc})",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"DuckDuckGo Lite returned {status_desc} for freshness query. "
                "Temporal freshness delta cannot be computed."
            ),
            "suggested_action": {
                "summary": "Re-run audit from a different IP or later.",
                "priority": "low", "effort": "low",
                "implementation_hint": "DDG rate-limits automated queries. Add retry with backoff."
            },
            "check_ref": "CHECK-1.10"
        })
        return {
            "findings": findings, "offsite_price_str": "", "offsite_price_num": None,
            "offsite_year_max": None, "snippets": [], "status": "blocked"
        }

    # Parse DDG Lite plain HTML snippets
    snippet_pattern = re.compile(
        r'<(?:td|div)[^>]*class=["\'][^"\']*result-snippet[^"\']*["\'][^>]*>(.*?)</(?:td|div)>',
        re.DOTALL | re.IGNORECASE
    )
    snippets_raw = snippet_pattern.findall(resp.text)

    # Fallback: grab any <td> text content
    if not snippets_raw:
        snippets_raw = re.findall(r"<td[^>]*>(.*?)</td>", resp.text, re.DOTALL | re.IGNORECASE)

    snippets = []
    offsite_years: list[int] = []
    offsite_price_matches: list[str] = []

    for snip in snippets_raw[:10]:
        clean = re.sub(r"<[^>]+>", " ", snip).strip()
        clean = re.sub(r"\s+", " ", clean)
        if len(clean) > 15:
            snippets.append(clean[:200])
            offsite_years.extend(extract_year_mentions(clean))
            prices = re.findall(r"\$[\d,]+(?:\.\d{2})?(?:/mo(?:nth)?|/year|/yr)?", clean, re.IGNORECASE)
            offsite_price_matches.extend(prices)

    y_offsite = max(offsite_years) if offsite_years else 0

    # Extract price from offsite
    offsite_price_str = offsite_price_matches[0] if offsite_price_matches else ""
    offsite_price_num = _parse_price_to_monthly(offsite_price_str) if offsite_price_str else None

    # Freshness delta
    if y_site > 0 and y_offsite > 0:
        delta_freshness = y_site - y_offsite
        if delta_freshness >= 2:
            findings.append({
                "id": "F-FRESH-001",
                "title": f"Temporal freshness gap: site claims {y_site}, web corroborates only {y_offsite}",
                "severity": "high",
                "type": "defect",
                "evidence": (
                    f"On-site most recent year mention: {y_site}. "
                    f"DuckDuckGo corroboration (top snippets): latest year = {y_offsite}. "
                    f"delta_Freshness = +{delta_freshness} years. "
                    f"Sample snippet: '{snippets[0] if snippets else 'N/A'}'. "
                    "AI time-decay rankers will downgrade on-site claims as potentially stale."
                ),
                "suggested_action": {
                    "summary": (
                        f"Update external web presence to reflect current {y_site} information. "
                        "Ensure blog posts, press releases, and third-party profiles are current."
                    ),
                    "priority": "high",
                    "effort": "medium",
                    "implementation_hint": (
                        "1. Publish a press release or blog post with the current year + key claim. "
                        "2. Update Wikipedia/Wikidata entry with current facts. "
                        "3. Submit to PR newswire services. "
                        "4. Update LinkedIn company page with recent milestones."
                    )
                },
                "check_ref": "CHECK-1.10"
            })

    return {
        "findings": findings,
        "offsite_price_str": offsite_price_str,
        "offsite_price_num": offsite_price_num,
        "offsite_year_max": y_offsite,
        "snippets": snippets[:5],
        "status": "ok",
    }


def _parse_price_to_monthly(price_str: str) -> float | None:
    """Normalise price string to monthly float."""
    if not price_str:
        return None
    num_match = re.search(r"[\d,]+(?:\.\d{2})?", price_str.replace(",", ""))
    if not num_match:
        return None
    num = float(num_match.group().replace(",", ""))
    if "/year" in price_str.lower() or "/yr" in price_str.lower():
        num = num / 12
    return round(num, 2)
