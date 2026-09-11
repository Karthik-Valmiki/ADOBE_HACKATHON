#!/usr/bin/env python3
"""
render_parity.py — Client-Side Rendering Parity Audit
Checks: CSR hydration gap, visual data trap detector, semantic noise floor.

Finding IDs produced:
  F-DOM-001  CSR hydration gap delta_H < 0.15 (Critical)
  F-DOM-002  Visual data trap (unlabelled media, high area, low text density) (Critical)
  F-DOM-005  Semantic noise floor / DOM depth > 10 (Medium)

JS Hydration Engine:
  Node.js + jsdom.
  Called via asyncio.create_subprocess_exec — reads static HTML from stdin,
  returns a JSON payload with hydrated_html + word_count + JSON-LD blocks.

Hard constraints:
  - No Chromium / Playwright / Selenium
  - No pixel geometry — area from HTML width/height attributes only
  - No CSS layout engine
  - External network blocked inside jsdom_runner.js
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import httpx

from .utils import (
    BROWSER_UA, extract_semantic_text, extract_text_from_html,
    get_dom_depth, make_client, tokenize, word_count,
)

# ── Node.js runner path ───────────────────────────────────────────────────────
_SCRIPTS_DIR = Path(__file__).parent.parent          # …/scripts/
_RUNNER_PATH = _SCRIPTS_DIR / "jsdom_runner.js"      # …/scripts/jsdom_runner.js


def _find_node() -> str | None:
    """Return absolute path to node binary, or None if not on PATH."""
    return shutil.which("node")


# ─────────────────────────────────────────────────────────────────────────────
# Public entry-point
# ─────────────────────────────────────────────────────────────────────────────

async def run_render_parity_audit(url: str) -> dict[str, Any]:
    """
    Runs all client-side rendering parity checks.
    Returns findings + hydrated_dom_ast (raw hydrated HTML string).
    """
    findings: list[dict] = []

    # ── Fetch static HTML ────────────────────────────────────────────────────
    static_html = ""
    try:
        async with make_client(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": BROWSER_UA})
            static_html = resp.text
    except Exception as exc:
        return {
            "findings": [{
                "id": "F-DOM-FETCH-ERR",
                "title": "Failed to fetch page HTML",
                "severity": "high",
                "type": "defect",
                "evidence": f"HTTP fetch error: {type(exc).__name__}: {exc}",
                "suggested_action": {
                    "summary": "Verify site is publicly accessible.",
                    "priority": "high", "effort": "low",
                    "implementation_hint": "Check DNS resolution and server availability."
                },
                "check_ref": "CHECK-1.5"
            }],
            "hydrated_dom_ast": None,
            "js_engine_available": False,
        }

    # Static word count (baseline)
    static_text = extract_semantic_text(static_html)
    w_static = word_count(static_text)

    # ── JS Hydration via Node.js + jsdom ────────────────────────────────────
    hydrated_html = static_html   # fallback
    js_engine_available = False
    w_hydrated = w_static
    jsdom_payload: dict = {}

    node_path = _find_node()
    if not node_path:
        findings.append({
            "id": "F-DOM-NODE-MISSING",
            "title": "Node.js not found — JS hydration skipped",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                "node binary not found on PATH. "
                "jsdom_runner.js requires Node.js ≥18. "
                "Install from https://nodejs.org/ and re-run the audit."
            ),
            "suggested_action": {
                "summary": "Install Node.js ≥18 to enable full JS hydration parity check.",
                "priority": "medium", "effort": "low",
                "implementation_hint": "winget install OpenJS.NodeJS.LTS"
            },
            "check_ref": "CHECK-1.5"
        })
    elif not _RUNNER_PATH.exists():
        findings.append({
            "id": "F-DOM-RUNNER-MISSING",
            "title": "jsdom_runner.js not found — JS hydration skipped",
            "severity": "medium",
            "type": "defect",
            "evidence": f"Expected runner at: {_RUNNER_PATH}",
            "suggested_action": {
                "summary": "Restore jsdom_runner.js to the scripts/ directory.",
                "priority": "medium", "effort": "low",
                "implementation_hint": "Run: cd skills/audit-orchestrator/scripts && npm install"
            },
            "check_ref": "CHECK-1.5"
        })
    else:
        try:
            hydrated_html, w_hydrated, js_engine_available, jsdom_payload = (
                await _run_jsdom_hydration(url, static_html, node_path)
            )
        except Exception as exc:
            # Non-fatal — fall back to static HTML, note in findings
            findings.append({
                "id": "F-DOM-JSDOM-ERR",
                "title": "JS hydration failed — falling back to static HTML",
                "severity": "low",
                "type": "proactive",
                "evidence": f"jsdom_runner error: {type(exc).__name__}: {exc}",
                "suggested_action": {
                    "summary": "JS hydration encountered an error. Results may undercount CSR content.",
                    "priority": "low", "effort": "low",
                    "implementation_hint": "Check Node.js version (≥18) and run: npm install inside scripts/"
                },
                "check_ref": "CHECK-1.5"
            })

    # ── Check 1.5: CSR Hydration Gap ────────────────────────────────────────
    if w_hydrated > 0:
        delta_h = w_static / w_hydrated
    else:
        delta_h = 0.0

    if delta_h < 0.15:
        pct_invisible = (1 - delta_h) * 100
        findings.append({
            "id": "F-DOM-001",
            "title": "Critical CSR hydration gap: most content invisible to basic AI crawlers",
            "severity": "critical",
            "type": "defect",
            "evidence": (
                f"Static HTML word count: {w_static}. "
                f"Hydrated DOM word count (jsdom): {w_hydrated}. "
                f"delta_H = {delta_h:.3f} ({delta_h*100:.1f}% — {pct_invisible:.1f}% content invisible to non-JS crawlers). "
                "Indicates React/Vue/Angular CSR without SSR. "
                "AI crawlers skipping JS execution see a near-empty page."
            ),
            "suggested_action": {
                "summary": (
                    "Implement Server-Side Rendering (SSR) or Static Site Generation (SSG). "
                    "For React: use Next.js getServerSideProps/getStaticProps. "
                    "For Vue: use Nuxt.js SSR mode. For Angular: use Angular Universal."
                ),
                "priority": "critical",
                "effort": "high",
                "implementation_hint": (
                    "Quick win: enable pre-rendering for key pages (home, pricing, about). "
                    "Use Vercel/Netlify static export. "
                    "Validate with: curl -A 'GPTBot/1.1' <url> | wc -w"
                )
            },
            "check_ref": "CHECK-1.5"
        })
    elif delta_h >= 0.85:
        findings.append({
            "id": "F-DOM-SSR-OK",
            "title": "Excellent SSR coverage: content fully visible to AI crawlers",
            "severity": "low",
            "type": "proactive",
            "evidence": (
                f"Static HTML word count: {w_static}. "
                f"Hydrated DOM word count (jsdom): {w_hydrated}. "
                f"delta_H = {delta_h:.3f} ({delta_h*100:.1f}% content in static HTML). "
                "Content is fully accessible to non-JS AI crawlers."
            ),
            "suggested_action": {
                "summary": "Excellent SSR coverage. Maintain server-side rendering on all key pages.",
                "priority": "low", "effort": "low",
                "implementation_hint": "Ensure new features / marketing pages also use SSR, not CSR-only."
            },
            "check_ref": "CHECK-1.5"
        })

    # ── Check 1.6: Visual Data Trap Detector ────────────────────────────────
    vdt_findings = _check_visual_data_trap(hydrated_html)
    findings.extend(vdt_findings)

    # ── Check 1.7: Semantic Noise Floor ─────────────────────────────────────
    snf_findings = _check_semantic_noise_floor(hydrated_html)
    findings.extend(snf_findings)

    return {
        "findings": findings,
        "hydrated_dom_ast": hydrated_html,
        "js_engine_available": js_engine_available,
        "delta_h": delta_h,
        "w_static": w_static,
        "w_hydrated": w_hydrated,
        # Pass jsdom-extracted data to downstream checks
        "jsdom_json_ld_blocks": jsdom_payload.get("json_ld_blocks", []),
        "jsdom_meta_tags": jsdom_payload.get("meta_tags", {}),
        "jsdom_links": jsdom_payload.get("links", []),
        "jsdom_title": jsdom_payload.get("title", ""),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Node.js + jsdom subprocess runner
# ─────────────────────────────────────────────────────────────────────────────

async def _run_jsdom_hydration(
    url: str,
    static_html: str,
    node_path: str,
    timeout: float = 20.0,
) -> tuple[str, int, bool, dict]:
    """
    Pipes static_html to jsdom_runner.js via stdin.
    Returns (hydrated_html, word_count, js_engine_available=True, payload_dict).

    The runner:
    - Parses the HTML in jsdom
    - Executes inline <script> tags (no external fetches)
    - Returns JSON on stdout with hydrated_html, word_count, json_ld_blocks, etc.
    """
    html_bytes = static_html.encode("utf-8", errors="replace")

    proc = await asyncio.create_subprocess_exec(
        node_path,
        str(_RUNNER_PATH),
        url,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # Ensure we don't inherit the parent's console environment issues
        env={**os.environ, "NODE_NO_WARNINGS": "1"},
    )

    try:
        stdout_data, stderr_data = await asyncio.wait_for(
            proc.communicate(input=html_bytes),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        raise RuntimeError(f"jsdom_runner.js timed out after {timeout}s")

    raw_stdout = stdout_data.decode("utf-8", errors="replace").strip()

    if not raw_stdout:
        # Node ran but produced no output
        stderr_text = stderr_data.decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"jsdom_runner.js produced no stdout. stderr: {stderr_text}")

    try:
        payload = json.loads(raw_stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"jsdom_runner.js returned non-JSON output: {raw_stdout[:200]}")

    if payload.get("error"):
        raise RuntimeError(f"jsdom_runner.js reported error: {payload['error']}")

    hydrated_html = payload.get("hydrated_html") or static_html
    w_hydrated = payload.get("word_count", 0)
    if w_hydrated == 0:
        # Fall back to our own counter on the returned HTML
        hydrated_text = extract_semantic_text(hydrated_html)
        w_hydrated = word_count(hydrated_text)

    return hydrated_html, w_hydrated, True, payload


# ─────────────────────────────────────────────────────────────────────────────
# Check 1.6: Visual Data Trap Detector
# ─────────────────────────────────────────────────────────────────────────────

def _check_visual_data_trap(html: str) -> list[dict]:
    """
    F-DOM-002: Unlabelled canvas/img/svg/video with high declared attribute area
    and low text density in main/article containers.

    CONSTRAINT: Uses HTML width/height ATTRIBUTES only — not rendered/CSS pixels.
    """
    findings: list[dict] = []

    # Extract main/article content region
    main_match = re.search(
        r"<(?:main|article)[^>]*>(.*?)</(?:main|article)>",
        html, re.DOTALL | re.IGNORECASE
    )
    content_html = main_match.group(1) if main_match else html

    # Find all media elements within content
    media_pattern = re.compile(
        r"<(canvas|img|svg|video)([^>]*)(?:>(.*?)</\1>|/)>",
        re.DOTALL | re.IGNORECASE
    )

    a_total_unlabelled = 0
    unlabelled_elements: list[dict] = []

    for m in media_pattern.finditer(content_html):
        tag = m.group(1).lower()
        attrs_str = m.group(2)
        inner = m.group(3) or ""

        # Check for alt / aria-label / aria-describedby
        has_alt = bool(re.search(r'\balt=["\'][^"\']{1,}["\']', attrs_str, re.IGNORECASE))
        has_aria_label = bool(re.search(r'\baria-label=["\'][^"\']{1,}["\']', attrs_str, re.IGNORECASE))
        has_aria_desc = bool(re.search(r'\baria-describedby=["\'][^"\']{1,}["\']', attrs_str, re.IGNORECASE))
        has_title = bool(re.search(r'<title>[^<]{1,}</title>', inner, re.IGNORECASE))  # For SVG

        is_labelled = has_alt or has_aria_label or has_aria_desc or has_title

        if not is_labelled:
            # Read width/height from HTML attributes only
            width_match = re.search(r'\bwidth=["\']?(\d+)["\']?', attrs_str, re.IGNORECASE)
            height_match = re.search(r'\bheight=["\']?(\d+)["\']?', attrs_str, re.IGNORECASE)
            width = int(width_match.group(1)) if width_match else 300
            height = int(height_match.group(1)) if height_match else 200
            area = width * height
            a_total_unlabelled += area
            unlabelled_elements.append({
                "tag": tag, "width": width, "height": height, "area": area
            })

    # Count text chars in content area
    content_text = extract_text_from_html(content_html)
    c_text = len(content_text)

    if a_total_unlabelled > 0:
        text_density = c_text / a_total_unlabelled
    else:
        text_density = 999.0

    # Rule trigger: unlabelled area > 200k, text density < 0.20, at least 1 element
    if a_total_unlabelled > 200_000 and text_density < 0.20 and unlabelled_elements:
        elem_summary = ", ".join(
            f"<{e['tag']} {e['width']}×{e['height']} ({e['area']:,}px²)>"
            for e in unlabelled_elements[:3]
        )
        findings.append({
            "id": "F-DOM-002",
            "title": "Visual data trap: key content locked in unlabelled media elements",
            "severity": "critical",
            "type": "defect",
            "evidence": (
                f"Primary content area: {len(unlabelled_elements)} unlabelled "
                f"canvas/img/svg element(s). "
                f"Declared attribute area: {a_total_unlabelled:,} px². "
                f"Text characters: {c_text} (Text_Density = {text_density:.5f} < 0.20 threshold). "
                f"Elements: {elem_summary}. "
                "Specs/pricing locked in non-text format are invisible to AI extraction."
            ),
            "suggested_action": {
                "summary": (
                    "Add descriptive alt text or aria-label to all informational media. "
                    "Convert data visualisations (pricing tables, spec charts) to HTML text + CSS."
                ),
                "priority": "critical",
                "effort": "medium",
                "implementation_hint": (
                    "For <img>: add alt='[specific description of content]'. "
                    "For <canvas>/<svg> charts: add aria-label='[data summary]' AND "
                    "a hidden <table> sibling with the same data. "
                    "For pricing tables: use HTML <table> instead of images."
                )
            },
            "check_ref": "CHECK-1.6"
        })

    return findings


# ─────────────────────────────────────────────────────────────────────────────
# Check 1.7: Semantic Noise Floor
# ─────────────────────────────────────────────────────────────────────────────

def _check_semantic_noise_floor(html: str) -> list[dict]:
    """
    F-DOM-005: Value proposition nodes buried at DOM depth > 10.
    Algorithm: find h1/h2 + hero/value-prop/headline elements,
    score TF-IDF, find top candidates, measure ancestor depth.
    """
    findings: list[dict] = []

    # Extract page title for TF-IDF scoring
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    page_title = title_match.group(1).strip() if title_match else ""
    title_tokens = tokenize(page_title)

    # Find candidate "value proposition" elements
    candidates: list[dict] = []

    # Pattern 1: h1/h2 headings
    for h_match in re.finditer(r"<(h[12])[^>]*>(.*?)</\1>", html, re.IGNORECASE | re.DOTALL):
        tag = h_match.group(1)
        text = re.sub(r"<[^>]+>", "", h_match.group(2)).strip()
        if len(text) > 3:
            text_tokens = tokenize(text)
            overlap = len(title_tokens & text_tokens) / max(len(title_tokens), 1)
            candidates.append({
                "tag": tag,
                "text": text[:60],
                "position": h_match.start(),
                "overlap": overlap,
                "source": "heading",
            })

    # Pattern 2: hero/value-prop/headline class elements
    for class_match in re.finditer(
        r'<[^>]+(?:class|id)=["\'][^"\']*(?:hero|value-prop|headline|jumbotron|banner)[^"\']*["\'][^>]*>(.*?)</[^>]+>',
        html, re.IGNORECASE | re.DOTALL
    ):
        text = re.sub(r"<[^>]+>", "", class_match.group(1)).strip()
        if len(text) > 3:
            candidates.append({
                "tag": "div.hero",
                "text": text[:60],
                "position": class_match.start(),
                "overlap": 0.5,
                "source": "hero-class",
            })

    if not candidates:
        return findings

    candidates.sort(key=lambda c: c["overlap"], reverse=True)
    top_candidates = candidates[:3]

    d_max = 0
    deepest_candidate: dict = {}

    for cand in top_candidates:
        prefix = html[:cand["position"]]
        opens = len(re.findall(r"<[a-z][a-z0-9]*(?:\s[^>]*)?>", prefix, re.IGNORECASE))
        closes = len(re.findall(r"</[a-z][a-z0-9]*>", prefix, re.IGNORECASE))
        depth = max(0, opens - closes)

        if depth > d_max:
            d_max = depth
            deepest_candidate = cand

    if d_max > 10:
        findings.append({
            "id": "F-DOM-005",
            "title": f"Semantic noise floor: value proposition at excessive DOM depth {d_max}",
            "severity": "medium",
            "type": "defect",
            "evidence": (
                f"Primary value proposition "
                f"('{deepest_candidate.get('text', '')}', <{deepest_candidate.get('tag', '')}>)"
                f" at DOM depth {d_max} from <html>. "
                f"Exceeds max depth 10. "
                "Buried inside nested <div> boilerplate — "
                "LLM chunking algorithms lose signal and down-weight the content."
            ),
            "suggested_action": {
                "summary": (
                    "Flatten DOM structure. Move key headings and value propositions to "
                    "shallower nesting (depth ≤ 6 ideal). Use semantic HTML5 elements."
                ),
                "priority": "medium",
                "effort": "medium",
                "implementation_hint": (
                    "Replace deeply-nested <div><div><div>...<h1> patterns with "
                    "direct <main><h1> or <section><h1>. "
                    "Use CSS Grid/Flexbox for layout instead of nested <div> wrappers. "
                    "Test DOM depth with: document.querySelector('h1').depth"
                )
            },
            "check_ref": "CHECK-1.7"
        })

    return findings
