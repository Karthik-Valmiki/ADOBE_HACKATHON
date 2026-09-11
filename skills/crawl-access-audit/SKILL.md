---
name: crawl-access-audit
version: "1.0.0"
description: >
  Deterministic audit of crawler access gates: robots.txt AI-bot directives,
  Bot-to-Human TTFB ratio, WAF challenge-page detection (Cloudflare, Akamai,
  Imperva, DataDome), and Sitemap-robots consistency.
license: Apache-2.0
tags: [ai-readiness, crawl-access, robots-txt, waf, ps1]
allowed_tools:
  - http_get
  - subprocess
entry: skills/audit-orchestrator/SKILL.md
---

# Crawl Access Audit Skill

## When to Use

Invoke this skill when the agent task is to determine whether AI crawlers can
freely access a target website. Specifically use it when you need to answer:

- Is the site blocking GPTBot, ClaudeBot, PerplexityBot, OAI-SearchBot, or
  Google-Extended in robots.txt?
- Does the server respond significantly slower to AI user-agents than browsers
  (differential throttling)?
- Does a WAF challenge-page intercept the crawl before content is served?
- Is the XML sitemap listed in robots.txt and are its entries consistent with
  robots.txt Allow/Disallow rules?

## Inputs

| Field      | Type   | Required | Description                                     |
|------------|--------|----------|-------------------------------------------------|
| `url`      | string | Yes      | Full URL of the site to audit (https preferred) |
| `timeout`  | float  | No       | Per-request timeout seconds (default: 10.0)     |

## Procedure

Execute in strict order. Do not skip steps.

### Step 1 — Fetch robots.txt

```
GET {root_url}/robots.txt
Headers: User-Agent: AuditBot/2.0
```

Parse each `User-agent:` / `Disallow:` / `Allow:` / `Sitemap:` directive pair.
Build a per-agent allow/disallow map.

### Step 2 — Check AI Bot Directives (CHECK-1.1)

For each agent in `{GPTBot, ClaudeBot, PerplexityBot, OAI-SearchBot, Google-Extended}`:

1. Look up the agent's specific stanza in the parsed robots.txt map.
2. If absent, look up the wildcard `*` stanza.
3. If `Disallow: /` is present for the agent (or wildcard covering it):
   - Emit finding `F-BOT-001` with severity `critical`.
4. If partial disallow (path other than `/`):
   - Emit finding `F-BOT-002` with severity `high`.
5. If allow (or no directive found):
   - Emit proactive finding `F-BOT-OK` with severity `low`, type `proactive`.

### Step 3 — TTFB Differential Ratio (CHECK-1.2)

```
t_ai   = elapsed_ms(GET {url}, User-Agent: GPTBot/1.1)
t_browser = elapsed_ms(GET {url}, User-Agent: Mozilla/5.0 ...)
R_TTFB = t_ai / t_browser
```

- If `R_TTFB > 2.5`: emit `F-BOT-003`, severity `high`.
- Repeat for at least 3 requests each; use median values.

### Step 4 — WAF Challenge Detection (CHECK-1.3)

Fetch the page with each AI user-agent. Inspect the response body for
challenge-page DOM signatures (attribute-pattern scan, not pixel geometry):

- Cloudflare: `id="challenge-form"`, `turnstile` src, `cf-mitigated` header
- Akamai: `id="akam-sc-blocked"`, Akamai header `x-akamai-transformed`
- Imperva: `incapsula` class, `_Incapsula_Resource` script src
- DataDome: `id="ddCaptcha"`, `datadome` script src

If any pattern matches: emit `F-BOT-004`, severity `critical`.

### Step 5 — Sitemap Consistency (CHECK-1.4)

1. Parse `Sitemap:` directives from robots.txt.
2. Fetch each sitemap XML (up to 3).
3. For each `<loc>` URL in the sitemap, check if it is blocked by the robot
   rules for `GPTBot`.
4. If >10% of sitemap URLs are blocked for GPTBot: emit `F-BOT-005`, severity `high`.

## Output

```json
{
  "skill": "crawl-access-audit",
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
  ]
}
```

Each finding MUST include `id`, `title`, `severity`, `type`, `evidence`,
`suggested_action`, and `check_ref`. The `findings` array MUST NEVER be empty —
emit at least one proactive finding if no defects are detected.
