#!/usr/bin/env python3
"""
BLV Semgrep Runner (SAST)
Runs custom Semgrep rules against target source code and produces
a structured report compatible with the BLV dashboard.

Usage:
    python blv_semgrep_runner.py [target_directory]

Example:
    python blv_semgrep_runner.py ./vulnerable_app
"""

import json
import os
import sys
import subprocess
import datetime

# =========================================================
# CONFIG
# =========================================================
TARGET_DIR = sys.argv[1] if len(sys.argv) > 1 else "./vulnerable_app"
RULES_DIR = os.environ.get("SEMGREP_RULES", "./semgrep-rules")
OUTPUT_FILE = os.environ.get("SEMGREP_OUTPUT", "semgrep-report.json")

# =========================================================
# RUN SEMGREP
# =========================================================
def run_semgrep():
    """Execute semgrep with custom BLV rules and return parsed results."""

    print("\n" + "=" * 64)
    print("  BLV SAST Scanner (Semgrep)")
    print("  Static Analysis for Business Logic Vulnerabilities")
    print("=" * 64)
    print(f"\n  Target     : {TARGET_DIR}")
    print(f"  Rules      : {RULES_DIR}")

    cmd = [
        "semgrep",
        "--config", RULES_DIR,
        "--json",
        "--no-git-ignore",
        TARGET_DIR
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )
    except FileNotFoundError:
        print("\n  [ERROR] Semgrep is not installed.")
        print("  Install with: pip install semgrep")
        print("  Or: docker run --rm -v $(pwd):/src semgrep/semgrep semgrep --config ./semgrep-rules /src/vulnerable_app")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("\n  [ERROR] Semgrep scan timed out after 120 seconds.")
        sys.exit(1)

    # Parse JSON output
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"\n  [ERROR] Could not parse Semgrep output")
        print(f"  stderr: {result.stderr[:500]}")
        sys.exit(1)

    return output


# =========================================================
# ANALYZE RESULTS
# =========================================================
def analyze_results(semgrep_output):
    """Parse semgrep findings into BLV-structured report."""

    findings = semgrep_output.get("results", [])
    errors = semgrep_output.get("errors", [])

    print(f"\n  Findings   : {len(findings)}")
    print(f"  Errors     : {len(errors)}")

    # Group by BLV rule ID
    blv_findings = {}
    severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}

    for finding in findings:
        check_id = finding.get("check_id", "unknown")
        message = finding.get("extra", {}).get("message", "No description")
        severity = finding.get("extra", {}).get("severity", "WARNING")
        metadata = finding.get("extra", {}).get("metadata", {})
        path = finding.get("path", "")
        start_line = finding.get("start", {}).get("line", 0)
        end_line = finding.get("end", {}).get("line", 0)
        code_snippet = finding.get("extra", {}).get("lines", "")

        blv_rule_id = metadata.get("blv_rule_id", check_id)
        blv_severity = metadata.get("blv_severity", "MEDIUM").upper()
        category = metadata.get("category", "General")
        cwe = metadata.get("cwe", "")
        impact = metadata.get("impact", "")
        fix = metadata.get("fix", "")

        # Map semgrep severity to BLV severity
        if blv_severity in severity_counts:
            severity_counts[blv_severity] += 1

        if blv_rule_id not in blv_findings:
            blv_findings[blv_rule_id] = {
                "rule_id": blv_rule_id,
                "check_id": check_id,
                "severity": blv_severity,
                "category": category,
                "cwe": cwe,
                "impact": impact,
                "fix": fix,
                "locations": []
            }

        blv_findings[blv_rule_id]["locations"].append({
            "file": path,
            "start_line": start_line,
            "end_line": end_line,
            "code_snippet": code_snippet.strip()[:300],
            "message": message.strip()[:500]
        })

    return blv_findings, severity_counts


def print_report(blv_findings, severity_counts):
    """Print structured SAST report to terminal."""

    print("\n" + "-" * 64)
    print("  SAST FINDINGS")
    print("-" * 64)

    if not blv_findings:
        print("\n  No business logic vulnerabilities found in source code.")
        return

    for rule_id, finding in sorted(blv_findings.items()):
        sev = finding["severity"]
        cat = finding["category"]
        num_locations = len(finding["locations"])

        # Color-coded severity indicator
        sev_indicator = {
            "CRITICAL": "[!!!]",
            "HIGH": "[!! ]",
            "MEDIUM": "[!  ]",
            "LOW": "[   ]"
        }.get(sev, "[   ]")

        print(f"\n  {sev_indicator} {rule_id} [{sev}] — {cat}")

        if finding.get("cwe"):
            print(f"        CWE: {finding['cwe']}")

        for loc in finding["locations"]:
            print(f"        File: {loc['file']}:{loc['start_line']}-{loc['end_line']}")
            if loc.get("code_snippet"):
                for line in loc["code_snippet"].split("\n")[:3]:
                    print(f"          > {line}")

        if finding.get("fix"):
            print(f"        Fix: {finding['fix']}")

    print(f"\n" + "-" * 64)
    print(f"  SEVERITY SUMMARY")
    print(f"    CRITICAL : {severity_counts['CRITICAL']}")
    print(f"    HIGH     : {severity_counts['HIGH']}")
    print(f"    MEDIUM   : {severity_counts['MEDIUM']}")
    print(f"    LOW      : {severity_counts['LOW']}")
    print(f"    Total    : {sum(severity_counts.values())}")
    print("-" * 64)


# =========================================================
# SAVE & SEND REPORT
# =========================================================
def save_report(blv_findings, severity_counts, semgrep_output):
    """Save structured JSON report."""

    report = {
        "scan_type": "SAST",
        "tool": "Semgrep",
        "timestamp": datetime.datetime.now().isoformat(),
        "target": TARGET_DIR,
        "rules_directory": RULES_DIR,
        "total_findings": sum(severity_counts.values()),
        "severity_counts": severity_counts,
        "findings": blv_findings,
        "semgrep_version": semgrep_output.get("version", "unknown"),
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\n  Report saved: {OUTPUT_FILE}")
    return report


def send_to_dashboard(blv_findings, severity_counts):
    """Send SAST results to dashboard API."""

    api_url = os.getenv("CI_RESULT_API")
    if not api_url:
        print("  CI_RESULT_API not set, skipping dashboard API")
        return

    import requests

    failed_ids = list(blv_findings.keys())
    failed_reasons = {}
    failed_evidence = {}

    for rid, finding in blv_findings.items():
        reasons = []
        for loc in finding["locations"]:
            reasons.append(f"{loc['file']}:{loc['start_line']} — {loc['message'][:100]}")
        failed_reasons[rid] = " | ".join(reasons)

        failed_evidence[rid] = {
            "scan_type": "SAST",
            "tool": "Semgrep",
            "locations": finding["locations"],
            "cwe": finding.get("cwe", ""),
            "fix": finding.get("fix", ""),
        }

    total_rules_checked = len(blv_findings) + 1  # approximation
    passed_count = max(0, total_rules_checked - len(failed_ids))

    payload = {
        "run_id": os.getenv("GITHUB_RUN_ID", f"sast-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"),
        "commit_sha": os.getenv("GITHUB_SHA", "local"),
        "branch": os.getenv("GITHUB_REF_NAME", "local"),
        "status": "FAIL" if blv_findings else "PASS",
        "passed_rules": passed_count,
        "failed_rules": len(failed_ids),
        "failed_rule_details": ", ".join(failed_ids) if failed_ids else None,
        "failed_rule_reasons": failed_reasons,
        "failed_rule_evidence": failed_evidence,
        "security_score": max(0, 100 - (severity_counts["CRITICAL"] * 25 + severity_counts["HIGH"] * 15 + severity_counts["MEDIUM"] * 8 + severity_counts["LOW"] * 3)),
        "score_grade": "F" if severity_counts["CRITICAL"] > 0 else ("D" if severity_counts["HIGH"] > 0 else ("C" if severity_counts["MEDIUM"] > 0 else "A")),
        "quality_gate_passed": severity_counts["CRITICAL"] == 0 and severity_counts["HIGH"] == 0,
        "quality_gate_reasons": ["SAST scan — Semgrep static analysis"],
        "regressions": [],
        "fixed": [],
        "category_summary": {},
    }

    try:
        r = requests.post(api_url, json=payload, timeout=10)
        print(f"  SAST result sent to dashboard -> {r.status_code}")
    except Exception as e:
        print(f"  Failed to send SAST result: {e}")


# =========================================================
# GATE DECISION
# =========================================================
def should_block(severity_counts):
    """Block CI if CRITICAL or HIGH findings exist in SAST."""
    if severity_counts.get("CRITICAL", 0) > 0:
        return True
    if severity_counts.get("HIGH", 0) > 0:
        return True
    return False


# =========================================================
# MAIN
# =========================================================
def main():
    semgrep_output = run_semgrep()
    blv_findings, severity_counts = analyze_results(semgrep_output)
    print_report(blv_findings, severity_counts)
    save_report(blv_findings, severity_counts, semgrep_output)
    send_to_dashboard(blv_findings, severity_counts)

    total = sum(severity_counts.values())

    if total == 0:
        print("\n  SAST PASSED — No business logic issues found in source code")
        sys.exit(0)

    if should_block(severity_counts):
        print(f"\n  SAST BLOCKED — {severity_counts['CRITICAL']} CRITICAL, {severity_counts['HIGH']} HIGH findings")
        sys.exit(1)

    print(f"\n  SAST WARNING — {total} findings (no CRITICAL/HIGH, not blocking)")
    sys.exit(0)


if __name__ == "__main__":
    main()
