#!/usr/bin/env python3
"""
report_serializer.py — Final report serialiser and HTML dashboard generator.
Validates schema compliance, sorts findings, computes summary counts.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
AUDIT_VERSION = "2.0.0"


def serialize_report(
    site: str,
    findings: list[dict],
    layer3_contract: dict,
    elapsed_seconds: float,
    js_engine_available: bool,
    checks_partial: list[str],
    output_format: str = "json",
) -> dict[str, Any]:
    """
    Validate, deduplicate, sort, and package all findings into final report.
    """
    # Deduplicate by finding ID (keep first occurrence)
    seen_ids: set[str] = set()
    unique_findings: list[dict] = []
    for f in findings:
        fid = f.get("id", "")
        if fid not in seen_ids:
            seen_ids.add(fid)
            unique_findings.append(_validate_finding(f))

    # Sort: critical → high → medium → low → proactive/info
    unique_findings.sort(key=lambda f: (
        0 if f.get("type") == "defect" else 1,
        SEVERITY_RANK.get(f.get("severity", "medium"), 2),
        f.get("id", ""),
    ))

    # Summary counts
    defects = [f for f in unique_findings if f.get("type") != "proactive"]
    proactive = [f for f in unique_findings if f.get("type") == "proactive"]

    summary = {
        "total_findings": len(unique_findings),
        "critical": sum(1 for f in defects if f.get("severity") == "critical"),
        "high": sum(1 for f in defects if f.get("severity") == "high"),
        "medium": sum(1 for f in defects if f.get("severity") == "medium"),
        "low": sum(1 for f in defects if f.get("severity") == "low"),
        "proactive": len(proactive),
        "by_category": {
            "discoverability": sum(1 for f in unique_findings if not f.get("id", "").startswith("F-ENG") and not f.get("id", "").startswith("F-TIMEOUT")),
            "engagement": sum(1 for f in unique_findings if f.get("id", "").startswith("F-ENG")),
        }
    }

    report = {
        "site": site,
        "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audit_version": AUDIT_VERSION,
        "summary": summary,
        "findings": unique_findings,
        "cross_web_corroboration": layer3_contract,
        "runtime_meta": {
            "elapsed_seconds": round(elapsed_seconds, 2),
            "js_engine_available": js_engine_available,
            "checks_partial": checks_partial,
        },
    }

    return report


def _validate_finding(f: dict) -> dict:
    """Ensure finding has all required fields. Fill defaults for missing optional fields."""
    required = ["id", "title", "severity", "evidence", "suggested_action"]
    for field in required:
        if field not in f:
            if field == "suggested_action":
                f[field] = {
                    "summary": "No remediation was specified for this finding. Investigate the evidence string above.",
                    "priority": f.get("severity", "medium"),
                    "effort": "medium",
                    "implementation_hint": "Cross-reference the finding ID against the check_specifications.md reference document for the full algorithm and remediation steps."
                }
            else:
                f[field] = f"MISSING_{field.upper()}"

    # Ensure severity is valid
    valid_severities = {"critical", "high", "medium", "low", "info"}
    if f.get("severity") not in valid_severities:
        f["severity"] = "medium"

    # Ensure type field
    if "type" not in f:
        f["type"] = "defect"

    # Ensure suggested_action is a dict with required subfields
    sa = f.get("suggested_action", {})
    if isinstance(sa, str):
        f["suggested_action"] = {
            "summary": sa,
            "priority": f.get("severity", "medium"),
            "effort": "medium",
            "implementation_hint": "",
        }
    elif isinstance(sa, dict):
        if "summary" not in sa:
            sa["summary"] = "No remediation summary provided. Refer to the finding evidence string and check_ref for corrective action."
        if "priority" not in sa:
            sa["priority"] = f.get("severity", "medium")
        if "effort" not in sa:
            sa["effort"] = "medium"
        if "implementation_hint" not in sa:
            sa["implementation_hint"] = ""

    # Truncate evidence to reasonable length
    if len(f.get("evidence", "")) > 1000:
        f["evidence"] = f["evidence"][:997] + "..."

    return f


def generate_html_report(report: dict) -> str:
    """Generate a beautiful HTML dashboard from the report dict."""
    site = report.get("site", "")
    audited_at = report.get("audited_at", "")
    summary = report.get("summary", {})
    findings = report.get("findings", [])
    runtime_meta = report.get("runtime_meta", {})

    severity_colors = {
        "critical": "#FF3B30",
        "high": "#FF9500",
        "medium": "#FFCC00",
        "low": "#34C759",
        "info": "#5AC8FA",
    }
    severity_bg = {
        "critical": "#FF3B3015",
        "high": "#FF950015",
        "medium": "#FFCC0015",
        "low": "#34C75915",
        "info": "#5AC8FA15",
    }

    findings_html = ""
    for f in findings:
        sev = f.get("severity", "medium")
        ftype = f.get("type", "defect")
        color = severity_colors.get(sev, "#888")
        bg = severity_bg.get(sev, "#f9f9f9")
        sa = f.get("suggested_action", {})
        hint = sa.get("implementation_hint", "") if isinstance(sa, dict) else ""

        badge_label = "PROACTIVE ✓" if ftype == "proactive" else sev.upper()
        badge_color = "#34C759" if ftype == "proactive" else color

        findings_html += f"""
        <div class="finding-card" data-severity="{sev}" data-type="{ftype}" style="border-left: 4px solid {color}; background: {bg};">
            <div class="finding-header">
                <span class="finding-id">{f.get("id", "")}</span>
                <span class="severity-badge" style="background:{badge_color}20; color:{badge_color}; border:1px solid {badge_color}40;">{badge_label}</span>
            </div>
            <h3 class="finding-title">{_escape_html(f.get("title", ""))}</h3>
            <div class="finding-section">
                <div class="section-label">📋 Evidence</div>
                <div class="evidence-text">{_escape_html(f.get("evidence", ""))}</div>
            </div>
            <div class="finding-section">
                <div class="section-label">🔧 Suggested Action</div>
                <div class="action-text">{_escape_html(sa.get("summary", "") if isinstance(sa, dict) else str(sa))}</div>
                {"<div class='hint-box'><span class='hint-label'>💡 Implementation:</span> " + _escape_html(hint) + "</div>" if hint else ""}
            </div>
            <div class="finding-meta">
                <span>Effort: <strong>{(sa.get("effort","—") if isinstance(sa,dict) else "—").upper()}</strong></span>
                <span>Check: <code>{f.get("check_ref","")}</code></span>
            </div>
        </div>"""

    critical_count = summary.get("critical", 0)
    high_count = summary.get("high", 0)
    medium_count = summary.get("medium", 0)
    low_count = summary.get("low", 0)
    proactive_count = summary.get("proactive", 0)
    total = summary.get("total_findings", 0)

    # AI Readiness Score (0-100)
    score = max(0, 100 - (critical_count * 25) - (high_count * 10) - (medium_count * 4) - (low_count * 1))
    score_color = "#FF3B30" if score < 40 else "#FF9500" if score < 70 else "#34C759"

    js_status = "✅ Available" if runtime_meta.get("js_engine_available") else "⚠️ Static-only"
    elapsed = runtime_meta.get("elapsed_seconds", 0)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Readiness Audit — {site}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg-primary: #0A0E1A;
    --bg-secondary: #111827;
    --bg-card: #161D2E;
    --bg-card-hover: #1E2840;
    --accent-blue: #3B82F6;
    --accent-purple: #8B5CF6;
    --accent-cyan: #06B6D4;
    --text-primary: #F9FAFB;
    --text-secondary: #9CA3AF;
    --text-muted: #6B7280;
    --border: #1F2D45;
    --border-light: #2D3E57;
    --critical: #FF3B30;
    --high: #FF9500;
    --medium: #FFCC00;
    --low: #34C759;
    --gradient-1: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    --gradient-2: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
    --gradient-hero: linear-gradient(135deg, #0A0E1A 0%, #1a1040 50%, #0A0E1A 100%);
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Inter',sans-serif; background:var(--bg-primary); color:var(--text-primary); min-height:100vh; }}

  /* Hero Header */
  .hero {{
    background: var(--gradient-hero);
    border-bottom: 1px solid var(--border);
    padding: 3rem 2rem 2rem;
    position: relative;
    overflow: hidden;
  }}
  .hero::before {{
    content:'';
    position:absolute; top:-50%; left:-50%; width:200%; height:200%;
    background: radial-gradient(ellipse at 60% 40%, rgba(139,92,246,0.15) 0%, transparent 60%),
                radial-gradient(ellipse at 20% 80%, rgba(59,130,246,0.1) 0%, transparent 50%);
    pointer-events:none;
  }}
  .hero-inner {{ max-width:1200px; margin:0 auto; position:relative; z-index:1; }}
  .hero-badge {{
    display:inline-flex; align-items:center; gap:8px;
    background:rgba(139,92,246,0.15); border:1px solid rgba(139,92,246,0.3);
    border-radius:100px; padding:6px 16px; font-size:12px; font-weight:600;
    color:#A78BFA; text-transform:uppercase; letter-spacing:1px; margin-bottom:1.5rem;
  }}
  .hero h1 {{ font-size:2.5rem; font-weight:800; line-height:1.2; margin-bottom:0.5rem;
    background:linear-gradient(135deg,#F9FAFB,#A78BFA); -webkit-background-clip:text;
    -webkit-text-fill-color:transparent; background-clip:text; }}
  .hero-site {{ font-size:1.1rem; color:var(--accent-cyan); font-family:'JetBrains Mono',monospace;
    margin-bottom:0.5rem; }}
  .hero-meta {{ font-size:0.85rem; color:var(--text-muted); }}

  /* Score Ring */
  .score-section {{ display:flex; align-items:center; gap:2rem; margin-top:2rem; flex-wrap:wrap; }}
  .score-ring-container {{ position:relative; width:120px; height:120px; flex-shrink:0; }}
  .score-ring-container svg {{ transform:rotate(-90deg); }}
  .score-text {{
    position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
    text-align:center;
  }}
  .score-num {{ font-size:2rem; font-weight:800; line-height:1; color:{score_color}; }}
  .score-label {{ font-size:10px; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px; }}
  .score-desc {{ flex:1; }}
  .score-desc h2 {{ font-size:1.3rem; font-weight:700; margin-bottom:0.25rem; }}
  .score-desc p {{ color:var(--text-secondary); font-size:0.9rem; }}

  /* Summary Cards */
  .summary-grid {{
    display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
    gap:1rem; max-width:1200px; margin:2rem auto; padding:0 2rem;
  }}
  .summary-card {{
    background:var(--bg-card); border:1px solid var(--border); border-radius:16px;
    padding:1.25rem 1rem; text-align:center;
    transition:all 0.2s; cursor:pointer;
  }}
  .summary-card:hover {{ border-color:var(--border-light); background:var(--bg-card-hover); transform:translateY(-2px); }}
  .summary-card.active {{ border-color:var(--accent-blue); }}
  .summary-num {{ font-size:2.5rem; font-weight:800; line-height:1; }}
  .summary-sev {{ font-size:0.75rem; text-transform:uppercase; letter-spacing:1px; color:var(--text-muted); margin-top:4px; }}

  /* Filters */
  .filter-bar {{
    max-width:1200px; margin:0 auto 1rem; padding:0 2rem;
    display:flex; gap:0.75rem; flex-wrap:wrap; align-items:center;
  }}
  .filter-label {{ font-size:0.85rem; color:var(--text-muted); }}
  .filter-btn {{
    padding:6px 14px; border-radius:100px; border:1px solid var(--border);
    background:var(--bg-card); color:var(--text-secondary); font-size:0.8rem;
    cursor:pointer; transition:all 0.2s; font-family:'Inter',sans-serif;
  }}
  .filter-btn:hover, .filter-btn.active {{ border-color:var(--accent-blue); color:var(--accent-blue); background:rgba(59,130,246,0.1); }}

  /* Findings */
  .findings-section {{ max-width:1200px; margin:0 auto; padding:0 2rem 3rem; }}
  .findings-section h2 {{ font-size:1.25rem; font-weight:700; margin-bottom:1.5rem; color:var(--text-secondary); }}
  .finding-card {{
    background:var(--bg-card); border:1px solid var(--border);
    border-radius:16px; padding:1.5rem; margin-bottom:1rem;
    transition:all 0.25s;
  }}
  .finding-card:hover {{ border-color:var(--border-light); transform:translateX(4px); }}
  .finding-header {{ display:flex; align-items:center; gap:0.75rem; margin-bottom:0.75rem; flex-wrap:wrap; }}
  .finding-id {{ font-family:'JetBrains Mono',monospace; font-size:0.8rem; color:var(--text-muted);
    background:rgba(255,255,255,0.05); padding:3px 10px; border-radius:6px; }}
  .severity-badge {{ padding:4px 12px; border-radius:100px; font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; }}
  .finding-title {{ font-size:1rem; font-weight:600; color:var(--text-primary); margin-bottom:1rem; line-height:1.4; }}
  .finding-section {{ margin-bottom:0.75rem; }}
  .section-label {{ font-size:0.75rem; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-muted); margin-bottom:0.4rem; }}
  .evidence-text {{ font-size:0.875rem; color:var(--text-secondary); line-height:1.6; font-style:italic; }}
  .action-text {{ font-size:0.875rem; color:var(--text-primary); line-height:1.6; }}
  .hint-box {{
    background:rgba(59,130,246,0.08); border:1px solid rgba(59,130,246,0.2);
    border-radius:8px; padding:0.75rem 1rem; margin-top:0.5rem;
    font-size:0.8rem; color:var(--text-secondary); font-family:'JetBrains Mono',monospace;
    line-height:1.6; white-space:pre-wrap; word-break:break-all;
  }}
  .hint-label {{ color:var(--accent-blue); font-weight:600; font-family:'Inter',sans-serif; }}
  .finding-meta {{
    display:flex; gap:1.5rem; margin-top:1rem; padding-top:0.75rem;
    border-top:1px solid var(--border); font-size:0.8rem; color:var(--text-muted);
  }}
  .finding-meta code {{ background:rgba(255,255,255,0.06); padding:1px 6px; border-radius:4px;
    font-family:'JetBrains Mono',monospace; font-size:0.75rem; }}

  /* Runtime footer */
  .runtime-bar {{
    background:var(--bg-secondary); border-top:1px solid var(--border);
    padding:1rem 2rem; text-align:center; font-size:0.8rem; color:var(--text-muted);
  }}
  .runtime-bar code {{ font-family:'JetBrains Mono',monospace; color:var(--accent-cyan); }}

  @media(max-width:600px) {{
    .hero h1 {{ font-size:1.75rem; }}
    .summary-grid {{ grid-template-columns:repeat(3,1fr); }}
  }}
</style>
</head>
<body>

<div class="hero">
  <div class="hero-inner">
    <div class="hero-badge">🔍 Brand AI-Readiness Audit v{AUDIT_VERSION}</div>
    <h1>AI Readiness Report</h1>
    <div class="hero-site">{_escape_html(site)}</div>
    <div class="hero-meta">Audited: {audited_at} · Runtime: {elapsed:.1f}s · JS Engine: {js_status}</div>

    <div class="score-section">
      <div class="score-ring-container">
        <svg width="120" height="120" viewBox="0 0 120 120">
          <circle cx="60" cy="60" r="50" fill="none" stroke="#1F2D45" stroke-width="10"/>
          <circle cx="60" cy="60" r="50" fill="none" stroke="{score_color}" stroke-width="10"
            stroke-dasharray="{314.16}" stroke-dashoffset="{314.16 * (1 - score/100):.1f}"
            stroke-linecap="round"/>
        </svg>
        <div class="score-text">
          <div class="score-num" style="color:{score_color}">{score}</div>
          <div class="score-label">Score</div>
        </div>
      </div>
      <div class="score-desc">
        <h2 style="color:{score_color}">{"Excellent" if score >= 80 else "Good" if score >= 60 else "Needs Work" if score >= 40 else "Critical Issues"}</h2>
        <p>{total} total findings · {summary.get("critical",0)} critical · {summary.get("high",0)} high · {proactive_count} proactive improvements</p>
      </div>
    </div>
  </div>
</div>

<div class="summary-grid">
  <div class="summary-card" onclick="filterFindings('critical')" title="Filter Critical">
    <div class="summary-num" style="color:#FF3B30">{critical_count}</div>
    <div class="summary-sev">Critical</div>
  </div>
  <div class="summary-card" onclick="filterFindings('high')" title="Filter High">
    <div class="summary-num" style="color:#FF9500">{high_count}</div>
    <div class="summary-sev">High</div>
  </div>
  <div class="summary-card" onclick="filterFindings('medium')" title="Filter Medium">
    <div class="summary-num" style="color:#FFCC00">{medium_count}</div>
    <div class="summary-sev">Medium</div>
  </div>
  <div class="summary-card" onclick="filterFindings('low')" title="Filter Low">
    <div class="summary-num" style="color:#34C759">{low_count}</div>
    <div class="summary-sev">Low</div>
  </div>
  <div class="summary-card" onclick="filterFindings('proactive')" title="Filter Proactive">
    <div class="summary-num" style="color:#8B5CF6">{proactive_count}</div>
    <div class="summary-sev">Proactive</div>
  </div>
  <div class="summary-card" onclick="filterFindings('all')" title="Show All">
    <div class="summary-num" style="color:#3B82F6">{total}</div>
    <div class="summary-sev">Total</div>
  </div>
</div>

<div class="filter-bar">
  <span class="filter-label">Filter:</span>
  <button class="filter-btn active" onclick="filterFindings('all',this)">All</button>
  <button class="filter-btn" onclick="filterFindings('critical',this)" style="border-color:#FF3B3040">🔴 Critical</button>
  <button class="filter-btn" onclick="filterFindings('high',this)" style="border-color:#FF950040">🟠 High</button>
  <button class="filter-btn" onclick="filterFindings('medium',this)" style="border-color:#FFCC0040">🟡 Medium</button>
  <button class="filter-btn" onclick="filterFindings('low',this)" style="border-color:#34C75940">🟢 Low</button>
  <button class="filter-btn" onclick="filterFindings('proactive',this)" style="border-color:#8B5CF640">✨ Proactive</button>
</div>

<div class="findings-section">
  <h2>Findings ({total})</h2>
  <div id="findings-container">
    {findings_html}
  </div>
</div>

<div class="runtime-bar">
  Brand AI-Readiness Audit v{AUDIT_VERSION} · 
  <code>{site}</code> · 
  Audited at <code>{audited_at}</code> · 
  Runtime: <code>{elapsed:.1f}s</code> · 
  Checks partial: <code>{", ".join(checks_partial) if checks_partial else "none"}</code>
</div>

<script>
function filterFindings(type, btn) {{
  const cards = document.querySelectorAll('.finding-card');
  cards.forEach(card => {{
    if (type === 'all') {{ card.style.display = ''; }}
    else if (type === 'proactive') {{ card.style.display = card.dataset.type === 'proactive' ? '' : 'none'; }}
    else {{ card.style.display = card.dataset.severity === type && card.dataset.type !== 'proactive' ? '' : 'none'; }}
  }});
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
}}
</script>
</body>
</html>"""


def _escape_html(s: str) -> str:
    return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")
