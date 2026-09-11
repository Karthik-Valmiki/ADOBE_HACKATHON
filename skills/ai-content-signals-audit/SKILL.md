---
name: ai-content-signals-audit
version: "1.0.0"
description: >
  Deterministic audit of AI content discoverability signals beyond robots.txt.
  Checks canonical URL correctness, hreflang reciprocal link integrity,
  XML sitemap lastmod freshness, meta description density and length,
  robots meta AI-blocking directives, and resource hint (preconnect/prefetch)
  presence for performance signalling.
license: Apache-2.0
tags: [ai-readiness, canonical, hreflang, sitemap, meta-description, ps1]
allowed_tools:
  - http_get
entry: skills/audit-orchestrator/SKILL.md
---

# AI Content Signals Audit Skill

## When to Use

Invoke this skill as the final PS1 audit step, after crawl-access and
render-parity checks. Use it when:

- You need to verify that canonical URLs are self-referential and consistent.
- You need to check hreflang tag reciprocal integrity for multilingual sites.
- You need to confirm sitemap lastmod dates reflect actual content changes.
- You need to verify meta description presence and quality.
- You need to detect `<meta name="robots" content="noai">` or similar
  AI-blocking directives that prevent content ingestion.
- You need to confirm resource hints are in place for performance.

## Inputs

| Field   | Type   | Required | Description                              |
|---------|--------|----------|------------------------------------------|
| `url`   | string | Yes      | Full URL of the page to audit            |

## Procedure

### Step 1 — Canonical URL Parity (CHECK-SIG-1)

From the HTML `<head>`:
```html
<link rel="canonical" href="...">
```

- If canonical href domain ≠ requested URL domain: emit `F-SIG-001`, severity `high`.
- If canonical href is absent: emit `F-SIG-002`, severity `medium`.
- If canonical matches current URL: emit `F-SIG-CANON-OK`, severity `low`, type `proactive`.

### Step 2 — hreflang Reciprocal Integrity (CHECK-SIG-2)

Collect all `<link rel="alternate" hreflang="..." href="...">` tags.

For each hreflang target URL:
1. Fetch that URL (HEAD request, timeout 5s).
2. Confirm it has a reciprocal `hreflang` pointing back to the original URL.
3. If reciprocal is missing: emit `F-SIG-003`, severity `medium` per missing link.

Maximum: check first 5 hreflang targets to stay within runtime budget.

### Step 3 — Sitemap lastmod Freshness (CHECK-SIG-3)

Fetch XML sitemap (from robots.txt `Sitemap:` directive).
Parse all `<lastmod>` values. Compute:

```
freshness_ratio = count(entries with lastmod within 90 days) / count(total entries)
```

- `freshness_ratio < 0.30` and sitemap has >10 entries: emit `F-SIG-004`,
  severity `medium` (stale sitemap).
- Sitemap absent (no `Sitemap:` in robots.txt): emit `F-SIG-005`, severity `high`.

### Step 4 — Meta Description Quality (CHECK-SIG-4)

Read `<meta name="description" content="...">`.

- Absent: emit `F-SIG-006`, severity `high`.
- Length < 50 chars: emit `F-SIG-007`, severity `medium` (too short for AI summary).
- Length > 160 chars: emit `F-SIG-008`, severity `low` (truncated in SERPs/AI snippets).
- 50–160 chars: emit `F-SIG-META-OK`, severity `low`, type `proactive`.

### Step 5 — Robots Meta AI-Blocking (CHECK-SIG-5)

Check for `<meta name="robots" content="...">`.

If content contains any of:
- `noai`, `noimageai`, `noimageindex`, `nosnippet`, `noarchive`

Then:
- `noai` or `noimageai` present: emit `F-SIG-009`, severity `critical`
  (explicitly blocks AI content ingestion).
- `nosnippet`: emit `F-SIG-010`, severity `high` (prevents AI snippet extraction).
- `noarchive`: emit `F-SIG-011`, severity `low` (informational).

### Step 6 — Resource Hints (CHECK-SIG-6)

Check `<head>` for:
- `<link rel="preconnect">` — critical third-party origins preconnected.
- `<link rel="dns-prefetch">` — DNS prefetch hints.
- `<link rel="preload">` — LCP asset preloaded.

If none of the above are present:
- Emit `F-SIG-012`, severity `low` (missing resource hints slow AI crawler perception of TTFB).

## Output

Standard findings array. All findings MUST include `id`, `title`, `severity`,
`type`, `evidence`, `suggested_action`, and `check_ref`. The `findings` array
MUST NEVER be empty.
