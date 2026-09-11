#!/usr/bin/env python3
"""
entity_structured_data.py — JSON-LD / Structured Data Audit
Checks: Organization entity anchor, sameAs disambiguation, Schema.org completeness.

Finding IDs produced:
  F-ENTITY-001   No valid JSON-LD Organization entity / missing sameAs (High)
  F-SCHEMA-001   Missing FAQ/HowTo/Product schema on relevant pages (Medium)
  F-SCHEMA-002   Open Graph incomplete (Medium)
  F-SCHEMA-OK    Valid entity + sameAs found (proactive, Low)
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from .utils import (
    BROWSER_UA, find_json_ld_blocks, make_client, truncate_evidence,
)

# Authoritative disambiguation URIs for sameAs validation
AUTHORITATIVE_SAME_AS_DOMAINS = [
    "wikidata.org/wiki/Q",
    "crunchbase.com/organization/",
    "linkedin.com/company/",
    "opencorporates.com/",
    "isni.org/",
    "ror.org/",           # Research Organization Registry
    "d-nb.info/gnd/",     # German National Library
    "viaf.org/viaf/",     # Virtual International Authority File
]

# Required Organization fields
REQUIRED_ENTITY_FIELDS = {"name", "url", "description"}

SCHEMA_ORG_TYPES_ENTITY = {
    "Organization", "Corporation", "LocalBusiness", "Brand",
    "EducationalOrganization", "GovernmentOrganization", "NGO",
    "MedicalOrganization", "NewsMediaOrganization",
}

# High-value bonus schema types
BONUS_SCHEMA_TYPES = {
    "FAQPage": "F-SCHEMA-FAQ",
    "HowTo": "F-SCHEMA-HOWTO",
    "Product": "F-SCHEMA-PRODUCT",
    "Offer": "F-SCHEMA-OFFER",
    "BreadcrumbList": "F-SCHEMA-BREADCRUMB",
    "Article": "F-SCHEMA-ARTICLE",
    "WebSite": "F-SCHEMA-WEBSITE",
    "SearchAction": "F-SCHEMA-SEARCH",
}


async def run_entity_structured_data_audit(url: str) -> dict[str, Any]:
    """
    Fetch raw HTML, parse JSON-LD, validate entity anchor and Schema.org signals.
    Returns: findings + brand_name (consumed by corroboration audit).
    """
    findings: list[dict] = []
    brand_name: str = ""
    wikidata_qid: str | None = None

    # Fetch raw HTML (no JS hydration needed — JSON-LD is in static HTML)
    try:
        async with make_client(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": BROWSER_UA})
            html = resp.text
    except Exception as exc:
        return {
            "findings": [{
                "id": "F-ENTITY-FETCH-ERR",
                "title": "Failed to fetch page for JSON-LD analysis",
                "severity": "medium",
                "type": "defect",
                "evidence": f"Fetch error: {type(exc).__name__}: {exc}",
                "suggested_action": {
                    "summary": "Verify site is publicly accessible.",
                    "priority": "medium", "effort": "low",
                    "implementation_hint": "Check DNS and server availability."
                },
                "check_ref": "CHECK-1.8"
            }],
            "brand_name": "",
        }

    # Extract all JSON-LD blocks
    ld_blocks = find_json_ld_blocks(html)
    all_types_found: list[str] = []
    entity_block: dict | None = None
    entity_issues: list[str] = []

    for block in ld_blocks:
        # Handle @graph containers
        items = block.get("@graph", [block])
        for item in items:
            item_type = item.get("@type", "")
            if isinstance(item_type, list):
                item_types = item_type
            else:
                item_types = [item_type]

            for t in item_types:
                all_types_found.append(t)
                if t in SCHEMA_ORG_TYPES_ENTITY and entity_block is None:
                    entity_block = item

    # ── Check 1.8: Entity Identity Anchor ───────────────────────────────────
    if entity_block is None:
        findings.append({
            "id": "F-ENTITY-001",
            "title": "No JSON-LD Organization entity found",
            "severity": "high",
            "type": "defect",
            "evidence": (
                f"Scanned {len(ld_blocks)} JSON-LD block(s) on page. "
                f"Types found: {', '.join(all_types_found) if all_types_found else 'none'}. "
                "No Organization, Corporation, LocalBusiness, or Brand @type present. "
                "AI systems have no structured entity anchor — name disambiguation risk is high."
            ),
            "suggested_action": {
                "summary": (
                    "Add JSON-LD Organization schema to the homepage <head>. "
                    "Include: @type, name, url, description, logo, sameAs (Wikidata QID + LinkedIn)."
                ),
                "priority": "high",
                "effort": "low",
                "implementation_hint": _org_schema_template("YourBrand", url),
            },
            "check_ref": "CHECK-1.8"
        })
    else:
        # Entity found — validate fields and sameAs
        entity_name = entity_block.get("name", "")
        entity_url = entity_block.get("url", "")
        entity_desc = entity_block.get("description", "")
        same_as = entity_block.get("sameAs", [])
        if isinstance(same_as, str):
            same_as = [same_as]

        brand_name = entity_name

        # Check required fields
        missing_fields = []
        if not entity_name:
            missing_fields.append("name")
        if not entity_url:
            missing_fields.append("url")
        if not entity_desc:
            missing_fields.append("description")

        # Check sameAs for authoritative URIs
        authoritative_uris = [
            uri for uri in same_as
            if any(domain in uri for domain in AUTHORITATIVE_SAME_AS_DOMAINS)
        ]

        # Extract Wikidata QID if present
        for uri in same_as:
            qid_match = re.search(r"wikidata\.org/wiki/(Q\d+)", uri)
            if qid_match:
                wikidata_qid = qid_match.group(1)
                break

        if missing_fields or not authoritative_uris:
            issues = []
            if missing_fields:
                issues.append(f"missing fields: {', '.join(missing_fields)}")
            if not authoritative_uris:
                issues.append("sameAs has no authoritative disambiguation URIs (Wikidata/Crunchbase/LinkedIn)")
            elif not wikidata_qid:
                issues.append("sameAs present but no Wikidata QID — entity graph disambiguation incomplete")

            findings.append({
                "id": "F-ENTITY-001",
                "title": f"JSON-LD Organization entity incomplete: {'; '.join(issues)}",
                "severity": "high",
                "type": "defect",
                "evidence": (
                    f"JSON-LD {entity_block.get('@type', 'Organization')} found "
                    f"(name: '{entity_name}'). "
                    f"Issues: {'; '.join(issues)}. "
                    f"Current sameAs: {same_as if same_as else 'empty'}. "
                    "Without authoritative URIs, AI entity graphs cannot disambiguate this brand "
                    "from similarly-named entities."
                ),
                "suggested_action": {
                    "summary": (
                        "Complete Organization schema: add missing fields and authoritative sameAs URIs. "
                        "Register on Wikidata and add the QID to sameAs."
                    ),
                    "priority": "high",
                    "effort": "medium",
                    "implementation_hint": (
                        f"Add to sameAs: Wikidata QID (https://www.wikidata.org/wiki/Q....), "
                        f"Crunchbase (https://www.crunchbase.com/organization/{entity_name.lower().replace(' ', '-')}), "
                        f"LinkedIn (https://www.linkedin.com/company/{entity_name.lower().replace(' ', '-')}). "
                        "If no Wikidata entry exists, create one at wikidata.org."
                    )
                },
                "check_ref": "CHECK-1.8"
            })
        else:
            # Full pass — proactive
            findings.append({
                "id": "F-SCHEMA-OK",
                "title": f"JSON-LD Organization entity complete with disambiguation anchors",
                "severity": "low",
                "type": "proactive",
                "evidence": (
                    f"JSON-LD {entity_block.get('@type', 'Organization')} found: "
                    f"name='{entity_name}', url='{entity_url}'. "
                    f"sameAs includes {len(authoritative_uris)} authoritative URI(s). "
                    f"{'Wikidata QID: ' + wikidata_qid if wikidata_qid else ''}. "
                    "Entity graph disambiguation anchors in place."
                ),
                "suggested_action": {
                    "summary": "Keep sameAs URIs updated as brand registers on new authoritative platforms.",
                    "priority": "low", "effort": "low",
                    "implementation_hint": "Review sameAs annually. Add ISNI/ROR if applicable."
                },
                "check_ref": "CHECK-1.8"
            })

    # ── Bonus Schema.org signals ─────────────────────────────────────────────
    missing_bonus = []
    for schema_type in ["FAQPage", "BreadcrumbList", "WebSite"]:
        if schema_type not in all_types_found:
            missing_bonus.append(schema_type)

    if missing_bonus:
        findings.append({
            "id": "F-SCHEMA-001",
            "title": f"Missing high-value Schema.org types: {', '.join(missing_bonus)}",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"Found schema types: {', '.join(all_types_found) if all_types_found else 'none'}. "
                f"Missing: {', '.join(missing_bonus)}. "
                "FAQPage schema enables AI assistants to cite specific Q&A. "
                "BreadcrumbList improves page hierarchy understanding. "
                "WebSite with SearchAction enables sitelinks search box."
            ),
            "suggested_action": {
                "summary": (
                    f"Add {', '.join(missing_bonus)} JSON-LD schema blocks to appropriate pages."
                ),
                "priority": "medium",
                "effort": "medium",
                "implementation_hint": (
                    "FAQPage: add to /faq or any page with Q&A content. "
                    "BreadcrumbList: add to all inner pages. "
                    "WebSite: add to homepage with potentialAction SearchAction pointing to site search."
                )
            },
            "check_ref": "CHECK-SCHEMA"
        })

    # ── Open Graph completeness ──────────────────────────────────────────────
    og_findings = _check_open_graph(html)
    findings.extend(og_findings)

    return {
        "findings": findings,
        "brand_name": brand_name,
        "wikidata_qid": wikidata_qid,
        "all_schema_types": all_types_found,
    }


def _check_open_graph(html: str) -> list[dict]:
    """Check Open Graph meta tags for completeness."""
    findings: list[dict] = []
    required_og = ["og:title", "og:description", "og:image", "og:url", "og:type"]
    found_og = set()

    for prop in required_og:
        if re.search(rf'property=["\']({prop})["\']', html, re.IGNORECASE):
            found_og.add(prop)

    missing_og = [p for p in required_og if p not in found_og]

    # Twitter Card
    has_twitter_card = bool(re.search(r'name=["\']twitter:card["\']', html, re.IGNORECASE))

    if missing_og or not has_twitter_card:
        issues = []
        if missing_og:
            issues.append(f"Missing Open Graph tags: {', '.join(missing_og)}")
        if not has_twitter_card:
            issues.append("Missing twitter:card meta tag")

        findings.append({
            "id": "F-SIGNAL-001",
            "title": "Incomplete social/AI sharing signals: Open Graph and Twitter Card",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"Open Graph: found {len(found_og)}/{len(required_og)} required tags. "
                f"{'; '.join(issues)}. "
                "AI assistants and social platforms use OG tags for rich link previews and "
                "content summarisation. Missing tags cause degraded AI citation quality."
            ),
            "suggested_action": {
                "summary": (
                    "Add all required Open Graph meta tags and twitter:card to every page <head>."
                ),
                "priority": "medium",
                "effort": "low",
                "implementation_hint": (
                    "Add to <head>:\n"
                    '<meta property="og:title" content="[Page Title]">\n'
                    '<meta property="og:description" content="[150-char description]">\n'
                    '<meta property="og:image" content="[absolute image URL, min 1200×630px]">\n'
                    '<meta property="og:url" content="[canonical URL]">\n'
                    '<meta property="og:type" content="website">\n'
                    '<meta name="twitter:card" content="summary_large_image">'
                )
            },
            "check_ref": "CHECK-OG"
        })

    return findings


def _org_schema_template(name: str, url: str) -> str:
    return (
        '<script type="application/ld+json">{\n'
        '  "@context": "https://schema.org",\n'
        '  "@type": "Organization",\n'
        f'  "name": "{name}",\n'
        f'  "url": "{url}",\n'
        '  "description": "[Your brand description]",\n'
        '  "logo": "[Logo URL]",\n'
        '  "sameAs": [\n'
        '    "https://www.wikidata.org/wiki/Q[YOUR_QID]",\n'
        '    "https://www.linkedin.com/company/[your-company]",\n'
        '    "https://www.crunchbase.com/organization/[your-company]"\n'
        '  ]\n'
        '}</script>'
    )
