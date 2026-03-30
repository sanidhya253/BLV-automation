from io import BytesIO
import os
import json
import sqlite3

from flask import Flask, request, jsonify, render_template, send_file

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

# -----------------------------
# Paths
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "ci_results.db")
RULE_FILE = os.path.join(BASE_DIR, "rules", "final_business_logic_rules.json")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    import psycopg2

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))


# -----------------------------
# Rule helpers
# -----------------------------
def load_rule_severity_map():
    try:
        with open(RULE_FILE, "r", encoding="utf-8") as f:
            rules = json.load(f).get("rules", [])
        return {r.get("rule_id"): (r.get("severity") or "LOW").upper() for r in rules}
    except Exception as e:
        print("Severity map load error:", e)
        return {}


def load_rules_index():
    try:
        with open(RULE_FILE, "r", encoding="utf-8") as f:
            rules = json.load(f).get("rules", [])
        idx = {}
        for r in rules:
            rid = r.get("rule_id")
            if rid:
                idx[rid] = {
                    "name": r.get("name", ""),
                    "endpoint": r.get("endpoint", ""),
                    "severity": (r.get("severity") or "LOW").upper(),
                    "category": r.get("category", "General"),
                    "description": r.get("description", ""),
                    "expected_behavior": r.get("expected_behavior") or {},
                }
        return idx
    except Exception as e:
        print("Rule index load error:", e)
        return {}


def load_quality_gate_config():
    try:
        with open(RULE_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("quality_gate", {})
    except Exception:
        return {}


# -----------------------------
# DB helpers
# -----------------------------
def get_db():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL)
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_db()
    cur = conn.cursor()

    if DATABASE_URL:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ci_results (
                id SERIAL PRIMARY KEY,
                run_id TEXT,
                commit_sha TEXT,
                branch TEXT,
                status TEXT,
                passed_rules INTEGER,
                failed_rules INTEGER,
                failed_rule_details TEXT,
                failed_rule_reasons TEXT,
                failed_rule_evidence TEXT,
                security_score REAL DEFAULT 0,
                score_grade TEXT DEFAULT 'F',
                quality_gate_passed BOOLEAN DEFAULT FALSE,
                quality_gate_reasons TEXT,
                regressions TEXT,
                fixed_rules TEXT,
                category_summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ci_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                commit_sha TEXT,
                branch TEXT,
                status TEXT,
                passed_rules INTEGER,
                failed_rules INTEGER,
                failed_rule_details TEXT,
                failed_rule_reasons TEXT,
                failed_rule_evidence TEXT,
                security_score REAL DEFAULT 0,
                score_grade TEXT DEFAULT 'F',
                quality_gate_passed BOOLEAN DEFAULT 0,
                quality_gate_reasons TEXT,
                regressions TEXT,
                fixed_rules TEXT,
                category_summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # Safe migrations for older DBs
    new_cols = [
        ("security_score", "REAL DEFAULT 0"),
        ("score_grade", "TEXT DEFAULT 'F'"),
        ("quality_gate_passed", "BOOLEAN DEFAULT FALSE"),
        ("quality_gate_reasons", "TEXT"),
        ("regressions", "TEXT"),
        ("fixed_rules", "TEXT"),
        ("category_summary", "TEXT"),
        ("failed_rule_evidence", "TEXT"),
    ]
    for col_name, col_type in new_cols:
        try:
            cur.execute(f"ALTER TABLE ci_results ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
            conn.commit()
        except Exception:
            conn.rollback()

    conn.commit()
    conn.close()


def fetch_run_by_run_id(run_id):
    conn = get_db()
    cur = conn.cursor()
    placeholder = "%s" if DATABASE_URL else "?"
    cur.execute(f"""
        SELECT run_id, commit_sha, branch, status,
               passed_rules, failed_rules, failed_rule_details,
               created_at, failed_rule_reasons, failed_rule_evidence,
               security_score, score_grade, quality_gate_passed,
               quality_gate_reasons, regressions, fixed_rules, category_summary
        FROM ci_results
        WHERE run_id = {placeholder}
        ORDER BY created_at DESC LIMIT 1
    """, (run_id,))
    row = cur.fetchone()
    conn.close()
    return row


def fetch_previous_scan(current_run_id):
    """Fetch the scan immediately before the given run_id."""
    conn = get_db()
    cur = conn.cursor()
    placeholder = "%s" if DATABASE_URL else "?"

    # Get the created_at of current run
    cur.execute(f"""
        SELECT created_at FROM ci_results
        WHERE run_id = {placeholder}
        ORDER BY created_at DESC LIMIT 1
    """, (current_run_id,))
    current = cur.fetchone()

    if not current:
        conn.close()
        return None

    # Get the run right before this one
    cur.execute(f"""
        SELECT run_id, commit_sha, branch, status,
               passed_rules, failed_rules, failed_rule_details,
               created_at, failed_rule_reasons, failed_rule_evidence,
               security_score, score_grade, quality_gate_passed,
               quality_gate_reasons, regressions, fixed_rules, category_summary
        FROM ci_results
        WHERE created_at < {placeholder}
        ORDER BY created_at DESC LIMIT 1
    """, (current[0],))
    row = cur.fetchone()
    conn.close()
    return row


def build_comparison(current_row, previous_row, rules_idx):
    """Build a comparison dict between current and previous scan."""
    if not previous_row:
        return None

    # Current scan failed rule IDs
    curr_failed_str = current_row[6] or ""
    curr_failed = {x.strip() for x in curr_failed_str.split(",") if x.strip()}

    # Previous scan failed rule IDs
    prev_failed_str = previous_row[6] or ""
    prev_failed = {x.strip() for x in prev_failed_str.split(",") if x.strip()}

    # All rule IDs
    all_rules = set(rules_idx.keys())

    curr_passed = all_rules - curr_failed
    prev_passed = all_rules - prev_failed

    # Classify each rule
    still_failing = curr_failed & prev_failed
    regressions = curr_failed - prev_failed  # was passing, now failing
    fixed = prev_failed - curr_failed         # was failing, now passing
    still_passing = curr_passed & prev_passed

    # Score comparison
    curr_score = float(current_row[10] or 0)
    prev_score = float(previous_row[10] or 0)
    score_change = curr_score - prev_score

    # Build rule-level comparison table
    rule_comparison = []
    for rid in sorted(all_rules):
        rinfo = rules_idx.get(rid, {})
        prev_status = "FAIL" if rid in prev_failed else "PASS"
        curr_status = "FAIL" if rid in curr_failed else "PASS"

        if rid in regressions:
            change = "REGRESSION"
        elif rid in fixed:
            change = "FIXED"
        elif rid in still_failing:
            change = "STILL FAILING"
        else:
            change = "STABLE"

        rule_comparison.append({
            "rule_id": rid,
            "name": rinfo.get("name", "Unknown"),
            "severity": rinfo.get("severity", "LOW"),
            "category": rinfo.get("category", "General"),
            "previous": prev_status,
            "current": curr_status,
            "change": change,
        })

    return {
        "previous_run_id": previous_row[0],
        "previous_date": str(previous_row[7]),
        "previous_score": prev_score,
        "previous_grade": previous_row[11] or "F",
        "previous_passed": int(previous_row[4] or 0),
        "previous_failed": int(previous_row[5] or 0),
        "previous_gate": bool(previous_row[12]),
        "current_score": curr_score,
        "current_grade": current_row[11] or "F",
        "score_change": round(score_change, 1),
        "total_regressions": len(regressions),
        "total_fixed": len(fixed),
        "total_still_failing": len(still_failing),
        "total_still_passing": len(still_passing),
        "rules": rule_comparison,
    }


# -----------------------------
# API routes
# -----------------------------
@app.route("/api/ci-results", methods=["GET"])
def get_ci_results():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT run_id, commit_sha, branch, status,
               passed_rules, failed_rules, failed_rule_details,
               created_at, failed_rule_reasons, failed_rule_evidence,
               security_score, score_grade, quality_gate_passed,
               quality_gate_reasons, regressions, fixed_rules, category_summary
        FROM ci_results
        ORDER BY created_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return jsonify(rows)


@app.route("/api/ci-results", methods=["POST"])
def add_ci_result():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    required = ["run_id", "commit_sha", "branch", "status", "passed_rules", "failed_rules"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing field: {field}"}), 400

    # Reasons
    reasons_dict = data.get("failed_rule_reasons") or {}
    if isinstance(reasons_dict, dict) and reasons_dict:
        reasons_str = "||".join([f"{k}: {v}" for k, v in reasons_dict.items()])
    elif isinstance(reasons_dict, str) and reasons_dict.strip():
        reasons_str = reasons_dict.strip()
    else:
        reasons_str = None

    # Evidence
    evidence_obj = data.get("failed_rule_evidence") or {}
    evidence_str = json.dumps(evidence_obj) if isinstance(evidence_obj, (dict, list)) else (evidence_obj or None)

    # Quality gate reasons
    qg_reasons = data.get("quality_gate_reasons") or []
    qg_reasons_str = json.dumps(qg_reasons) if isinstance(qg_reasons, list) else (qg_reasons or None)

    # Regressions & fixed
    regressions = data.get("regressions") or []
    regressions_str = json.dumps(regressions) if isinstance(regressions, list) else (regressions or None)

    fixed = data.get("fixed") or []
    fixed_str = json.dumps(fixed) if isinstance(fixed, list) else (fixed or None)

    # Category summary
    cat_summary = data.get("category_summary") or {}
    cat_str = json.dumps(cat_summary) if isinstance(cat_summary, dict) else (cat_summary or None)

    try:
        conn = get_db()
        cur = conn.cursor()
        placeholder = "%s" if DATABASE_URL else "?"
        placeholders = ", ".join([placeholder] * 16)
        cur.execute(f"""
            INSERT INTO ci_results
            (run_id, commit_sha, branch, status, passed_rules, failed_rules,
             failed_rule_details, failed_rule_reasons, failed_rule_evidence,
             security_score, score_grade, quality_gate_passed,
             quality_gate_reasons, regressions, fixed_rules, category_summary)
            VALUES ({placeholders})
        """, (
            data["run_id"],
            data["commit_sha"],
            data["branch"],
            data["status"],
            int(data["passed_rules"]),
            int(data["failed_rules"]),
            data.get("failed_rule_details"),
            reasons_str,
            evidence_str,
            float(data.get("security_score", 0)),
            data.get("score_grade", "F"),
            bool(data.get("quality_gate_passed", False)),
            qg_reasons_str,
            regressions_str,
            fixed_str,
            cat_str,
        ))
        conn.commit()
        conn.close()
        return jsonify({"message": "CI result stored"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return {"status": "BLV CI Dashboard API running", "version": "2.0"}


@app.route("/")
@app.route("/dashboard")
def dashboard():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT run_id, commit_sha, branch, status,
               passed_rules, failed_rules, failed_rule_details,
               created_at, failed_rule_reasons, failed_rule_evidence,
               security_score, score_grade, quality_gate_passed,
               quality_gate_reasons, regressions, fixed_rules, category_summary
        FROM ci_results
        ORDER BY created_at DESC
    """)
    results = cur.fetchall()
    conn.close()

    rules_idx = load_rules_index()
    gate_config = load_quality_gate_config()

    return render_template("dashboard.html",
        results=results,
        rules_index=rules_idx,
        gate_config=gate_config)


# -----------------------------
# Comparison API
# -----------------------------
@app.route("/api/compare/<run_id>", methods=["GET"])
def compare_scan(run_id):
    """Compare a scan with its previous scan."""
    current = fetch_run_by_run_id(run_id)
    if not current:
        return jsonify({"error": "Run not found"}), 404

    previous = fetch_previous_scan(run_id)
    rules_idx = load_rules_index()
    comparison = build_comparison(current, previous, rules_idx)

    if not comparison:
        return jsonify({"error": "No previous scan to compare with"}), 404

    return jsonify(comparison), 200


# -----------------------------
# Score History API
# -----------------------------
@app.route("/api/stats/score-history", methods=["GET"])
def stats_score_history():
    conn = get_db()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("""
            SELECT run_id, security_score, score_grade, created_at
            FROM ci_results
            WHERE created_at >= (CURRENT_DATE - INTERVAL '30 days')
            ORDER BY created_at ASC
        """)
    else:
        cur.execute("""
            SELECT run_id, security_score, score_grade, created_at
            FROM ci_results
            WHERE DATE(created_at) >= DATE('now', '-30 day')
            ORDER BY created_at ASC
        """)
    rows = cur.fetchall()
    conn.close()
    data = [{"run_id": r[0], "score": r[1] or 0, "grade": r[2] or "F", "date": str(r[3])} for r in rows]
    return jsonify(data), 200


# -----------------------------
# Reports
# -----------------------------
@app.route("/report/<run_id>.json", methods=["GET"])
def download_report_json(run_id):
    row = fetch_run_by_run_id(run_id)
    if not row:
        return jsonify({"error": "Run not found"}), 404

    # Parse JSON fields safely
    def safe_json(val):
        if not val:
            return None
        try:
            return json.loads(val)
        except Exception:
            return val

    report = {
        "run_id": row[0],
        "commit_sha": row[1],
        "branch": row[2],
        "status": row[3],
        "passed_rules": row[4],
        "failed_rules": row[5],
        "failed_rule_details": row[6],
        "created_at": str(row[7]),
        "failed_rule_reasons": row[8],
        "failed_rule_evidence": safe_json(row[9]),
        "security_score": row[10],
        "score_grade": row[11],
        "quality_gate_passed": row[12],
        "quality_gate_reasons": safe_json(row[13]),
        "regressions": safe_json(row[14]),
        "fixed_rules": safe_json(row[15]),
        "category_summary": safe_json(row[16]),
    }
    return jsonify(report), 200


@app.route("/report/<run_id>.pdf", methods=["GET"])
def download_report_pdf(run_id):
    row = fetch_run_by_run_id(run_id)
    if not row:
        return jsonify({"error": "Run not found"}), 404

    run_id_val = row[0]
    commit_sha = row[1]
    branch = row[2]
    status = row[3]
    passed_rules = row[4]
    failed_rules = row[5]
    failed_rule_details = row[6]
    created_at = row[7]
    failed_rule_reasons = row[8]
    failed_rule_evidence = row[9]
    security_score = row[10] or 0
    score_grade = row[11] or "F"
    quality_gate_passed = row[12]
    quality_gate_reasons_raw = row[13]
    regressions_raw = row[14]
    fixed_raw = row[15]
    category_summary_raw = row[16]

    rules_idx = load_rules_index()

    # Parse fields
    reasons_map = {}
    if failed_rule_reasons:
        for part in str(failed_rule_reasons).split("||"):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                rid, reason = part.split(":", 1)
                reasons_map[rid.strip()] = reason.strip()

    evidence_map = {}
    if failed_rule_evidence:
        try:
            evidence_map = json.loads(failed_rule_evidence)
        except Exception:
            pass

    failed_ids = []
    if failed_rule_details:
        failed_ids = [x.strip() for x in str(failed_rule_details).split(",") if x.strip()]

    total_rules = int(passed_rules or 0) + int(failed_rules or 0)

    sev_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for rid in failed_ids:
        sev = (rules_idx.get(rid, {}).get("severity") or "LOW").upper()
        if sev not in sev_counts:
            sev = "LOW"
        sev_counts[sev] += 1

    qg_reasons = []
    if quality_gate_reasons_raw:
        try:
            qg_reasons = json.loads(quality_gate_reasons_raw)
        except Exception:
            pass

    regressions = []
    if regressions_raw:
        try:
            regressions = json.loads(regressions_raw)
        except Exception:
            pass

    fixed_list = []
    if fixed_raw:
        try:
            fixed_list = json.loads(fixed_raw)
        except Exception:
            pass

    # Build PDF
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10, leading=14)
    mono = ParagraphStyle("mono", parent=styles["BodyText"], fontName="Courier", fontSize=9, leading=12)

    story = []

    # Title
    story.append(Paragraph("BLV CI Scan Report", h1))
    story.append(Paragraph("Business Logic Vulnerability Automation Framework v2.0", body))
    story.append(Spacer(1, 10))

    # Metadata
    meta_tbl = [
        ["Run ID", str(run_id_val)],
        ["Commit SHA", str(commit_sha)],
        ["Branch", str(branch)],
        ["Status", str(status)],
        ["Security Score", f"{security_score}/100 (Grade: {score_grade})"],
        ["Quality Gate", "PASSED" if quality_gate_passed else "FAILED"],
        ["Created At", str(created_at)],
    ]
    t = Table(meta_tbl, colWidths=[4*cm, 11*cm])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
    ]))
    story.append(t)
    story.append(Spacer(1, 14))

    # Quality Gate
    story.append(Paragraph("Quality Gate", h2))
    gate_status = "PASSED" if quality_gate_passed else "FAILED"
    story.append(Paragraph(f"Status: <b>{gate_status}</b>", body))
    if qg_reasons:
        for reason in qg_reasons:
            story.append(Paragraph(f"&bull; {reason}", body))
    story.append(Spacer(1, 10))

    # Regressions
    if regressions:
        story.append(Paragraph("Regressions Detected", h2))
        story.append(Paragraph(
            "The following rules were passing in the previous scan but are now failing:", body))
        for rid in regressions:
            rname = rules_idx.get(rid, {}).get("name", "Unknown")
            story.append(Paragraph(f"&bull; <b>{rid}</b> — {rname}", body))
        story.append(Spacer(1, 10))

    if fixed_list:
        story.append(Paragraph("Fixed Since Last Scan", h2))
        for rid in fixed_list:
            rname = rules_idx.get(rid, {}).get("name", "Unknown")
            story.append(Paragraph(f"&bull; <b>{rid}</b> — {rname}", body))
        story.append(Spacer(1, 10))

    # ── COMPARATIVE ANALYSIS ──
    prev_row = fetch_previous_scan(run_id_val)
    if prev_row:
        comparison = build_comparison(row, prev_row, rules_idx)
        if comparison:
            story.append(Paragraph("Comparative Analysis (Current vs Previous Scan)", h2))

            # Score comparison
            score_arrow = "+" if comparison["score_change"] > 0 else ""
            score_color = "green" if comparison["score_change"] >= 0 else "red"

            comp_summary = [
                ["Metric", "Previous Scan", "Current Scan", "Change"],
                ["Run ID", str(comparison["previous_run_id"])[:20], str(run_id_val)[:20], ""],
                ["Date", str(comparison["previous_date"])[:19], str(created_at)[:19], ""],
                ["Security Score",
                    f"{comparison['previous_score']}/100 ({comparison['previous_grade']})",
                    f"{comparison['current_score']}/100 ({comparison['current_grade']})",
                    f"{score_arrow}{comparison['score_change']}"],
                ["Passed Rules", str(comparison["previous_passed"]), str(passed_rules), ""],
                ["Failed Rules", str(comparison["previous_failed"]), str(failed_rules), ""],
                ["Quality Gate",
                    "PASSED" if comparison["previous_gate"] else "FAILED",
                    "PASSED" if quality_gate_passed else "FAILED", ""],
            ]

            comp_tbl = Table(comp_summary, colWidths=[3.5*cm, 4.5*cm, 4.5*cm, 2.5*cm])
            comp_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 1), (0, -1), colors.whitesmoke),
            ]))
            story.append(comp_tbl)
            story.append(Spacer(1, 10))

            # Change summary
            story.append(Paragraph(
                f"<b>Regressions:</b> {comparison['total_regressions']} &nbsp;&nbsp; "
                f"<b>Fixed:</b> {comparison['total_fixed']} &nbsp;&nbsp; "
                f"<b>Still Failing:</b> {comparison['total_still_failing']} &nbsp;&nbsp; "
                f"<b>Stable (Passing):</b> {comparison['total_still_passing']}", body))
            story.append(Spacer(1, 8))

            # Rule-by-rule comparison table
            story.append(Paragraph("Rule-by-Rule Comparison", h2))

            rule_comp_data = [["Rule ID", "Name", "Severity", "Previous", "Current", "Status"]]
            for rc in comparison["rules"]:
                change_label = rc["change"]
                rule_comp_data.append([
                    rc["rule_id"],
                    rc["name"][:30],
                    rc["severity"],
                    rc["previous"],
                    rc["current"],
                    change_label,
                ])

            rule_comp_tbl = Table(rule_comp_data, colWidths=[2.5*cm, 4*cm, 2*cm, 2*cm, 2*cm, 2.5*cm])

            # Color rows based on change status
            rule_style = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]

            for i, rc in enumerate(comparison["rules"], start=1):
                if rc["change"] == "REGRESSION":
                    rule_style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fef2f2")))
                    rule_style.append(("TEXTCOLOR", (5, i), (5, i), colors.HexColor("#dc2626")))
                elif rc["change"] == "FIXED":
                    rule_style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f0fdf4")))
                    rule_style.append(("TEXTCOLOR", (5, i), (5, i), colors.HexColor("#16a34a")))
                elif rc["change"] == "STILL FAILING":
                    rule_style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fff7ed")))
                    rule_style.append(("TEXTCOLOR", (5, i), (5, i), colors.HexColor("#ea580c")))

            rule_comp_tbl.setStyle(TableStyle(rule_style))
            story.append(rule_comp_tbl)
            story.append(Spacer(1, 14))
    else:
        story.append(Paragraph("Comparative Analysis", h2))
        story.append(Paragraph(
            "No previous scan available for comparison. Run the validator again to see "
            "a side-by-side comparison of results.", body))
        story.append(Spacer(1, 10))

    # Executive Summary
    story.append(Paragraph("Executive Summary", h2))
    summary_text = (
        f"This automated CI scan validated <b>{total_rules}</b> business logic rules. "
        f"The security score is <b>{security_score}/100 (Grade {score_grade})</b>. "
        f"<b>{passed_rules}</b> rules passed and <b>{failed_rules}</b> failed. "
    )
    story.append(Paragraph(summary_text, body))
    story.append(Spacer(1, 10))

    # Overview
    story.append(Paragraph("Results Overview", h2))
    overview = [
        ["Metric", "Value"],
        ["Total Rules", str(total_rules)],
        ["Passed", str(passed_rules)],
        ["Failed", str(failed_rules)],
        ["Security Score", f"{security_score}/100"],
        ["Critical Failures", str(sev_counts["CRITICAL"])],
        ["High Failures", str(sev_counts["HIGH"])],
        ["Medium Failures", str(sev_counts["MEDIUM"])],
        ["Low Failures", str(sev_counts["LOW"])],
    ]
    t2 = Table(overview, colWidths=[6*cm, 9*cm])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.black),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
    ]))
    story.append(t2)
    story.append(Spacer(1, 14))

    # Detailed Findings
    story.append(Paragraph("Detailed Findings", h2))
    if not failed_ids:
        story.append(Paragraph("No failed rules were recorded for this run.", body))
    else:
        for rid in failed_ids:
            rmeta = rules_idx.get(rid, {})
            name = rmeta.get("name", "Unknown Rule")
            endpoint = rmeta.get("endpoint", "-")
            sev = rmeta.get("severity", "LOW")
            desc = rmeta.get("description", "")
            expected = rmeta.get("expected_behavior", {})
            observed = reasons_map.get(rid, "No reason recorded.")

            is_regression = rid in regressions

            title_prefix = "[REGRESSION] " if is_regression else ""
            story.append(Paragraph(f"<b>{title_prefix}{rid}</b> — {name}", body))
            story.append(Paragraph(
                f"<b>Severity:</b> {sev} &nbsp;&nbsp; "
                f"<b>Category:</b> {rmeta.get('category', 'General')} &nbsp;&nbsp; "
                f"<b>Endpoint:</b> <font name='Courier'>{endpoint}</font>",
                body
            ))
            if desc:
                story.append(Paragraph(f"<i>{desc}</i>", body))
            story.append(Spacer(1, 4))

            exp_txt = json.dumps(expected, indent=2) if expected else \
                "As per rule definition."
            finding_tbl = Table([
                ["Expected Behavior", "Observed Behavior"],
                [Paragraph(f"<pre>{exp_txt}</pre>", mono), Paragraph(observed, body)]
            ], colWidths=[7.2*cm, 7.8*cm])
            finding_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(finding_tbl)
            story.append(Spacer(1, 6))

            # Evidence
            ev = {}
            if isinstance(evidence_map, dict):
                ev = evidence_map.get(rid, {}) or {}

            if ev:
                story.append(Paragraph("<b>Evidence (Proof)</b>", body))
                story.append(Paragraph(
                    f"<b>Endpoint:</b> <font name='Courier'>{ev.get('endpoint', endpoint)}</font><br/>"
                    f"<b>Status Code:</b> {ev.get('status_code', '-')}<br/>"
                    f"<b>Request Payload:</b> <font name='Courier'>{json.dumps(ev.get('request_payload', {}))[:400]}</font><br/>"
                    f"<b>Response Snippet:</b> {ev.get('response_snippet', '')}",
                    body
                ))
                story.append(Spacer(1, 6))

            story.append(Paragraph(
                "<b>Impact:</b> Attackers can abuse this logic flaw to bypass intended business constraints, "
                "causing financial loss or unauthorized access.", body))
            story.append(Paragraph("<b>Recommendation:</b>", body))
            recs = [
                "Validate inputs strictly on the server side.",
                "Enforce workflow state checks.",
                "Apply authorization controls for privileged endpoints.",
                "Add unit/integration tests to prevent regression.",
            ]
            for rline in recs:
                story.append(Paragraph(f"&bull; {rline}", body))
            story.append(Spacer(1, 12))

    story.append(Paragraph(
        "Generated automatically by BLV Automation Framework v2.0 (CI/CD).",
        ParagraphStyle("foot", parent=body, textColor=colors.grey, fontSize=9)
    ))

    doc.build(story)
    buf.seek(0)

    return send_file(buf, mimetype="application/pdf", as_attachment=True,
        download_name=f"blv_report_{run_id_val}.pdf")


# -----------------------------
# Chart stats
# -----------------------------
@app.route("/api/stats/daily", methods=["GET"])
def stats_daily():
    conn = get_db()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("""
            SELECT DATE(created_at) AS d,
                   SUM(CASE WHEN status = 'PASS' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN status = 'FAIL' THEN 1 ELSE 0 END)
            FROM ci_results
            WHERE created_at >= (CURRENT_DATE - INTERVAL '13 days')
            GROUP BY d ORDER BY d ASC
        """)
    else:
        cur.execute("""
            SELECT DATE(created_at) AS d,
                   SUM(CASE WHEN status = 'PASS' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN status = 'FAIL' THEN 1 ELSE 0 END)
            FROM ci_results
            WHERE DATE(created_at) >= DATE('now', '-13 day')
            GROUP BY d ORDER BY d ASC
        """)
    rows = cur.fetchall()
    conn.close()
    return jsonify([{"date": str(d), "pass": int(p or 0), "fail": int(f or 0)} for d, p, f in rows]), 200


@app.route("/api/stats/severity", methods=["GET"])
def stats_severity():
    try:
        sev_map = load_rule_severity_map()
        conn = get_db()
        cur = conn.cursor()
        if DATABASE_URL:
            cur.execute("""
                SELECT failed_rule_details FROM ci_results
                WHERE status = 'FAIL'
                  AND created_at >= (CURRENT_DATE - INTERVAL '13 days')
                  AND failed_rule_details IS NOT NULL
            """)
        else:
            cur.execute("""
                SELECT failed_rule_details FROM ci_results
                WHERE status = 'FAIL'
                  AND DATE(created_at) >= DATE('now', '-13 day')
                  AND failed_rule_details IS NOT NULL
            """)
        rows = cur.fetchall()
        conn.close()

        counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for (details,) in rows:
            if not details:
                continue
            for rid in str(details).split(","):
                rid = rid.strip()
                if not rid:
                    continue
                sev = (sev_map.get(rid, "LOW") or "LOW").upper()
                if sev not in counts:
                    sev = "LOW"
                counts[sev] += 1
        return jsonify(counts), 200
    except Exception as e:
        print("Severity stats error:", e)
        return jsonify({"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}), 200


@app.route("/api/stats/rule-frequency", methods=["GET"])
def stats_rule_frequency():
    """Returns how many times each rule ID has failed across all scans."""
    try:
        rules_idx = load_rules_index()
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT failed_rule_details FROM ci_results
            WHERE failed_rule_details IS NOT NULL
        """)
        rows = cur.fetchall()
        conn.close()

        # Count failures per rule
        fail_counts = {}
        for (details,) in rows:
            if not details:
                continue
            for rid in str(details).split(","):
                rid = rid.strip()
                if not rid:
                    continue
                fail_counts[rid] = fail_counts.get(rid, 0) + 1

        # Build response with all rules (0 if never failed)
        result = []
        for rid, info in sorted(rules_idx.items()):
            result.append({
                "rule_id": rid,
                "name": info.get("name", ""),
                "severity": info.get("severity", "LOW"),
                "fail_count": fail_counts.get(rid, 0)
            })

        return jsonify(result), 200
    except Exception as e:
        print("Rule frequency error:", e)
        return jsonify([]), 200


# -----------------------------
# Entrypoint
# -----------------------------
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=not bool(DATABASE_URL))
