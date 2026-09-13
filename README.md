# Brand AI-Readiness Audit Marketplace

> **Adobe University Hackathon 2026 — Round 3 Submission**

This Agent Skill Marketplace automatically audits any website to detect issues affecting **Off-Site AI Discoverability** (how well LLMs can find and cite the brand) and **On-Site AI Engagement** (how well the site retains AI-referred visitors).

Built exactly to the `agentskills.io` standard, it executes fully deterministically in under 10 seconds without heavy browser bloat, producing a JSON report with mechanism-sound, prioritized fixes.

---

## Quick Start

**Prerequisites:** Python 3.10+ and Node.js 18+ (for headless `jsdom` hydration).

```bash
# 1. Install dependencies
pip install -r requirements.txt
cd skills/audit-orchestrator/scripts && npm install && cd ../../..

# 2. Run an audit (outputs JSON)
python run_audit.py https://example.com

# (Optional) Output as a human-readable Markdown summary
python run_audit.py https://example.com --format markdown
```

---

## Agent Skill Composition

As required by the hackathon rubric, this marketplace decomposes the AI-readiness problem into highly focused, single-concern agent skills. 

The `marketplace.json` manifest designates **`audit-orchestrator`** as the single entrypoint. It receives the target URL, delegates specialized tasks concurrently across 6 sub-skills, and merges their outputs into a final serialized report.

| Skill | Role | Primary Concern |
| :--- | :--- | :--- |
| **`audit-orchestrator`** | **Entrypoint** | Coordinates network requests, DOM hydration, and pipeline execution. |
| **`crawl-access-audit`** | Sub-Skill | `robots.txt` AI agent directives, WAF challenge blocking, and TTFB latency. |
| **`render-parity-audit`** | Sub-Skill | Client-Side Rendering (CSR) hydration gap ($\Delta_H$), visual data traps. |
| **`entity-structured-data-audit`** | Sub-Skill | Schema.org `Organization` anchoring and `sameAs` entity disambiguation. |
| **`corroboration-freshness-audit`** | Sub-Skill | Cross-web factual corroboration via Wikidata/DuckDuckGo and freshness metrics. |
| **`engagement-audit`** | Sub-Skill | Intent mismatch, hero CTAs, boilerplate noise ratio, and price divergence. |
| **`ai-content-signals-audit`** | Sub-Skill | AI fast-lane (`/llms.txt`), canonical tagging, and Open Graph / Twitter Cards. |
| **`report-serializer`** | Serializer | Deduplicates findings, calculates AI Readiness scores, and enforces JSON schema. |

---

## Output Report Format

The audit produces a standard JSON schema containing the site, execution metadata, a counts-by-severity summary, and an array of findings.

```json
{
  "site": "https://example.com",
  "audited_at": "2026-09-13T10:45:00Z",
  "summary": {
    "total_findings": 2,
    "critical": 1,
    "high": 1,
    "medium": 0
  },
  "findings": [
    {
      "id": "F-NET-001",
      "title": "robots.txt explicitly blocks AI crawlers",
      "severity": "critical",
      "evidence": "robots.txt disallows GPTBot and ClaudeBot under Disallow: / directives.",
      "suggested_action": {
        "summary": "Update robots.txt to grant explicit Allow access to AI search agents.",
        "priority": "critical"
      }
    }
  ]
}
```

---

## Key Technical Decisions

*   **Zero Hallucinations:** Relies entirely on deterministic heuristics (e.g., semantic DOM word count diffs) rather than non-deterministic LLM evaluation.
*   **Safe & Read-Only:** Strictly performs HTTP GET/HEAD requests and honors rate limits.
*   **Graceful Degradation:** If external corroboration targets (e.g., DuckDuckGo) rate-limit the agent, the skill emits an explicit `UNVERIFIED` finding rather than crashing.
