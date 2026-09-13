# Brand AI-Readiness Audit Marketplace

This Agent Skill Marketplace automatically audits websites to detect issues affecting **Off-Site AI Discoverability** (how well AI assistants can find and cite the brand) and **On-Site AI Engagement** (how well the site retains AI-referred visitors). 

## Codebase Overview

The marketplace is built following the Agent Skills standard (`agentskills.io`). It decomposes the AI-readiness problem into highly focused, single-concern sub-skills. 

An **entrypoint skill** (`audit-orchestrator`) receives the audit request for a specific target URL, composes the checks by delegating tasks across the sub-skills concurrently, and aggregates the results into a single standardized JSON report containing both evidence-backed findings and prioritized suggested actions.

## Skills Breakdown

### Entrypoint

*   **`audit-orchestrator`**: The designated entrypoint skill. It fetches the target URL (handling both raw network requests and JS-hydrated DOM), invokes the specialized sub-skills in the marketplace, and passes the collected outputs to the report serializer to generate the final audit report.

### Sub-Skills

*   **`crawl-access-audit`**: Inspects `robots.txt` directives against AI crawler bots (e.g., GPTBot, ClaudeBot), checks for Web Application Firewall (WAF) challenge blocks, and measures TTFB (Time to First Byte) latency.
*   **`render-parity-audit`**: Analyzes the gap between the raw HTML and the JavaScript-hydrated DOM (CSR hydration gap) to identify crucial content that non-JS crawlers would miss.
*   **`entity-structured-data-audit`**: Looks for Schema.org JSON-LD markup (such as `Organization` and `sameAs`) to ensure the brand's identity is machine-readable and accurately disambiguated.
*   **`corroboration-freshness-audit`**: Cross-references on-site claims with external knowledge graphs (like Wikidata) to ensure external corroboration and detects stale content.
*   **`engagement-audit`**: Evaluates the post-click experience, checking for high boilerplate-to-content ratios, missing context retention, and hero Call-to-Action (CTA) mismatches that might cause referred visitors to bounce.
*   **`ai-content-signals-audit`**: Searches for direct optimization signals for AI assistants, such as `/llms.txt`, well-formed canonical tags, and Open Graph metadata.
*   **`report-serializer`**: A utility skill that takes the raw findings from all sub-skills, deduplicates them, assigns categories (discoverability vs. engagement), and strictly enforces the final JSON schema structure.

## Getting Started

### Prerequisites
- Python 3.10+
- Node.js 18+ (for headless `jsdom` hydration)

### Installation & Execution
```bash
# 1. Install dependencies
pip install -r requirements.txt
cd skills/audit-orchestrator/scripts && npm install && cd ../../..

# 2. Run an audit against a target URL (outputs JSON)
python run_audit.py https://example.com
```

### Output Report Format
The audit produces a standardized JSON schema:
- **`site`**: The audited URL.
- **`audited_at`**: Timestamp of the audit.
- **`summary`**: Breakdown of total findings by severity (`critical`, `high`, `medium`, `low`) and category (`discoverability`, `engagement`).
- **`findings`**: An array of detected issues, each detailing an `id`, `title`, `severity`, `evidence`, and a prioritized `suggested_action` describing how to fix it.
