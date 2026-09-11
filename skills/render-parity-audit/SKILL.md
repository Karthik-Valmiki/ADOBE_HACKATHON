---
name: render-parity-audit
version: "1.0.0"
description: >
  Deterministic audit of SSR vs CSR render parity using Node.js + jsdom.
  Measures the hydration gap delta_H, detects visual data traps (unlabelled
  media with high declared attribute area), and identifies semantic noise from
  excessive DOM depth.
license: Apache-2.0
tags: [ai-readiness, render-parity, ssr, csr, jsdom, ps1]
allowed_tools:
  - http_get
  - subprocess
entry: skills/audit-orchestrator/SKILL.md
---

# Render Parity Audit Skill

## When to Use

Invoke this skill when the agent task is to determine whether an AI crawler
receives the same content a human browser sees. Use it when:

- The site is suspected to use React/Vue/Angular without SSR.
- You need to quantify the content gap between static HTML and JS-rendered DOM.
- You need to detect media elements that lock data away from text extractors.
- You need to verify value-proposition content is not buried in deep DOM nesting.

## Runtime Requirements

- **Python**: httpx ≥0.27.0
- **Node.js**: ≥18 LTS (for jsdom_runner.js)
- **npm package**: jsdom (installed in `skills/audit-orchestrator/scripts/`)
- Install: `cd skills/audit-orchestrator/scripts && npm install`

## Inputs

| Field   | Type   | Required | Description                              |
|---------|--------|----------|------------------------------------------|
| `url`   | string | Yes      | Full URL of the page to audit            |

## Procedure

Execute in strict order.

### Step 1 — Fetch static HTML (CHECK-1.5 baseline)

```
GET {url}
Headers: User-Agent: Mozilla/5.0 ...
```

Count words in semantic containers (`<p>`, `<h1>`–`<h6>`, `<article>`, `<main>`).
Record as `w_static`.

### Step 2 — JS Hydration via Node.js + jsdom

Pipe the static HTML to `jsdom_runner.js` via stdin:

```sh
node skills/audit-orchestrator/scripts/jsdom_runner.js {url} < static.html
```

The runner:
1. Parses HTML in jsdom (no Chromium).
2. Executes all inline `<script>` tags with network requests blocked.
3. Returns JSON on stdout: `{hydrated_html, word_count, json_ld_blocks, meta_tags, links}`.

Record returned `word_count` as `w_hydrated`.

### Step 3 — Compute delta_H (CHECK-1.5)

```
delta_H = w_static / w_hydrated
```

- `delta_H < 0.15` → emit `F-DOM-001`, severity `critical` (CSR content gap).
- `delta_H >= 0.85` → emit `F-DOM-SSR-OK`, severity `low`, type `proactive`.
- `0.15 <= delta_H < 0.85` → intermediate gap; no finding (informational only).

### Step 4 — Visual Data Trap Detection (CHECK-1.6)

Scan the hydrated HTML for `<canvas>`, `<img>`, `<svg>`, `<video>` within
`<main>` or `<article>` containers.

For each element without `alt`, `aria-label`, or `aria-describedby`:

1. Read `width` and `height` HTML attributes (not CSS — attribute scan only).
2. Compute `area = width × height`.
3. Sum to `A_total_unlabelled`.

Compute `text_density = len(text_in_container) / A_total_unlabelled`.

- If `A_total_unlabelled > 200,000` AND `text_density < 0.20`:
  - Emit `F-DOM-002`, severity `critical`.

**HARD CONSTRAINT**: Never use CSS-computed pixel geometry. HTML attributes only.

### Step 5 — Semantic Noise Floor (CHECK-1.7)

Find all `<h1>`, `<h2>` and elements with class/id containing
`hero|value-prop|headline|jumbotron|banner`.

For each candidate, count ancestor opening tags minus closing tags before its
position in the HTML string. This gives DOM depth estimate `d`.

- If `d > 10` for any top-scoring (TF-IDF overlap with page title) candidate:
  - Emit `F-DOM-005`, severity `medium`.

## Output

Standard findings array. The `hydrated_dom_ast` field is passed downstream to
the entity and engagement audit skills.

Each finding MUST include `id`, `title`, `severity`, `type`, `evidence`,
`suggested_action` (with `summary`, `priority`, `effort`, `implementation_hint`),
and `check_ref`.
