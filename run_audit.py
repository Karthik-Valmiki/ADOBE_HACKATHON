#!/usr/bin/env python3
"""
run_audit.py — Brand AI Readiness Audit convenience runner.

Usage:
    python run_audit.py <url> [--format json|markdown] [--output <file>]

Examples:
    python run_audit.py https://adobe.com
    python run_audit.py https://adobe.com --format markdown
    python run_audit.py https://adobe.com --output report.json
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

# Resolve the orchestrator module path
_ROOT = Path(__file__).parent
_SCRIPTS = _ROOT / "skills" / "audit-orchestrator" / "scripts"
sys.path.insert(0, str(_SCRIPTS))


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Brand AI Readiness Audit — run a full audit on any URL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("url", help="Target URL to audit (e.g. https://example.com)")
    parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format: json (default) or markdown summary",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Write output to FILE instead of stdout",
    )
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # Import after path setup
    from audit_orchestrator import orchestrate  # type: ignore[import]

    print(f"[*] Starting Brand AI Readiness Audit for: {args.url}", file=sys.stderr)
    print(f"[*] Output format: {args.format}", file=sys.stderr)

    try:
        report = await orchestrate(args.url)
    except Exception as exc:
        print(f"[!] Audit failed with exception: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.format == "markdown":
        output_text = _render_markdown(report)
    else:
        output_text = json.dumps(report, indent=2, ensure_ascii=True)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(output_text, encoding="utf-8")
        print(f"[+] Report written to: {out_path.resolve()}", file=sys.stderr)
    else:
        print(output_text)


def _render_markdown(report: dict) -> str:
    """Render a Markdown summary of the audit report for human-readable output."""
    url = report.get("site", report.get("url", ""))
    ts = report.get("audited_at", "")
    runtime_meta = report.get("runtime_meta", {})
    # Field name is elapsed_seconds in the actual serializer output
    duration = runtime_meta.get("elapsed_seconds", runtime_meta.get("duration_seconds", 0))
    findings = report.get("findings", [])
    summary = report.get("summary", {})

    # Score: computed from defect severity counts (proactive findings do not penalise)
    critical = summary.get("critical", 0)
    high = summary.get("high", 0)
    medium = summary.get("medium", 0)
    low_c = summary.get("low", 0)
    penalty = critical * 20 + high * 8 + medium * 3 + low_c * 1
    score = max(0, 100 - penalty)

    if score >= 80:
        band, emoji = "Excellent", "🟢"
    elif score >= 60:
        band, emoji = "Good", "🟡"
    elif score >= 40:
        band, emoji = "Fair", "🟠"
    else:
        band, emoji = "Poor", "🔴"

    lines = [
        "# Brand AI Readiness Audit",
        "",
        f"**URL**: {url}  ",
        f"**Audited at**: {ts}  ",
        f"**Duration**: {duration:.1f}s",
        "",
        "## AI Readiness Score",
        "",
        f"> {emoji} **{score}/100** — {band}",
        "",
        "## Findings Summary",
        "",
        "| Severity | Count |",
        "|----------|-------|",
    ]

    for sev, cnt in [("Critical", critical), ("High", high), ("Medium", medium), ("Low", low_c)]:
        if cnt > 0:
            lines.append(f"| {sev} | {cnt} |")

    lines += ["", "## Top Findings", ""]

    SORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_findings = sorted(findings, key=lambda f: SORDER.get(f.get("severity", "low"), 9))
    for f in sorted_findings[:10]:
        sev = f.get("severity", "low").upper()
        fid = f.get("id", "")
        title = f.get("title", "")
        sa = f.get("suggested_action", {})
        action = sa.get("summary", "") if isinstance(sa, dict) else ""
        lines.append(f"### [{sev}] {fid} — {title}")
        lines.append("")
        lines.append(f"**Evidence**: {str(f.get('evidence', ''))[:300]}")
        lines.append("")
        if action:
            lines.append(f"**Recommended action**: {action}")
        lines.append("")

    if not sorted_findings:
        lines.append("✅ No defects found. All checks passed.")
        lines.append("")

    # Cross-web corroboration summary (uses actual report field names)
    corr = report.get("cross_web_corroboration", {})
    if corr:
        lines += ["## Cross-Web Corroboration", ""]
        status = corr.get("corroboration_status", "unknown")
        brand = corr.get("brand_name", "")
        qid = corr.get("wikidata_qid")
        entity_found = corr.get("wikidata_entity_found", False)
        offsite_year = corr.get("offsite_year_max")
        offsite_price = corr.get("offsite_price_str", "")

        if entity_found and qid:
            lines.append(f"- ✅ Brand '{brand}' corroborated in Wikidata (QID: {qid})")
        elif status == "ok":
            lines.append(f"- ✅ Brand '{brand}' found in corroboration sources")
        elif status in ("rate_limited", "blocked"):
            lines.append(f"- ⚠️ Corroboration check returned status '{status}' — results unverified")
        else:
            lines.append(f"- ❌ Brand '{brand}' not found in Wikidata knowledge graph")

        if offsite_year:
            lines.append(f"- Most recent off-site year mention: {offsite_year}")
        if offsite_price:
            lines.append(f"- Off-site price reference: {offsite_price}")
        lines.append("")

    lines += [
        "---",
        "*Generated by Brand AI Readiness Audit v2.0.0*",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    asyncio.run(main())

