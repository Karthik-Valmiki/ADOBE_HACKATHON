# Brand AI Readiness Audit — Check Specifications

> Engineering reference for all deterministic check algorithms.
> Every threshold, formula, and finding ID is defined here.
> Do NOT change thresholds without updating this document AND the corresponding Python module.

---

## Check Registry

| Check ID     | Skill                          | Finding IDs               | Audit Domain          |
|--------------|--------------------------------|---------------------------|-----------------------|
| CHECK-1.1    | crawl-access-audit             | F-NET-001, F-NET-002      | Crawl Access          |
| CHECK-1.2    | crawl-access-audit             | F-NET-003                 | Crawl Access          |
| CHECK-1.3    | crawl-access-audit             | F-NET-004                 | Crawl Access          |
| CHECK-1.4    | crawl-access-audit             | F-LLMS-001, F-LLMS-OK     | Crawl Access          |
| CHECK-1.5    | render-parity-audit            | F-DOM-001                 | Rendering Parity      |
| CHECK-1.6    | render-parity-audit            | F-DOM-002                 | Rendering Parity      |
| CHECK-1.7    | render-parity-audit            | F-DOM-005                 | Rendering Parity      |
| CHECK-1.8    | entity-structured-data-audit   | F-ENTITY-001, F-SCHEMA-*  | Entity & Structured Data |
| CHECK-1.9    | corroboration-freshness-audit  | F-ENTITY-002, F-ENTITY-003, F-ENTITY-UNVERIFIED | Cross-Web Corroboration |
| CHECK-1.10   | corroboration-freshness-audit  | F-FRESH-001, F-FRESH-UNVERIFIED | Cross-Web Corroboration |
| CHECK-SIG-1  | ai-content-signals-audit       | F-SIG-001, F-SIG-002      | Content Signals       |
| CHECK-SIG-2  | ai-content-signals-audit       | F-SIG-003                 | Content Signals       |
| CHECK-SIG-3  | ai-content-signals-audit       | F-SIG-004, F-SIG-005      | Content Signals       |
| CHECK-SIG-4  | ai-content-signals-audit       | F-SIG-006, F-SIG-007, F-SIG-008 | Content Signals  |
| CHECK-SIG-5  | ai-content-signals-audit       | F-SIG-009 through F-SIG-011 | Content Signals     |
| CHECK-SIG-6  | ai-content-signals-audit       | F-SIG-012                 | Content Signals       |
| CHECK-2.1    | engagement-audit               | F-ENG-004                 | On-Site Engagement    |
| CHECK-2.2    | engagement-audit               | F-ENG-003                 | On-Site Engagement    |
| CHECK-2.3    | engagement-audit               | F-ENG-007                 | On-Site Engagement    |
| CHECK-2.4    | engagement-audit               | F-ENG-009, F-ENG-010      | On-Site Engagement    |
| CHECK-2.5    | engagement-audit               | F-ENG-013, F-ENG-013-UNVERIFIED | On-Site Engagement |
| CHECK-2.6    | engagement-audit               | F-ENG-006, F-ENG-005      | On-Site Engagement    | |

---

## Detailed Specifications

### CHECK-1.1 — AI Bot Directive Audit

**Module**: `crawl_access.py` → `_check_robot_directives()`

**Algorithm**:
1. Parse `/robots.txt` using directive-pair state machine (not regex).
2. Build map: `{user_agent_name: {disallow: [...], allow: [...]}}`
3. For each target agent in `AI_USER_AGENTS`:
   - Check agent-specific stanza first; fall back to `*` stanza.
   - Apply longest-match rule for overlapping Allow/Disallow paths.

**Target agents**: `GPTBot`, `ClaudeBot`, `PerplexityBot`, `OAI-SearchBot`, `Google-Extended`

**Thresholds**:
- `Disallow: /` → `F-BOT-001`, severity `critical`
- Any other Disallow path → `F-BOT-002`, severity `high`
- No disallow (agent allowed) → `F-BOT-OK`, severity `low`, type `proactive`

---

### CHECK-1.2 — TTFB Differential Throttling Detection

**Module**: `crawl_access.py` → `_check_ttfb_differential()`

**Formula**:
```
R_TTFB = median(t_ai_requests) / median(t_browser_requests)
```

**Requests**: 3 per user-agent (GPTBot, browser UA). Use `httpx.Response.elapsed`.

**Thresholds**:
- `R_TTFB > 2.5` → `F-BOT-003`, severity `high`
- `1.0 <= R_TTFB <= 2.5` → no finding (within acceptable variance)
- `R_TTFB < 1.0` → `F-BOT-FAST-OK`, severity `low`, type `proactive`

---

### CHECK-1.3 — WAF Challenge-Page Detection

**Module**: `crawl_access.py` + `utils.py` → `is_waf_challenge_body()`

**Method**: Attribute-pattern AST scan (regex on HTML attribute values/IDs).
**NEVER** uses pixel geometry or visual rendering.

**Vendor signatures**:
| Vendor     | Pattern |
|------------|---------|
| Cloudflare | `id="challenge-form"`, `turnstile` script src, `cf-mitigated` header |
| Akamai     | `id="akam-sc-blocked"`, `x-akamai-transformed` header |
| Imperva    | `incapsula` class name, `_Incapsula_Resource` script src |
| DataDome   | `id="ddCaptcha"`, `datadome` script src |
| reCAPTCHA  | `g-recaptcha` id/class/src |

**Threshold**: Any signature match → `F-BOT-004`, severity `critical`.

---

### CHECK-1.4 — Sitemap Robots Consistency

**Module**: `crawl_access.py` → `_check_sitemap_consistency()`

**Algorithm**:
1. Parse `Sitemap:` directives from robots.txt.
2. Fetch up to 3 sitemap XMLs.
3. For each `<loc>` URL: apply GPTBot Disallow rules (longest-match).
4. Compute `blocked_ratio = blocked_count / total_count`.

**Threshold**:
- `blocked_ratio > 0.10` → `F-BOT-005`, severity `high`
- `blocked_ratio == 0` → `F-BOT-SITEMAP-OK`, severity `low`, type `proactive`

---

### CHECK-1.5 — CSR Hydration Gap

**Module**: `render_parity.py` → `run_render_parity_audit()`

**JS Engine**: Node.js + jsdom (via `jsdom_runner.js` subprocess)
**CONSTRAINT**: No Chromium. No Playwright. No Selenium.

**Formula**:
```
w_static   = word_count(extract_semantic_text(static_html))
w_hydrated = word_count(jsdom_runner.stdout.word_count)
delta_H    = w_static / w_hydrated
```

**Thresholds**:
- `delta_H < 0.15` → `F-DOM-001`, severity `critical` (≥85% content CSR-locked)
- `0.15 ≤ delta_H < 0.85` → no primary finding (partial hydration)
- `delta_H ≥ 0.85` → `F-DOM-SSR-OK`, severity `low`, type `proactive`

---

### CHECK-1.6 — Visual Data Trap

**Module**: `render_parity.py` → `_check_visual_data_trap()`

**CONSTRAINT**: HTML `width`/`height` attributes only. CSS pixel geometry FORBIDDEN.

**Formula**:
```
A_total_unlabelled = sum(width * height for unlabelled_media_in_main_or_article)
text_density = len(text_chars_in_content_area) / A_total_unlabelled
```

**Thresholds**:
- `A_total_unlabelled > 200,000` AND `text_density < 0.20` → `F-DOM-002`, severity `critical`

---

### CHECK-1.7 — Semantic Noise Floor

**Module**: `render_parity.py` → `_check_semantic_noise_floor()`

**Algorithm**:
1. Identify top-3 value-proposition candidates (h1/h2 + hero-class elements),
   scored by TF-IDF token overlap with page title.
2. For each candidate: count ancestor opening tags minus closing tags before
   candidate position in HTML string → estimated DOM depth `d`.

**Threshold**: `d > 10` → `F-DOM-005`, severity `medium`

---

### CHECK-1.8 — Schema.org Entity Completeness

**Module**: `entity_structured_data.py`

**Required properties by @type**:
| @type          | Required Properties                                                |
|----------------|--------------------------------------------------------------------|
| Organization   | name, url, logo, contactPoint \| sameAs                           |
| LocalBusiness  | name, address, telephone, openingHours, geo                        |
| Product        | name, description, offers{price,priceCurrency}, image, brand      |
| Article        | headline, author, datePublished, publisher                         |
| WebSite        | name, url, potentialAction{SearchAction}                          |
| BreadcrumbList | itemListElement[].item, .name, .position                          |

Missing required property → `F-ENT-001`, severity `high` per property.
JSON-LD parse failure → `F-ENT-002`, severity `critical`.

---

### CHECK-1.9 — External Corroboration

**Module**: `corroboration_freshness.py`

**API calls**: Wikipedia REST API, Wikidata EntityData API (both public, no key required)

**Formula**:
```
token_overlap = |tokens(wiki_description) ∩ tokens(site_description)| / |tokens(wiki_description)|
```

**Thresholds**:
- `token_overlap < 0.20` AND wiki page exists → `F-CORR-001`, severity `medium`
- Wikidata `foundingDate` year mismatch > 1 year → `F-CORR-002`, severity `medium`
- Wikidata `officialWebsite` domain ≠ audited domain → `F-CORR-003`, severity `high`
- Network error → `F-CORR-UNVERIFIED`, severity `low`, type `proactive` (never crash)

---

### CHECK-1.10 — Content Freshness

**Module**: `corroboration_freshness.py`

**Metrics**:
1. `Last-Modified` header age in days
2. Sitemap `<lastmod>` median age in days
3. Copyright year regex: `©\s*(\d{4})`

**Thresholds**:
- No `Last-Modified` header → `F-FRESH-001`, severity `low`
- `Last-Modified` > 365 days ago → `F-FRESH-002`, severity `medium`
- Sitemap `median_age_days > 180` → `F-FRESH-003`, severity `medium`
- Copyright year < current_year - 1 → `F-FRESH-004`, severity `low`

---

### CHECK-2.1 — Agent Action Density

**Module**: `engagement.py`

**Formula**:
```
D_action = count(semantic_action_anchors) / count(total_paragraphs_and_headings)
```

**Semantic action verbs** (case-insensitive): `buy`, `add to cart`, `shop`,
`subscribe`, `download`, `get started`, `try`, `book`, `contact`, `order`,
`register`, `sign up`, `start`, `explore`, `learn more`.

**Thresholds**:
- `D_action < 0.05` → `F-ENG-001`, severity `high`
- `D_action > 0.30` → `F-ENG-002`, severity `medium`
- Else → `F-ENG-OK`, severity `low`, type `proactive`

---

### CHECK-2.2 — Click Trap Detection

**Module**: `engagement.py`

**Detection**: Elements with (`onclick` \| `@click` \| `data-action` \| `role="button"`)
AND NOT (`<a href>` \| `<button type>`).

**Thresholds**:
- `N_traps >= 3` → `F-ENG-003`, severity `high`
- `N_traps 1–2` → `F-ENG-004`, severity `medium`

---

### CHECK-2.3 — Price Divergence

**Module**: `engagement.py`

**Price extraction regex**:
```
r'[$£€¥]\s*\d[\d,]*(?:\.\d{1,2})?|\d[\d,]*(?:\.\d{1,2})?\s*(?:USD|EUR|GBP|INR)'
```

**Formula**: `delta_price = |P_dom - P_ld| / P_ld`

**Threshold**: `delta_price > 0.05` → `F-ENG-005`, severity `critical`

---

### CHECK-2.4 — Pagination Loop Detection

**Module**: `engagement.py`

**Signals**:
- `rel="next"` link present
- `load more`/`next page`/`show more` anchor text
- `data-page`/`data-offset`/`data-cursor` attributes

Any signal → `F-ENG-006`, severity `medium`

---

### CHECK-2.5 — Web-to-AI Price Divergence

**Module**: `engagement.py`

**Requires**: `cross_web_corroboration.offsite_price_num` (from corroboration-freshness-audit)

**Algorithm**:
1. Extract on-site pricing from JSON-LD `Offer.price` or regex `PRICE_PATTERN` against visible text.
2. Normalise both on-site and off-site prices to monthly USD.
3. `delta_Value = |onsite_price_num - offsite_price_num|`

**Thresholds**:
- Any numeric mismatch (`delta_Value > 0`) → `F-ENG-013`, severity `critical`
- Off-site price unavailable (corroboration status = `rate_limited` or `blocked`) → `F-ENG-013-UNVERIFIED`, severity `medium`

---

### CHECK-2.6 — Form Machine-Readability

**Module**: `engagement.py`

**Unlabelled input**: No `<label for>` AND no `aria-label` AND no meaningful `placeholder`.

**Formula**: `unlabelled_ratio = unlabelled_count / total_input_count`

**Thresholds**:
- `unlabelled_ratio > 0.40` → `F-ENG-008`, severity `high`
- `unlabelled_ratio > 0.20` → `F-ENG-009`, severity `medium`

---

## AI Readiness Score Formula

```python
WEIGHTS = {"critical": 20, "high": 8, "medium": 3, "low": 1}

defect_findings = [f for f in findings if f["type"] == "defect"]
penalty = sum(WEIGHTS[f["severity"]] for f in defect_findings)
score = max(0, 100 - penalty)
```

| Band      | Range  | Meaning                              |
|-----------|--------|--------------------------------------|
| Excellent | 80–100 | AI-ready, no significant barriers    |
| Good      | 60–79  | Minor improvements needed             |
| Fair      | 40–59  | Significant gaps in AI discoverability|
| Poor      | 0–39   | Critical barriers — AI agents blocked |
