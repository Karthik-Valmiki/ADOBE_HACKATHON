---
name: corroboration-freshness-audit
version: "1.0.0"
description: >
  Deterministic multi-source corroboration and content freshness audit.
  Verifies brand claims against Wikidata APIs (no LLM).
  Checks last-modified headers, sitemap lastmod dates, and copyright year
  consistency. Emits the Cross-Web Output Contract for downstream skills.
license: Apache-2.0
tags: [ai-readiness, corroboration, freshness, wikidata]
allowed_tools:
  - http_get
entry: skills/audit-orchestrator/SKILL.md
---

# Corroboration & Freshness Audit Skill

## When to Use

Invoke this skill after the entity-structured-data-audit has identified brand
entity types and sameAs URLs. Use it when:

- You need to verify that the brand's stated name, description, and founding
  date match Wikidata records.
- You need to check whether on-site content is stale relative to external
  knowledge sources.
- You need to detect temporal inconsistencies (copyright year mismatch,
  outdated sitemap lastmod) that reduce AI trust signals.

## Inputs

| Field          | Type         | Required | Description                                          |
|----------------|--------------|----------|------------------------------------------------------|
| `url`          | string       | Yes      | Root URL of the site                                 |
| `brand_name`   | string       | No       | Brand name (extracted from JSON-LD name field)       |
| `entity_types` | list[string] | No       | @type values from entity-structured-data-audit       |
| `sameAs_urls`  | list[string] | No       | sameAs URLs (Wikipedia/Wikidata links if present)    |

## Procedure

### Step 1 — Wikidata Entity Lookup (CHECK-1.9)

Search Wikidata for the brand name:
```
GET https://www.wikidata.org/w/api.php?action=wbsearchentities&search={brand_name}&language=en
```

- If entity found: emit `F-ENTITY-003` (proactive, Low) with QID.
- If entity not found: emit `F-ENTITY-002` (Medium) — brand has no machine-readable Wikidata identity.
- If request fails (rate-limited, network error): emit `F-ENTITY-UNVERIFIED` (Medium). **Never crash.**

### Step 2 — DuckDuckGo Lite Temporal Freshness (CHECK-1.10)

Fetch DuckDuckGo Lite search results for the brand name:
```
GET https://lite.duckduckgo.com/lite/?q="{brand_name}" "{key_product_term}"
```

Parse year mentions (4-digit, 2010–2030) from snippet text.
Compute `offsite_year_max` = maximum year found in snippets.
Compute `temporal_delta` = current_year - offsite_year_max.

- If `temporal_delta >= 2`: emit `F-FRESH-001` (High) — AI knowledge about the brand is stale.
- If DuckDuckGo is unavailable: emit `F-FRESH-UNVERIFIED` (Medium). **Never crash.**

### Step 3 — Off-site Price Extraction

From DuckDuckGo snippets, extract the first price-like string matching:
```
\$[\d,]+(?:\.\d{2})?(?:/mo|/month|/year|/yr|/user|/seat)?
```

Store as `offsite_price_str` and `offsite_price_num` (normalised to monthly).
This data is consumed by the engagement audit for the price-divergence check.

## Cross-Web Output Contract

After completing all checks, this skill MUST emit a `layer3_contract` key in
its result dict (in addition to the `findings` array). This contract is consumed
by the engagement-audit skill:

```json
{
  "layer3_contract": {
    "brand_name": "<string>",
    "corroboration_status": "ok | rate_limited | blocked",
    "wikidata_entity_found": true | false,
    "wikidata_qid": "<string or null>",
    "offsite_price_str": "<string>",
    "offsite_price_num": "<float or null>",
    "offsite_year_max": "<int or null>",
    "offsite_snippets": ["<string>"]
  }
}
```

> Note: The key is named `layer3_contract` internally for backward-compat with the
> orchestrator's `corroboration_result.get("layer3_contract", {})` call. The
> orchestrator then maps this to `cross_web_corroboration` in the final report output.

## Output

Standard findings array plus the contract object. All findings MUST include
`id`, `title`, `severity`, `type`, `evidence`, `suggested_action`, and `check_ref`.
On corroboration source failure, emit an UNVERIFIED finding instead of crashing.
