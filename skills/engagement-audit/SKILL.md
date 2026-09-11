---
name: engagement-audit
version: "1.0.0"
description: >
  Deterministic on-site AI engagement audit.
  Checks intent mismatch, hidden hash anchors, CTA placement, intrusive overlay
  detection, web-to-AI price divergence, and boilerplate noise ratio. Consumes
  the cross-web corroboration contract from corroboration-freshness-audit.
license: Apache-2.0
tags: [ai-readiness, engagement, cta, overlay, pricing, boilerplate]
allowed_tools:
  - http_get
entry: skills/audit-orchestrator/SKILL.md
---

# Engagement Audit Skill

## When to Use

Invoke this skill when the task is to evaluate how effectively an AI
agent can read, navigate, and act on a website. Use it when:

- You need to detect intent mismatch between page title and hero section.
- You need to find URL hash anchors that AI assistants link to but which are
  collapsed or hidden in the rendered DOM.
- You need to check whether a clear call-to-action exists before the hero boundary.
- You need to detect full-screen overlays that intercept a visitor's first interaction.
- You need to cross-check on-site price claims against off-site corroboration data.
- You need to measure boilerplate noise relative to substantive content.

## Inputs

| Field                      | Type   | Required | Description                                               |
|----------------------------|--------|----------|-----------------------------------------------------------|
| `url`                      | string | Yes      | Full URL of the page to audit                             |
| `hydrated_html`            | string | No       | Pre-fetched hydrated HTML from jsdom runner (preferred)   |
| `cross_web_corroboration`  | dict   | No       | Output contract from corroboration-freshness-audit        |

## Procedure

### Check 2.1 — Intent Mismatch (CHECK-2.1)

Extract page title token set `T_ref` from `<title>`.
Extract hero token set `T_hero` from `<h1>`, `<h2>`, and hero-class containers.

```
delta_Intent = |T_ref ∩ T_hero| / |T_ref|
```

- `delta_Intent < 0.30`: emit `F-ENG-004`, severity `high`.
  Evidence must include the page title, the hero text sample, and the computed score.

### Check 2.2 — Hidden URL Hash Anchor (CHECK-2.2)

Scan all `<a href="#...">` elements in the DOM.
For each hash anchor, check the referenced element for collapsed state:
`display:none`, `visibility:hidden`, `height:0`, `aria-expanded="false"`,
`class` containing `collapse|hidden|d-none|folded`.

- If any referenced element is collapsed: emit `F-ENG-003`, severity `critical`.
  Evidence must name the exact hash ID and the collapsed CSS/attribute evidence.

### Check 2.3 — CTA Before Hero Boundary (CHECK-2.3)

Scan for CTA elements (`<button>`, `<a class="btn|cta">`, `<input type="submit">`)
that appear BEFORE the first `class/id` matching `hero|banner|jumbotron|intro|landing`.

- If no CTA found before the hero boundary: emit `F-ENG-007`, severity `high`.

### Check 2.4 — Full-Screen Overlay (CHECK-2.4)

Detect elements that match ALL of:
- `class` or `id` contains: `modal|overlay|popup|lightbox|cookie|consent|gate|paywall`
- `position: fixed` or `position: absolute`
- `z-index > 100`
- `width: 100%|100vw` AND `height: 100%|100vh`
- Contains a dismiss control (`<button>` or `aria-label="close"`)

- If present at page load (no scroll trigger): emit `F-ENG-009`, severity `critical`.
- If present only after scroll trigger signals: emit `F-ENG-010`, severity `critical`.

### Check 2.5 — Web-to-AI Price Divergence (CHECK-2.5)

If `cross_web_corroboration` contains a numeric `offsite_price_num`:
1. Extract on-site pricing from JSON-LD Offer schema or regex price pattern.
2. Normalise both to monthly USD.
3. Compute `delta_Value = |onsite_price - offsite_price|`.
4. Any numeric mismatch: emit `F-ENG-013`, severity `critical`.

If corroboration status is `rate_limited` or `blocked`, or no off-site price was
captured: emit `F-ENG-013-UNVERIFIED`, severity `medium`.

### Check 2.6 — Boilerplate Noise & Paragraph Density (CHECK-2.6)

**Boilerplate noise ratio:**
- Extract text from `<nav>`, `<header>`, `<footer>` → `W_boilerplate`
- Extract text from `<main>`, `<article>` → `W_content`
- `R_noise = W_boilerplate / max(W_content, 1)`
- If `R_noise > 2.5`: emit `F-ENG-006`, severity `medium`.

**Paragraph density:**
- Find all `<p>` blocks with word count > 120 and no intervening `<h*>`, `<img>`, `<ul>`.
- If any found: emit `F-ENG-005`, severity `medium`, with paragraph character count as evidence.

## Output

Standard findings array. All findings MUST include `id`, `title`, `severity`,
`type`, `evidence`, `suggested_action`, and `check_ref`. The `findings` array
MUST NEVER be empty — emit at least one proactive finding if all checks pass.
