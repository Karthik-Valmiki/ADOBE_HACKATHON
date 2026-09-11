---
name: entity-structured-data-audit
version: "1.0.0"
description: >
  Deterministic audit of Schema.org JSON-LD entity definitions, OpenGraph
  tags, and Twitter Card metadata. Validates @type hierarchy, required
  property completeness, and structured data parseability for AI knowledge
  graph construction.
license: Apache-2.0
tags: [ai-readiness, schema-org, json-ld, structured-data, entity, ps1]
allowed_tools:
  - http_get
entry: skills/audit-orchestrator/SKILL.md
---

# Entity Structured Data Audit Skill

## When to Use

Invoke this skill when the agent task is to determine whether an AI agent or
search engine can construct a correct knowledge-graph node for the brand from
the site's structured data. Use it when:

- The brand claims a specific @type (Organization, Product, LocalBusiness, etc.)
  but you need to verify the JSON-LD is correct and complete.
- You need to check if critical entity properties are missing.
- You need to verify OpenGraph and Twitter Card metadata for social AI ingestion.

## Inputs

| Field          | Type   | Required | Description                                         |
|----------------|--------|----------|-----------------------------------------------------|
| `url`          | string | Yes      | Full URL of the page to audit                       |
| `hydrated_html`| string | No       | Pre-fetched hydrated HTML from render-parity-audit  |

## Procedure

### Step 1 — Extract JSON-LD Blocks (CHECK-1.8)

From the page HTML (prefer hydrated HTML if available), find all:

```html
<script type="application/ld+json"> ... </script>
```

Parse each block as JSON. Handle both single objects and arrays (`@graph`).

### Step 2 — Validate @type and Required Properties

For each parsed block, identify the `@type`. Apply the property checklist:

| @type               | Required Properties                                                          |
|---------------------|------------------------------------------------------------------------------|
| Organization        | name, url, logo, contactPoint OR sameAs                                      |
| LocalBusiness       | name, address, telephone, openingHours, geo                                  |
| Product             | name, description, offers (with price + priceCurrency), image, brand        |
| Article / BlogPost  | headline, author, datePublished, publisher                                   |
| WebSite             | name, url, potentialAction (SearchAction)                                    |
| BreadcrumbList      | itemListElement[].item, itemListElement[].name, itemListElement[].position   |

If a required property is absent: emit `F-ENT-001` (severity: `high`) per missing property.

### Step 3 — JSON-LD Parse Error Check

If any `<script type="application/ld+json">` block fails JSON.parse:
- Emit `F-ENT-002`, severity `critical`.
- Include the parse error and a 200-char snippet as evidence.

### Step 4 — OpenGraph Completeness (CHECK-OG)

Check for: `og:title`, `og:description`, `og:image`, `og:type`, `og:url`.

- Missing ≥3: emit `F-ENT-003`, severity `high`.
- Missing 1–2: emit `F-ENT-004`, severity `medium`.
- All present: emit `F-ENT-OG-OK`, severity `low`, type `proactive`.

### Step 5 — Twitter Card (CHECK-TC)

Check for: `twitter:card`, `twitter:title`, `twitter:description`.

- Missing `twitter:card`: emit `F-ENT-005`, severity `medium`.
- Incorrect `twitter:card` value (not `summary`, `summary_large_image`, `app`, `player`): emit `F-ENT-006`, severity `low`.

## Output

Standard findings array with all entity-layer findings. Pass the extracted
`entity_types` list and `sameAs_urls` list downstream to the corroboration
skill for cross-source verification.

All findings MUST include `id`, `title`, `severity`, `type`, `evidence`,
`suggested_action`, and `check_ref`.
