---
name: audit-orchestrator
version: "2.0.0"
description: >
  Entrypoint skill. Given a target URL, composes all specialist audit skills in
  dependency order, enforces the cross-web corroboration contract, merges all findings,
  and emits a single structured audit report (JSON + HTML). Deterministic,
  evidence-backed, no headless browser, no model weights.
license: MIT
allowed_tools:
  - http_fetch_async
  - js_runtime_node_jsdom
inputs:
  - name: url
    type: string
    required: true
    description: "Fully-qualified URL to audit (e.g. https://target.com)"
  - name: output_format
    type: string
    required: false
    default: "json"
    description: "Output format: json | html | both"
outputs:
  - name: audit_report
    type: object
    schema: "references/audit_report_schema.json"
---

# Brand AI-Readiness Audit — Orchestrator

## When to Use
When diagnosing why a brand is invisible or misrepresented in AI assistants (ChatGPT, Claude,
Perplexity, Google AI Overview), or why visitors who arrive via AI referral don't engage.

## Inputs
- **url** (required): The target website URL (homepage or specific page).
- **output_format** (optional, default: `json`): `json`, `html`, or `both`.

## Execution Protocol

The orchestrator runs skills in strict dependency order. **Do not reorder.**
All HTTP calls use `httpx` async with explicit timeouts. No Chromium. No pixel geometry.

### Step 0 — Normalise & Validate Input
1. Parse URL. Validate scheme (must be http or https). Extract `root_url` (scheme + hostname).
2. If URL is invalid, emit `F-INPUT-001` (Critical) and halt.

### Step 1 — Independent Parallel Checks (no cross-dependencies)
Run ALL of the following **concurrently** (asyncio.gather):
- **crawl-access-audit** → robots.txt (F-NET-001), multi-UA WAF (F-NET-002/003), redirects (F-NET-004), llms.txt (F-LLMS-001)
- **entity-structured-data-audit** → JSON-LD entity (F-ENTITY-001), Schema.org signals (F-SCHEMA-*)
- **ai-content-signals-audit** → Open Graph, Twitter Card, Canonical, Sitemap, hreflang (F-SIGNAL-*)

### Step 2 — DOM Hydration (critical path gate)
Run **render-parity-audit**:
- Produces: hydrated DOM AST, W_static, W_hydrated, delta_H
- If Node.js/jsdom runtime fails: log warning, continue with static DOM only. Mark all DOM-dependent checks as PARTIAL.
- Outputs: F-DOM-001, F-DOM-002, F-DOM-005

### Step 3 — Cross-Web Corroboration (depends on Step 1 entity output)
Run **corroboration-freshness-audit** with `brand_name` from Step 1 entity check:
- Wikidata entity lookup (F-ENTITY-002 / F-ENTITY-003 / F-ENTITY-UNVERIFIED)
- DuckDuckGo Lite freshness delta (F-FRESH-001 / F-FRESH-UNVERIFIED)
- Emits **Cross-Web Output Contract** (consumed by Step 4)

### Step 4 — Engagement Checks (depends on Step 2 DOM + Step 3 contract)
Run **engagement-audit** with hydrated DOM AST + cross-web corroboration contract:
- Intent mismatch (F-ENG-004)
- Hidden hash anchor (F-ENG-003)
- CTA above-hero boundary (F-ENG-007)
- Full-screen overlay load/scroll (F-ENG-009 / F-ENG-010)
- Web-to-AI price divergence (F-ENG-013 / F-ENG-013-UNVERIFIED)
- Boilerplate noise + paragraph density (F-ENG-006 / F-ENG-005)

### Step 5 — Proactive Findings
After all checks complete:
- If site passes all crawl-access/discoverability checks → emit F-DISC-OK (type: proactive)
- If site passes all engagement checks → emit F-ENG-OK (type: proactive)
- If findings array is empty → emit F-DISC-OK with full passing evidence (mandatory: findings NEVER empty)

### Step 6 — Report Serialisation
Pass all findings to **report-serializer**:
- Validate each finding against schema (id, title, severity, evidence, suggested_action)
- Sort: critical → high → medium → low → proactive
- Compute summary counts
- Emit JSON report (and HTML dashboard if requested)

## Output Schema
```json
{
  "site": "string",
  "audited_at": "ISO8601",
  "audit_version": "2.0.0",
  "summary": {
    "total_findings": "int",
    "critical": "int",
    "high": "int",
    "medium": "int",
    "low": "int",
    "proactive": "int"
  },
  "findings": [
    {
      "id": "string",
      "title": "string",
      "severity": "critical|high|medium|low",
      "type": "defect|proactive",
      "evidence": "string",
      "suggested_action": {
        "summary": "string",
        "priority": "critical|high|medium|low",
        "effort": "low|medium|high",
        "implementation_hint": "string"
      },
      "check_ref": "string"
    }
  ],
  "cross_web_corroboration": { },
  "runtime_meta": {
    "elapsed_seconds": "float",
    "js_engine_available": "bool",
    "checks_partial": ["string"]
  }
}
```

## Error Handling Protocol
- **Never crash, never silently pass.**
- Network timeout on any check → emit explicit UNVERIFIED finding for that check.
- JS engine boot failure → continue with static DOM, mark affected checks as PARTIAL.
- Empty findings array is NEVER acceptable → always emit at least one proactive finding.

## Hard Constraints Compliance
| Constraint | Compliance |
|---|---|
| HTTP client | httpx async only |
| JS execution | Node.js + jsdom (no Chromium, no headless browser) |
| Pixel geometry | FORBIDDEN — zero pixel checks |
| Chromium/headless | FORBIDDEN — not used |
| Submission size | No model weights bundled |
| Runtime | < 5 min enforced via asyncio.timeout |
| Findings array | Never empty — guaranteed by Step 5 |
