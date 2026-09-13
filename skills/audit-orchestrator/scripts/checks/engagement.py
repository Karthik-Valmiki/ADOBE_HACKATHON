#!/usr/bin/env python3
"""
engagement.py — On-Site Engagement Audit
Checks: intent mismatch, hidden hash anchor, CTA above-hero,
full-screen overlay, web-to-AI price divergence, boilerplate noise.

Finding IDs produced:
  F-ENG-004    Intent mismatch delta_Intent < 0.30 (High)
  F-ENG-003    Hidden URL hash anchor (Critical)
  F-ENG-007    No CTA before hero boundary (High)
  F-ENG-009    Full-screen overlay at load (Critical)
  F-ENG-010    Scroll-triggered overlay (Critical)
  F-ENG-013    Web-to-AI price divergence (Critical)
  F-ENG-013-UNVERIFIED  Divergence check skipped (Medium)
  F-ENG-006    Boilerplate noise ratio > 2.5 (Medium)
  F-ENG-005    Long paragraph without visual anchors (Medium)
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from .utils import (
    BROWSER_UA, extract_text_from_html, tokenize, truncate_evidence, word_count,
)

# CSS declarative signatures for overlay detection (no pixel geometry)
OVERLAY_CSS_CLASSES = re.compile(
    r'class=["\'][^"\']*(?:modal|overlay|popup|lightbox|backdrop|cookie|consent|'
    r'interstitial|gate|paywall|newsletter-signup|exit-intent)[^"\']*["\']',
    re.IGNORECASE
)
OVERLAY_ID_PATTERNS = re.compile(
    r'id=["\'][^"\']*(?:modal|overlay|popup|lightbox|backdrop|cookie|consent|'
    r'newsletter|gate|paywall)[^"\']*["\']',
    re.IGNORECASE
)
FIXED_POSITION = re.compile(r'position\s*:\s*fixed', re.IGNORECASE)
ABSOLUTE_POSITION = re.compile(r'position\s*:\s*absolute', re.IGNORECASE)
HIGH_ZINDEX = re.compile(r'z-index\s*:\s*(\d+)', re.IGNORECASE)
FULL_VIEWPORT_WIDTH = re.compile(
    r'(?:width\s*:\s*(?:100%|100vw))|(?:class=["\'][^"\']*(?:w-full|w-screen)[^"\']*["\'])',
    re.IGNORECASE
)
FULL_VIEWPORT_HEIGHT = re.compile(
    r'(?:height\s*:\s*(?:100%|100vh))|(?:class=["\'][^"\']*(?:h-full|h-screen|inset-0)[^"\']*["\'])',
    re.IGNORECASE
)
DISMISS_CONTROL = re.compile(
    r'(?:<button[^>]*>|aria-label=["\'][^"\']*(?:close|dismiss|accept|ok|got.it)[^"\']*["\']|'
    r'role=["\']dialog["\'])',
    re.IGNORECASE
)

CTA_PATTERNS = re.compile(
    r'<(?:button|input)[^>]*(?:type=["\']submit["\'])?[^>]*>|'
    r'<a[^>]+(?:class|href)[^>]*(?:btn|cta|sign.?up|get.?started|try|download|contact|'
    r'start.?free|book|schedule|request|demo|learn.?more)[^>]*>',
    re.IGNORECASE
)

HERO_BOUNDARY_CLASSES = re.compile(
    r'(?:class|id)=["\'][^"\']*(?:hero|banner|jumbotron|intro|landing|above.?fold)[^"\']*["\']',
    re.IGNORECASE
)

BOILERPLATE_TAGS = re.compile(r'<(?:nav|header|footer)[^>]*>.*?</(?:nav|header|footer)>', re.DOTALL | re.IGNORECASE)
SIDEBAR_PATTERNS = re.compile(r'<[^>]+(?:class|id)=["\'][^"\']*sidebar[^"\']*["\'][^>]*>.*?</[^>]+>', re.DOTALL | re.IGNORECASE)
CONTENT_TAGS = re.compile(r'<(?:main|article)[^>]*>.*?</(?:main|article)>', re.DOTALL | re.IGNORECASE)

COLLAPSED_STATE = re.compile(
    r'(?:display\s*:\s*none|visibility\s*:\s*hidden|height\s*:\s*0(?:px)?|'
    r'aria-expanded=["\']false["\']|\bhidden\b|'
    r'class=["\'][^"\']*(?:collapse|tab-pane|accordion|folded|hidden|d-none|'
    r'is-hidden|u-hide|sr-only)[^"\']*["\'])',
    re.IGNORECASE
)

PRICE_PATTERN = re.compile(
    r'\$[\d,]+(?:\.\d{2})?(?:/mo(?:nth)?|/year|/yr|/user|/seat)?',
    re.IGNORECASE
)


async def run_engagement_audit(
    url: str,
    hydrated_html: str | None,
    cross_web_corroboration: dict,
) -> dict[str, Any]:
    """Run all on-site engagement checks on the hydrated DOM."""
    findings: list[dict] = []

    if not hydrated_html:
        return {
            "findings": [{
                "id": "F-ENG-NO-DOM",
                "title": "On-site engagement checks skipped: rendered DOM is unavailable",
                "severity": "medium",
                "type": "defect",
                "evidence": (
                    "jsdom hydration did not return a rendered HTML document. "
                    "Intent mismatch, overlay, CTA, and price-divergence checks could not run."
                ),
                "suggested_action": {
                    "summary": "Resolve DOM hydration failures (see F-DOM-* findings) and re-run the audit.",
                    "priority": "medium",
                    "effort": "low",
                    "implementation_hint": (
                        "Check that Node.js 18+ is on PATH (node --version) and that "
                        "jsdom dependencies are installed (cd skills/audit-orchestrator/scripts && npm install)."
                    )
                },
                "check_ref": "CHECK-2.0"
            }]
        }

    html = hydrated_html

    # --- WAF / Bot-Challenge Guard ---
    # If the HTML is a Cloudflare/WAF interstitial, it is not a real page and 
    # may contain obfuscated strings that break text parsers.
    if html and ("challenge-platform" in html.lower() or "cf-browser-verification" in html.lower() or "just a moment..." in html.lower() or "cf-turnstile" in html.lower()):
        return {
            "findings": [{
                "id": "F-ENG-WAF-DEGRADED",
                "title": "On-site engagement checks skipped: HTTP 403 / WAF challenge page",
                "severity": "medium",
                "type": "defect",
                "evidence": "A bot-challenge or WAF interstitial page was detected. Engagement checks (CTA, intent, noise ratio) cannot be evaluated accurately on challenge pages.",
                "suggested_action": {
                    "summary": "Allowlist audit tool IP in WAF to obtain accurate engagement analysis.",
                    "priority": "medium",
                    "effort": "medium",
                    "implementation_hint": "See F-NET-WAF-BLOCK for WAF allowlist instructions."
                },
                "check_ref": "CHECK-2.0"
            }]
        }

    # Check 2.1: Intent Mismatch
    findings.extend(_check_intent_mismatch(url, html))

    # Check 2.2: Hidden Hash Anchor
    findings.extend(_check_hidden_hash_anchor(url, html))

    # Check 2.3: CTA Above Hero Boundary
    findings.extend(_check_cta_above_hero(html))

    # Check 2.4: Full-Screen Overlay
    findings.extend(_check_fullscreen_overlay(html))

    # Check 2.5: Web-to-AI Price Divergence
    findings.extend(_check_price_divergence(html, cross_web_corroboration))

    # Check 2.6: Boilerplate Noise + Paragraph Density
    findings.extend(_check_boilerplate_noise(html))
    findings.extend(_check_paragraph_density(html))

    return {"findings": findings}


# ── Check 2.1: Intent Mismatch ───────────────────────────────────────────────

def _check_intent_mismatch(url: str, html: str) -> list[dict]:
    """
    F-ENG-004: delta_Intent = |T_ref ∩ T_hero| / |T_ref| < 0.30.
    T_ref from <title>. T_hero from h1/h2 + hero section.
    """
    findings: list[dict] = []

    # Extract page title token set
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    page_title = title_match.group(1).strip() if title_match else ""
    # Strip site name suffix (e.g. "Page Title | Brand Name")
    page_title = re.split(r"\s*[|—–-]\s*", page_title)[0].strip()
    t_ref = tokenize(page_title)

    if not t_ref:
        return findings  # No title = skip (can't compute meaningful delta)

    # Extract hero section tokens: h1, h2, first hero/banner section
    hero_parts: list[str] = []

    for h_match in re.finditer(r"<(h[12])[^>]*>(.*?)</\1>", html, re.IGNORECASE | re.DOTALL):
        hero_parts.append(re.sub(r"<[^>]+>", "", h_match.group(2)).strip())

    # Hero div/section by class
    hero_section_match = re.search(
        r'<(?:section|div)[^>]+(?:class|id)=["\'][^"\']*(?:hero|banner|jumbotron|intro)[^"\']*["\'][^>]*>(.*?)</(?:section|div)>',
        html, re.DOTALL | re.IGNORECASE
    )
    if hero_section_match:
        hero_text = re.sub(r"<[^>]+>", " ", hero_section_match.group(1))
        hero_parts.append(hero_text[:500])

    # First visible paragraph as fallback
    first_p_match = re.search(r"<p[^>]*>(.*?)</p>", html, re.DOTALL | re.IGNORECASE)
    if first_p_match:
        hero_parts.append(re.sub(r"<[^>]+>", "", first_p_match.group(1)).strip())

    t_hero = tokenize(" ".join(hero_parts))

    if not t_hero:
        return findings  # No hero content found = skip

    # Compute delta_Intent
    intersection = t_ref & t_hero
    delta_intent = len(intersection) / len(t_ref)

    if delta_intent < 0.30:
        findings.append({
            "id": "F-ENG-004",
            "title": f"Intent mismatch: AI referral visitors will not confirm landing (delta={delta_intent:.2f})",
            "severity": "high",
            "type": "defect",
            "evidence": (
                f"Page title tokens: {sorted(t_ref)}. "
                f"Hero section tokens: {sorted(list(t_hero)[:15])}. "
                f"Intersection: {sorted(intersection)}. "
                f"delta_Intent = {len(intersection)}/{len(t_ref)} = {delta_intent:.2f} (< 0.30 threshold). "
                "AI assistants cite this page for topics in the title, but arriving users see "
                "hero content with < 30% token overlap — causing immediate bounce."
            ),
            "suggested_action": {
                "summary": (
                    "Align hero section language with page title. "
                    f"Include key terms from title in H1/H2: {sorted(t_ref)}."
                ),
                "priority": "high",
                "effort": "medium",
                "implementation_hint": (
                    "Rewrite H1/H2 to echo the page title's primary keyword. "
                    "E.g., if title is 'Enterprise Security Platform', H1 should mention "
                    "'enterprise security'. Avoid purely aspirational hero copy divorced from SEO title."
                )
            },
            "check_ref": "CHECK-2.1"
        })

    return findings


# ── Check 2.2: Hidden Hash Anchor ─────────────────────────────────────────────────

def _check_hidden_hash_anchor(url: str, html: str) -> list[dict]:
    """
    F-ENG-003: URL #fragment target hidden on initial render.
    Checks inline style + class-based CSS signatures.
    """
    findings: list[dict] = []

    parsed = urlparse(url)
    fragment = parsed.fragment
    if not fragment:
        return findings  # No hash = skip

    # Find element with matching id
    id_pattern = re.compile(
        rf'<([a-z][a-z0-9]*)[^>]+id=["\'](?:{re.escape(fragment)})["\'][^>]*>(.*?)</\1>',
        re.DOTALL | re.IGNORECASE
    )
    match = id_pattern.search(html)
    if not match:
        # Try self-closing / id at element level
        match_simple = re.search(
            rf'<[^>]+id=["\'](?:{re.escape(fragment)})["\'][^>]*>',
            html, re.IGNORECASE
        )
        if not match_simple:
            return findings  # Element not found in DOM = skip (may be dynamically created)

        element_html = match_simple.group(0)
    else:
        # Check both element attrs and walk up ancestors (simplified: check surrounding context)
        element_html = match.group(0)

    # Check the element itself for collapsed state
    if COLLAPSED_STATE.search(element_html):
        findings.append({
            "id": "F-ENG-003",
            "title": f"AI-cited URL hash '#{fragment}' targets a hidden element",
            "severity": "critical",
            "type": "defect",
            "evidence": (
                f"URL fragment '#{fragment}' resolved to DOM element "
                f"with collapsed-state signal (display:none / visibility:hidden / "
                f"aria-expanded=false / class: tab-pane/accordion/collapse). "
                "AI assistants frequently cite deep anchor links. "
                "Users landing on this URL will see a blank/wrong view and immediately bounce."
            ),
            "suggested_action": {
                "summary": (
                    f"Ensure '#{fragment}' target is visible on initial page load. "
                    "Implement URL hash detection to auto-open collapsed sections."
                ),
                "priority": "critical",
                "effort": "medium",
                "implementation_hint": (
                    "Add JavaScript: if(window.location.hash) { "
                    "const el = document.querySelector(window.location.hash); "
                    "if(el) { el.style.display='block'; el.closest('.accordion')?.classList.add('active'); } }. "
                    "Or use CSS :target selector to show targeted elements."
                )
            },
            "check_ref": "CHECK-2.2"
        })

    # Also check ancestor context (100 chars before element)
    pos = html.find(element_html)
    if pos > 0:
        ancestor_context = html[max(0, pos - 2000):pos]
        # Count unclosed collapsed wrappers
        collapsed_opens = len(COLLAPSED_STATE.findall(ancestor_context))
        if collapsed_opens > 0 and not findings:
            findings.append({
                "id": "F-ENG-003",
                "title": f"AI-cited URL hash '#{fragment}' may be inside a collapsed container",
                "severity": "critical",
                "type": "defect",
                "evidence": (
                    f"URL fragment '#{fragment}' element has {collapsed_opens} collapsed-state "
                    f"ancestor(s) detected in surrounding DOM context. "
                    "Element may be hidden inside a tab/accordion panel."
                ),
                "suggested_action": {
                    "summary": f"Auto-expand the container holding '#{fragment}' on page load when hash is present.",
                    "priority": "critical",
                    "effort": "medium",
                    "implementation_hint": (
                        "Use window.location.hash to detect and expand the relevant tab/accordion. "
                        "Consider SSR-rendering the target content visible by default."
                    )
                },
                "check_ref": "CHECK-2.2"
            })

    return findings


# ── Check 2.3: CTA Above Hero Boundary ───────────────────────────────────────────

def _check_cta_above_hero(html: str) -> list[dict]:
    """
    F-ENG-007: No CTA in document order before hero boundary.
    CONSTRAINT: DOM order only — no pixel geometry.
    Hero boundary = first non-nav/header H1/H2 OR hero-class section OR 5th body child.
    """
    findings: list[dict] = []

    # Remove head section to focus on body
    body_match = re.search(r"<body[^>]*>(.*)</body>", html, re.DOTALL | re.IGNORECASE)
    body_html = body_match.group(1) if body_match else html

    # Remove nav/header/aside from consideration for hero boundary
    body_no_nav = re.sub(
        r"<(?:nav|header|aside)[^>]*>.*?</(?:nav|header|aside)>",
        "<!-- NAV_REMOVED -->",
        body_html, flags=re.DOTALL | re.IGNORECASE
    )

    # Find hero boundary: first H1/H2 outside nav/header/aside
    hero_boundary_pos = len(body_no_nav)  # Default: end of document
    hero_boundary_desc = "document end (no H1/H2 or hero section found)"

    h_match = re.search(r"<h[12][^>]*>", body_no_nav, re.IGNORECASE)
    if h_match:
        hero_boundary_pos = h_match.start()
        h_tag = re.sub(r"<[^>]+>", "", h_match.group(0)[:50])
        if not h_tag.isprintable() or "\ufffd" in h_tag:
            h_tag = "[Obfuscated/Garbled Challenge String]"
        hero_boundary_desc = f"first H1/H2: '{h_tag}'"

    # Check for hero-class section (use original body, not de-navved)
    hero_section = HERO_BOUNDARY_CLASSES.search(body_html)
    if hero_section and hero_section.start() < hero_boundary_pos:
        hero_boundary_pos = hero_section.start()
        hero_boundary_desc = "hero/banner section"

    # Fallback: 5th top-level block-level child
    if hero_boundary_pos == len(body_no_nav):
        block_elements = list(re.finditer(r"<(?:div|section|p|ul|ol|table|form)[^>]*>", body_no_nav, re.IGNORECASE))
        if len(block_elements) >= 5:
            hero_boundary_pos = block_elements[4].start()
            hero_boundary_desc = "5th top-level block element (fallback)"

    # Look for CTA before hero boundary in original body_html
    before_hero = body_html[:hero_boundary_pos]
    cta_match = CTA_PATTERNS.search(before_hero)

    if not cta_match:
        # Find nearest CTA after boundary for evidence
        after_hero = body_html[hero_boundary_pos:]
        first_cta_after = CTA_PATTERNS.search(after_hero)
        cta_info = "No CTA found anywhere on page" if not first_cta_after else "First CTA appears after hero boundary"

        findings.append({
            "id": "F-ENG-007",
            "title": "No call-to-action before hero boundary",
            "severity": "high",
            "type": "defect",
            "evidence": (
                f"Hero boundary: {hero_boundary_desc} (document order position {hero_boundary_pos}). "
                f"No <button>, <a class=*btn*/*cta*>, or <input type=submit> found before boundary. "
                f"{cta_info}. "
                "AI-referred visitors with high intent find no action to take in the first visible region."
            ),
            "suggested_action": {
                "summary": (
                    "Add a primary CTA button/link before the first H1/hero section. "
                    "Examples: 'Get Started', 'Start Free Trial', 'Book a Demo'."
                ),
                "priority": "high",
                "effort": "low",
                "implementation_hint": (
                    "Add to the nav or top banner: "
                    '<a href="/signup" class="btn btn-primary">Get Started Free</a>. '
                    "Ensure it is visible in the static HTML (not injected by JS after load)."
                )
            },
            "check_ref": "CHECK-2.3"
        })

    return findings


# ── Check 2.4: Full-Screen Overlay ────────────────────────────────────────────────

def _check_fullscreen_overlay(html: str) -> list[dict]:
    """
    F-ENG-009: Full-viewport overlay at load (CSS declarative signature).
    F-ENG-010: Scroll-triggered overlay (simulated via event dispatch patterns).
    CONSTRAINT: CSS-declarative signatures only — no rendered pixel area.
    """
    findings: list[dict] = []

    # Step 1: Find candidate overlay elements using CSS signatures
    # Strategy: find elements with fixed/absolute positioning + high z-index + full size + overlay class/id
    element_pattern = re.compile(
        r'<(div|section|aside|dialog|form)[^>]*(?:'
        r'(?:class|id)=["\'][^"\']*(?:modal|overlay|popup|lightbox|backdrop|cookie|consent|gate|paywall)[^"\']*["\']'
        r'|style=["\'][^"\']*(?:position\s*:\s*(?:fixed|absolute))[^"\']*["\']'
        r')[^>]*>(.*?)</\1>',
        re.DOTALL | re.IGNORECASE
    )

    for el_match in element_pattern.finditer(html):
        tag = el_match.group(1)
        full_el = el_match.group(0)
        inner = el_match.group(2)

        # Check CSS declarative signatures
        has_fixed_or_absolute = FIXED_POSITION.search(full_el) or ABSOLUTE_POSITION.search(full_el)
        has_overlay_class = OVERLAY_CSS_CLASSES.search(full_el) or OVERLAY_ID_PATTERNS.search(full_el)

        # z-index check
        zindex_match = HIGH_ZINDEX.search(full_el)
        has_high_zindex = zindex_match and int(zindex_match.group(1)) >= 999

        # Full viewport size check
        has_full_width = FULL_VIEWPORT_WIDTH.search(full_el)
        has_full_height = FULL_VIEWPORT_HEIGHT.search(full_el)

        # Must have at least: (fixed/absolute OR overlay class) AND (high z-index OR full size)
        is_overlay_candidate = (
            (has_fixed_or_absolute or has_overlay_class) and
            (has_high_zindex or (has_full_width and has_full_height))
        )

        if not is_overlay_candidate:
            continue

        # Check for dismiss control
        has_dismiss = DISMISS_CONTROL.search(inner)

        # Extract element descriptor
        class_match = re.search(r'class=["\']([^"\']{1,60})["\']', full_el)
        id_match = re.search(r'id=["\']([^"\']{1,40})["\']', full_el)
        el_desc = f"<{tag}"
        if class_match:
            el_desc += f" class='{class_match.group(1)[:40]}'"
        if id_match:
            el_desc += f" id='{id_match.group(1)}'"
        el_desc += ">"

        if not has_dismiss:
            findings.append({
                "id": "F-ENG-009",
                "title": "Full-screen overlay with no dismiss control detected at page load",
                "severity": "critical",
                "type": "defect",
                "evidence": (
                    f"Full-viewport overlay element: {el_desc}. "
                    f"Signatures: "
                    f"{'position:fixed/absolute ' if has_fixed_or_absolute else ''}"
                    f"{'z-index:' + zindex_match.group(1) + ' ' if zindex_match else ''}"
                    f"{'overlay/modal class ' if has_overlay_class else ''}"
                    f"{'full-width ' if has_full_width else ''}"
                    f"{'full-height ' if has_full_height else ''}. "
                    "No close button or dismiss control found in subtree. "
                    "AI-referred users with specific intent find content blocked — causing immediate exit."
                ),
                "suggested_action": {
                    "summary": (
                        "Add a visible close/dismiss button to the overlay. "
                        "For cookie banners: add 'Accept' AND 'X Close' buttons. "
                        "Consider replacing modal with inline banner for non-critical messages."
                    ),
                    "priority": "critical",
                    "effort": "low",
                    "implementation_hint": (
                        'Add <button aria-label="Close" onclick="this.closest(\'.modal\').style.display=\'none\'">✕</button> '
                        "inside the overlay. "
                        "For cookie banners: ensure 'Accept All' button triggers closure. "
                        "Defer newsletter modals to 30-second delay or on exit-intent only."
                    )
                },
                "check_ref": "CHECK-2.4"
            })
        break  # Report first overlay found — avoid duplicate findings

    # Step 2: Scroll-triggered overlay detection
    # Look for scroll event listeners in HTML (addEventListener('scroll') patterns)
    scroll_listener_pattern = re.compile(
        r"addEventListener\s*\(\s*['\"]scroll['\"]|"
        r"onscroll\s*=|"
        r"window\.onscroll",
        re.IGNORECASE
    )
    exit_intent_pattern = re.compile(
        r"addEventListener\s*\(\s*['\"]mouseleave['\"]|"
        r"mouseout.*exit|"
        r"exitIntent",
        re.IGNORECASE
    )

    # Check inline scripts for scroll/exit-intent triggers
    inline_scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE)
    has_scroll_trigger = any(scroll_listener_pattern.search(s) for s in inline_scripts)
    has_exit_intent = any(exit_intent_pattern.search(s) for s in inline_scripts)

    if (has_scroll_trigger or has_exit_intent) and not findings:
        # Look for hidden popup elements that might be activated by scroll
        hidden_popups = re.findall(
            r'<[^>]+(?:class|id)=["\'][^"\']*(?:popup|modal|overlay)[^"\']*["\'][^>]*'
            r'(?:style=["\'][^"\']*display\s*:\s*none[^"\']*["\']|hidden)[^>]*>',
            html, re.IGNORECASE
        )
        if hidden_popups:
            trigger_type = "scroll" if has_scroll_trigger else "exit-intent"
            findings.append({
                "id": "F-ENG-010",
                "title": f"Potential {trigger_type}-triggered overlay detected",
                "severity": "critical",
                "type": "defect",
                "evidence": (
                    f"Page contains {len(hidden_popups)} initially-hidden popup/overlay element(s) "
                    f"AND a {trigger_type} event listener in inline JavaScript. "
                    "Scroll-triggered popups interrupt AI-referred visitors who are actively reading content. "
                    "Note: IntersectionObserver-gated overlays not detectable in static analysis."
                ),
                "suggested_action": {
                    "summary": (
                        f"Remove or delay {trigger_type}-triggered overlays for AI-referred traffic. "
                        "Use UTM parameter detection to suppress overlays for referred visitors."
                    ),
                    "priority": "critical",
                    "effort": "medium",
                    "implementation_hint": (
                        "Detect AI referral: if(document.referrer.includes('perplexity') || "
                        "document.referrer.includes('openai')) { suppressPopups = true; }. "
                        "Or suppress on first visit: use sessionStorage to track first-visit flag."
                    )
                },
                "check_ref": "CHECK-2.4"
            })

    return findings


# ── Check 2.5: Web-to-AI Price Divergence ────────────────────────────────────────

def _check_price_divergence(html: str, cross_web_corroboration: dict) -> list[dict]:
    """
    F-ENG-013: Detects a numeric mismatch between on-site pricing and off-site
    pricing captured from corroboration sources (DuckDuckGo Lite snippets).
    F-ENG-013-UNVERIFIED: Off-site price data was unavailable during this run.
    """
    findings: list[dict] = []

    corroboration_status = cross_web_corroboration.get("corroboration_status", "blocked")
    offsite_price_num = cross_web_corroboration.get("offsite_price_num")
    offsite_price_str = cross_web_corroboration.get("offsite_price_str", "")
    offsite_snippets = cross_web_corroboration.get("offsite_snippets", [])

    if corroboration_status in ("rate_limited", "blocked") or offsite_price_num is None:
        findings.append({
            "id": "F-ENG-013-UNVERIFIED",
            "title": "Web-to-AI price divergence check skipped: off-site data unavailable",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"Cross-web corroboration status: '{corroboration_status}'. "
                "Off-site pricing data was unavailable during this audit run. "
                "On-site pricing could not be verified against AI-cached external sources."
            ),
            "suggested_action": {
                "summary": "Ensure public pricing data is consistently represented across external sources.",
                "priority": "medium", "effort": "low",
                "implementation_hint": (
                    "Manually verify pricing on: G2, Capterra, Crunchbase, LinkedIn. "
                    "Use Offer JSON-LD schema to signal authoritative pricing to AI crawlers."
                )
            },
            "check_ref": "CHECK-2.5"
        })
        return findings

    # Extract on-site pricing
    from .utils import find_json_ld_blocks
    ld_blocks = find_json_ld_blocks(html)
    onsite_prices: list[float] = []
    onsite_price_str = ""

    # Check JSON-LD Offer schema first
    for block in ld_blocks:
        items = block.get("@graph", [block])
        for item in items:
            if item.get("@type") in ("Offer", "AggregateOffer"):
                price = item.get("price") or item.get("lowPrice")
                if price:
                    try:
                        onsite_prices.append(float(str(price).replace(",", "")))
                        onsite_price_str = f"${price}"
                    except ValueError:
                        pass

    # Fallback: regex price from visible text
    if not onsite_prices:
        page_text = extract_text_from_html(html)
        price_matches = PRICE_PATTERN.findall(page_text)
        for pm in price_matches[:5]:
            num_str = re.search(r"[\d,]+(?:\.\d{2})?", pm.replace(",", ""))
            if num_str:
                num = float(num_str.group())
                if "/year" in pm.lower() or "/yr" in pm.lower():
                    num = num / 12
                onsite_prices.append(num)
                if not onsite_price_str:
                    onsite_price_str = pm

    if not onsite_prices:
        return findings  # No on-site pricing found — can't compare

    onsite_price_num = min(onsite_prices)  # Use lowest on-site price for comparison

    delta_value = abs(onsite_price_num - offsite_price_num)

    if delta_value > 0:
        # Any numeric mismatch = finding
        snippet_cite = f"Snippet: '{offsite_snippets[0][:100]}'" if offsite_snippets else ""
        findings.append({
            "id": "F-ENG-013",
            "title": f"Web-to-AI price divergence: on-site ${onsite_price_num:.0f}/mo vs off-site ${offsite_price_num:.0f}/mo",
            "severity": "critical",
            "type": "defect",
            "evidence": (
                f"On-site pricing: '{onsite_price_str}' (normalised: ${onsite_price_num:.2f}/mo). "
                f"Off-site (DuckDuckGo corroboration): '{offsite_price_str}' (normalised: ${offsite_price_num:.2f}/mo). "
                f"delta_Value = ${delta_value:.2f}/mo. {snippet_cite}. "
                "AI-referred visitors arrive expecting the off-site price; "
                "they experience an immediate credibility breakdown and exit."
            ),
            "suggested_action": {
                "summary": (
                    "Synchronise pricing across all external sources. "
                    "Add Offer JSON-LD schema with authoritative pricing to signal correct price to AI crawlers."
                ),
                "priority": "critical",
                "effort": "medium",
                "implementation_hint": (
                    "1. Add Offer JSON-LD: {\"@type\":\"Offer\",\"price\":\"" + str(onsite_price_num) + "\",\"priceCurrency\":\"USD\"}. "
                    "2. Update pricing on G2, Capterra, Crunchbase. "
                    "3. Publish a blog post with current pricing to push fresh data to search index."
                )
            },
            "check_ref": "CHECK-2.5"
        })

    return findings


# ── Check 2.6a: Boilerplate Noise Ratio ──────────────────────────────────────────

def _check_boilerplate_noise(html: str) -> list[dict]:
    """
    F-ENG-006: R_boilerplate = N_boilerplate / N_content > 2.5.
    N_boilerplate = element nodes in nav+header+footer+sidebar.
    N_content = element nodes in main+article+.content.
    """
    findings: list[dict] = []

    # Count element nodes in boilerplate regions
    boilerplate_html = ""
    for match in re.finditer(
        r"<(?:nav|header|footer)[^>]*>.*?</(?:nav|header|footer)>",
        html, re.DOTALL | re.IGNORECASE
    ):
        boilerplate_html += match.group(0)

    for match in re.finditer(
        r'<[^>]+class=["\'][^"\']*sidebar[^"\']*["\'][^>]*>.*?</[^>]+>',
        html, re.DOTALL | re.IGNORECASE
    ):
        boilerplate_html += match.group(0)

    # Count element nodes in content regions
    content_html = ""
    for match in re.finditer(
        r"<(?:main|article)[^>]*>.*?</(?:main|article)>",
        html, re.DOTALL | re.IGNORECASE
    ):
        content_html += match.group(0)

    # Fallback: look for .content, #content divs
    if not content_html:
        for match in re.finditer(
            r'<(?:div|section)[^>]+(?:class|id)=["\'][^"\']*(?:\bcontent\b)[^"\']*["\'][^>]*>.*?</(?:div|section)>',
            html, re.DOTALL | re.IGNORECASE
        ):
            content_html += match.group(0)

    n_boilerplate = len(re.findall(r"<[a-z][^/!>]*(?<!/)>", boilerplate_html, re.IGNORECASE))
    n_content = len(re.findall(r"<[a-z][^/!>]*(?<!/)>", content_html, re.IGNORECASE))

    # Both counters zero: no HTML5 landmark elements exist in the static HTML.
    # Emitting a '999x ratio' here would be factually wrong — there is no ratio
    # to compute when both numerator and denominator are zero. This happens
    # universally on CSR apps (React/Vue/Angular) where all markup is injected
    # by JavaScript. Emit a targeted PARTIAL finding and return early.
    if n_boilerplate == 0 and n_content == 0:
        findings.append({
            "id": "F-ENG-006-PARTIAL",
            "title": "Boilerplate noise ratio unmeasurable: no HTML5 semantic landmark elements in static source",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                "Element count in boilerplate regions (nav+header+footer+sidebar): 0. "
                "Element count in content regions (main+article+.content): 0. "
                "The page's static HTML contains no HTML5 semantic landmark elements. "
                "AI content extractors rely on <main>, <article>, <nav> to separate "
                "navigation chrome from substantive content. Without these landmarks "
                "the entire DOM is treated as undifferentiated text, degrading extraction quality."
            ),
            "suggested_action": {
                "summary": (
                    "Wrap primary content in <main> or <article>, navigation in <nav>, "
                    "and site-wide header/footer in <header>/<footer>."
                ),
                "priority": "medium",
                "effort": "medium",
                "implementation_hint": (
                    "Minimum landmark structure: "
                    "<header role='banner'>...</header> "
                    "<nav role='navigation'>...</nav> "
                    "<main role='main'><article>...</article></main> "
                    "<footer role='contentinfo'>...</footer>. "
                    "Validate at https://validator.w3.org/nu/ — look for 'no main landmark' warnings."
                )
            },
            "check_ref": "CHECK-2.6"
        })
        return findings

    # Content containers present — compute the actual ratio.
    if n_content == 0:
        # Boilerplate exists but no semantic content wrappers.
        r_boilerplate = float(n_boilerplate)
    else:
        r_boilerplate = n_boilerplate / n_content

    if r_boilerplate > 2.5:
        findings.append({
            "id": "F-ENG-006",
            "title": f"Boilerplate noise dominates page structure (ratio {r_boilerplate:.1f}x)",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"Boilerplate nodes (nav+header+footer+sidebar): {n_boilerplate}. "
                f"Content nodes (main+article+.content): {n_content}. "
                f"R_boilerplate = {r_boilerplate:.2f} (threshold: 2.5). "
                "Page is boilerplate-dominated. "
                "LLM extraction algorithms lose signal — genuine value content is down-weighted."
            ),
            "suggested_action": {
                "summary": (
                    "Reduce nav/footer element count or use proper HTML5 semantic structure. "
                    "Wrap main content in <main> or <article> tags."
                ),
                "priority": "medium",
                "effort": "medium",
                "implementation_hint": (
                    "1. Ensure all body content is inside <main>...</main>. "
                    "2. Reduce mega-menu complexity (flatten navigation). "
                    "3. Move footer links to a minimal sitemap. "
                    "4. Use schema.org BreadcrumbList instead of repeated navigation text."
                )
            },
            "check_ref": "CHECK-2.6"
        })

    return findings


# ── Check 2.6b: Paragraph Density ─────────────────────────────────────────────────

def _check_paragraph_density(html: str) -> list[dict]:
    """
    F-ENG-005: <p> with > 120 words AND no visual anchor within 5 DOM positions.
    """
    findings: list[dict] = []

    # Find main/article content for paragraph analysis
    content_match = re.search(
        r"<(?:main|article)[^>]*>(.*?)</(?:main|article)>",
        html, re.DOTALL | re.IGNORECASE
    )
    content_html = content_match.group(1) if content_match else html

    # Find all <p> elements
    p_pattern = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
    visual_anchor_tags = re.compile(r"<(h[3-6]|ul|ol|strong|em|blockquote|table)[^>]*>", re.IGNORECASE)

    flagged_paragraphs: list[str] = []

    for p_match in p_pattern.finditer(content_html):
        p_inner = re.sub(r"<[^>]+>", "", p_match.group(1)).strip()
        p_word_count = word_count(p_inner)

        if p_word_count <= 120:
            continue

        # Check for visual anchors within 5 DOM positions (before and after)
        p_start = p_match.start()
        p_end = p_match.end()

        # Look in 500 chars before and after for visual anchors
        before_context = content_html[max(0, p_start - 500):p_start]
        after_context = content_html[p_end:p_end + 500]
        surrounding = before_context + after_context

        has_visual_anchor = bool(visual_anchor_tags.search(surrounding))

        if not has_visual_anchor:
            flagged_paragraphs.append(p_inner[:80] + "...")

    if flagged_paragraphs:
        findings.append({
            "id": "F-ENG-005",
            "title": f"{len(flagged_paragraphs)} unbroken text wall(s) detected (>{120} words, no visual anchor)",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"{len(flagged_paragraphs)} paragraph(s) with > 120 words and no visual anchor "
                f"(h3/h4/ul/ol/strong) within 5 DOM positions. "
                f"First: '{flagged_paragraphs[0]}'. "
                "Unbroken prose walls cause human readers to exit and reduce LLM extraction quality."
            ),
            "suggested_action": {
                "summary": (
                    "Break long paragraphs into shorter chunks with sub-headings, bullet lists, or bold highlights."
                ),
                "priority": "medium",
                "effort": "medium",
                "implementation_hint": (
                    "Rule of thumb: max 3 sentences per paragraph. "
                    "Add <h3>/<h4> sub-headings every 100-150 words of body text. "
                    "Convert lists of items within prose to <ul> bullet points. "
                    "Use <strong> to highlight key facts for AI extraction."
                )
            },
            "check_ref": "CHECK-2.6"
        })

    return findings
