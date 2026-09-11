# Brand AI Readiness Audit

> **Adobe University Hackathon — Agent Skill Marketplace**
> Solves Problem Statement 1 (Off-Site AI Discoverability) and Problem Statement 2 (On-Site AI Engagement).

---

## What This Does

This marketplace audits any public website to determine:
1. **Can AI agents find and index the brand?** — Crawl access, entity data, rendering, and corroboration checks.
2. **Can AI agents act on the brand's website?** — On-site engagement: intent, CTA, overlays, price divergence, boilerplate.

The output is a structured JSON report with an **AI Readiness Score (0–100)**, severity-ranked findings, and specific implementation hints — fully deterministic, zero hallucination, zero Chromium.

---

## Architecture

```
brand-ai-readiness-audit/
├── marketplace.json                  ← agentskills.io manifest
├── requirements.txt                  ← Python: httpx only
├── run_audit.py                      ← Convenience CLI wrapper
└── skills/
    ├── audit-orchestrator/           ← Entrypoint: 6-step pipeline
    │   ├── SKILL.md                  ← Main skill instructions
    │   ├── references/
    │   │   ├── audit_report_schema.json   ← JSON Schema v7 for output
    │   │   └── check_specifications.md    ← All algorithms and thresholds
    │   └── scripts/
    │       ├── audit_orchestrator.py ← Main pipeline runner
    │       ├── jsdom_runner.js       ← Node.js + jsdom hydration engine
    │       ├── package.json          ← npm: jsdom dependency
    │       └── checks/
    │           ├── utils.py               ← Shared utilities, WAF detection
    │           ├── crawl_access.py        ← CHECK-1.1 to 1.4 (Crawl Access)
    │           ├── render_parity.py       ← CHECK-1.5 to 1.7 (Rendering Parity)
    │           ├── entity_structured_data.py ← CHECK-1.8 (Entity & Structured Data)
    │           ├── corroboration_freshness.py ← CHECK-1.9, 1.10 (Cross-Web Corroboration)
    │           ├── engagement.py          ← CHECK-2.1 to 2.6 (On-Site Engagement)
    │           ├── ai_content_signals.py  ← CHECK-SIG-1 to 6 (Content Signals)
    │           └── report_serializer.py   ← Score, dedup, schema validation
    ├── crawl-access-audit/SKILL.md
    ├── render-parity-audit/SKILL.md
    ├── entity-structured-data-audit/SKILL.md
    ├── corroboration-freshness-audit/SKILL.md
    ├── engagement-audit/SKILL.md
    ├── ai-content-signals-audit/SKILL.md
    └── report-serializer/SKILL.md
```

---

## Installation

### Prerequisites

- **Python 3.11+**
- **Node.js 18+ LTS** — required for JS hydration (jsdom)
- **pip** and **npm**

### Setup

```bash
# 1. Python dependencies
pip install -r requirements.txt

# 2. Node.js dependencies (jsdom runner)
cd skills/audit-orchestrator/scripts
npm install
cd ../../..
```

---

## Running an Audit

### Quick Run (convenience script)

```bash
python run_audit.py https://example.com
```

### With format options

```bash
# JSON output (default)
python run_audit.py https://example.com

# Markdown summary
python run_audit.py https://example.com --format markdown

# Save JSON to file
python run_audit.py https://example.com --output report.json
```

### Direct module run

```bash
cd skills/audit-orchestrator/scripts
python audit_orchestrator.py https://example.com
```

---

## Output Format

```json
{
  "schema_version": "2.0.0",
  "audit_id": "550e8400-e29b-41d4-a716-446655440000",
  "url": "https://example.com",
  "timestamp": "2026-09-11T12:00:00Z",
  "duration_seconds": 42.3,
  "ai_readiness_score": 67,
  "score_band": "Good",
  "findings": [
    {
      "id": "F-BOT-001",
      "title": "GPTBot blocked by robots.txt Disallow: /",
      "severity": "critical",
      "type": "defect",
      "evidence": "User-agent: GPTBot\\nDisallow: /",
      "suggested_action": {
        "summary": "Remove Disallow: / for GPTBot in robots.txt",
        "priority": "critical",
        "effort": "low",
        "implementation_hint": "Add: User-agent: GPTBot\\nAllow: /"
      },
      "check_ref": "CHECK-1.1"
    }
  ],
  "layer3_summary": {
    "brand_name_verified": true,
    "wikipedia_description": "...",
    "wikidata_founding_year": 2005,
    "last_modified_days_ago": 14
  },
  "warnings": []
}
```

**Score bands**:
| Band      | Score  | Meaning                                |
|-----------|--------|----------------------------------------|
| Excellent | 80–100 | AI-ready, no significant barriers      |
| Good      | 60–79  | Minor improvements needed              |
| Fair      | 40–59  | Significant gaps in discoverability    |
| Poor      | 0–39   | Critical barriers — AI agents blocked  |

---

## Checks Performed

### Problem Statement 1 — Off-Site AI Discoverability (12 checks)

| Check ID    | Description                                          |
|-------------|------------------------------------------------------|
| CHECK-1.1   | AI bot directive audit (GPTBot, ClaudeBot, PerplexityBot, OAI-SearchBot, Google-Extended) |
| CHECK-1.2   | TTFB differential throttling (R_TTFB > 2.5×)        |
| CHECK-1.3   | WAF challenge-page detection (Cloudflare, Akamai, Imperva, DataDome) |
| CHECK-1.4   | Sitemap robots consistency (blocked URL ratio)       |
| CHECK-1.5   | CSR hydration gap via Node.js + jsdom (delta_H)      |
| CHECK-1.6   | Visual data trap detection (unlabelled media area)   |
| CHECK-1.7   | Semantic noise floor (DOM depth of value proposition)|
| CHECK-1.8   | Schema.org JSON-LD entity completeness               |
| CHECK-1.9   | Multi-source corroboration (Wikipedia + Wikidata)    |
| CHECK-1.10  | Content freshness (Last-Modified, sitemap lastmod)   |
| CHECK-SIG-* | AI content signals (canonical, hreflang, meta desc, robots meta, resource hints) |

### On-Site AI Engagement Checks (6 checks)

| Check ID  | Description                                           |
|-----------|-------------------------------------------------------|
| CHECK-2.1 | Agent action density (D_action formula)               |
| CHECK-2.2 | Click trap detection (non-interactive onclick divs)   |
| CHECK-2.3 | Price divergence (DOM vs JSON-LD offers delta)        |
| CHECK-2.4 | Pagination / infinite scroll loop detection           |
| CHECK-2.5 | Web-to-AI price divergence (off-site corroboration data ↔ on-site DOM) |
| CHECK-2.6 | Form machine-readability (unlabelled input ratio)     |

---

## Hard Constraints (Adobe Hackathon)

- ✅ HTTP: `httpx` async only — no `requests`, no `urllib3`
- ✅ JS engine: Node.js + jsdom subprocess — no Chromium, no Playwright, no Selenium
- ✅ Pixel geometry: FORBIDDEN as detection trigger — HTML attributes only
- ✅ No model weights — fully deterministic algorithms
- ✅ `findings[]` NEVER empty — proactive finding always emitted
- ✅ Corroboration failure → explicit `F-CORR-UNVERIFIED` finding, never crash
- ✅ Runtime < 5 minutes per site
- ✅ ZIP size ≤ 50 MB

---

## Cross-Web Corroboration Contract

Corroboration data collected from Wikidata and DuckDuckGo Lite is passed from
the corroboration check into the engagement audit:

```
corroboration_freshness.py
  └─► cross_web_corroboration {brand_name, wikidata_qid, offsite_price_num, ...}
        └─► engagement.py CHECK-2.5 (web-to-AI price divergence)
```

This cross-module data contract ensures that the price divergence and temporal
freshness checks have access to verified off-site data without making duplicate
external requests.

---

## Novelty Over Sample Submission

| Feature | Sample (Adobe) | This Submission |
|---------|---------------|-----------------|
| JS hydration | PyMiniRacer stub | Node.js + jsdom (real DOM parse + inline script exec) |
| AI bot coverage | 1 (GPTBot) | 5 (GPTBot, ClaudeBot, PerplexityBot, OAI-SearchBot, Google-Extended) |
| WAF vendor coverage | Cloudflare only | Cloudflare + Akamai + Imperva + DataDome + reCAPTCHA |
| Skill count | 4 | 8 (genuine concern separation) |
| Engagement checks | 0 | 6 (intent mismatch, hidden anchors, CTA, overlays, price divergence, boilerplate) |
| Corroboration contract | Not implemented | Cross-Web Corroboration contract (Wikidata + DuckDuckGo Lite) |
| Output schema | Basic | JSON Schema v7 validated + AI Readiness Score |
| References | None | audit_report_schema.json + check_specifications.md |
