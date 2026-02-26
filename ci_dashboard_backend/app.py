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
# Paths (define FIRST)
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "ci_results.db")

REPO_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
RULE_FILE = os.path.join(REPO_ROOT, "rules", "final_business_logic_rules.json")

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    import psycopg2

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))


# -----------------------------
# Rule helpers
# -----------------------------
def load_rule_severity_map():
    """
    Returns dict: { "BLV-XXX-001": "HIGH", ... }
    Never crashes the server if rules file is missing.
    """
    try:
        with open(RULE_FILE, "r", encoding="utf-8") as f:
            rules = json.load(f).get("rules", [])
        return {r.get("rule_id"): (r.get("severity") or "LOW").upper() for r in rules}
    except Exception as e:
        print("Severity map load error:", e)
        return {}


def load_rules_index():
    """
    Returns dict: {rule_id: {name, endpoint, severity, expected_behavior}}
    """
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
                    "expected_behavior": r.get("expected_behavior") or {},
                }
        return idx
    except Exception as e:
        print("Rule index load error:", e)
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
        # Postgres
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Safe migration if table existed without the column
        try:
            cur.execute("ALTER TABLE ci_results ADD COLUMN failed_rule_evidence TEXT")
        except Exception:
            pass
    else:
        # SQLite
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Safe migration if table existed without the column
        try:
            cur.execute("ALTER TABLE ci_results ADD COLUMN failed_rule_evidence TEXT")
        except Exception:
            pass

    conn.commit()
    conn.close()


def fetch_run_by_run_id(run_id):
    conn = get_db()
    cur = conn.cursor()

    if DATABASE_URL:
        cur.execute("""
            SELECT run_id, commit_sha, branch, status,
                   passed_rules, failed_rules, failed_rule_details,
                   created_at, failed_rule_reasons, failed_rule_evidence
            FROM ci_results
            WHERE run_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (run_id,))
    else:
        cur.execute("""
            SELECT run_id, commit_sha, branch, status,
                   passed_rules, failed_rules, failed_rule_details,
                   created_at, failed_rule_reasons, failed_rule_evidence
            FROM ci_results
            WHERE run_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (run_id,))

    row = cur.fetchone()
    conn.close()
    return row


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
               created_at, failed_rule_reasons, failed_rule_evidence
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

    # Reasons: store as string "RID: reason||RID2: reason"
    reasons_dict = data.get("failed_rule_reasons") or {}
    if isinstance(reasons_dict, dict) and reasons_dict:
        reasons_str = "||".join([f"{k}: {v}" for k, v in reasons_dict.items()])
    elif isinstance(reasons_dict, str) and reasons_dict.strip():
        reasons_str = reasons_dict.strip()
    else:
        reasons_str = None

    # Evidence: store as JSON string
    evidence_obj = data.get("failed_rule_evidence") or {}
    if isinstance(evidence_obj, (dict, list)):
        evidence_str = json.dumps(evidence_obj)
    elif isinstance(evidence_obj, str) and evidence_obj.strip():
        evidence_str = evidence_obj.strip()
    else:
        evidence_str = None

    try:
        conn = get_db()
        cur = conn.cursor()

        if DATABASE_URL:
            cur.execute("""
                INSERT INTO ci_results
                (run_id, commit_sha, branch, status, passed_rules, failed_rules,
                 failed_rule_details, failed_rule_reasons, failed_rule_evidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data["run_id"],
                data["commit_sha"],
                data["branch"],
                data["status"],
                int(data["passed_rules"]),
                int(data["failed_rules"]),
                data.get("failed_rule_details"),
                reasons_str,
                evidence_str
            ))
        else:
            cur.execute("""
                INSERT INTO ci_results
                (run_id, commit_sha, branch, status, passed_rules, failed_rules,
                 failed_rule_details, failed_rule_reasons, failed_rule_evidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["run_id"],
                data["commit_sha"],
                data["branch"],
                data["status"],
                int(data["passed_rules"]),
                int(data["failed_rules"]),
                data.get("failed_rule_details"),
                reasons_str,
                evidence_str
            ))

        conn.commit()
        conn.close()
        return jsonify({"message": "CI result stored"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return {"status": "BLV CI Dashboard API running"}


@app.route("/dashboard")
def dashboard():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT run_id, commit_sha, branch, status,
               passed_rules, failed_rules, failed_rule_details,
               created_at, failed_rule_reasons, failed_rule_evidence
        FROM ci_results
        ORDER BY created_at DESC
    """)
    results = cur.fetchall()
    conn.close()
    return render_template("dashboard.html", results=results)


# -----------------------------
# Reports
# -----------------------------
@app.route("/report/<run_id>.json", methods=["GET"])
def download_report_json(run_id):
    row = fetch_run_by_run_id(run_id)
    if not row:
        return jsonify({"error": "Run not found"}), 404

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
        "failed_rule_evidence": row[9],
    }
    return jsonify(report), 200


@app.route("/report/<run_id>.pdf", methods=["GET"])
def download_report_pdf(run_id):
    row = fetch_run_by_run_id(run_id)
    if not row:
        return jsonify({"error": "Run not found"}), 404

    run_id, commit_sha, branch, status, passed_rules, failed_rules, failed_rule_details, created_at, failed_rule_reasons, failed_rule_evidence = row

    rules_idx = load_rules_index()

    # Reasons map: "RID: reason||RID2: reason"
    reasons_map = {}
    if failed_rule_reasons:
        for part in str(failed_rule_reasons).split("||"):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                rid, reason = part.split(":", 1)
                reasons_map[rid.strip()] = reason.strip()
            else:
                reasons_map[part.strip()] = ""

    # Evidence JSON -> dict
    evidence_map = {}
    if failed_rule_evidence:
        try:
            evidence_map = json.loads(failed_rule_evidence)
        except Exception:
            evidence_map = {}

    failed_ids = []
    if failed_rule_details:
        failed_ids = [x.strip() for x in str(failed_rule_details).split(",") if x.strip()]

    total_rules = int(passed_rules or 0) + int(failed_rules or 0)

    # Severity counts for this run
    sev_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for rid in failed_ids:
        sev = (rules_idx.get(rid, {}).get("severity") or "LOW").upper()
        if sev not in sev_counts:
            sev = "LOW"
        sev_counts[sev] += 1

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2*cm,
        rightMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10, leading=14)
    mono = ParagraphStyle("mono", parent=styles["BodyText"], fontName="Courier", fontSize=9, leading=12)

    story = []

    # Title
    story.append(Paragraph("BLV CI Scan Report", h1))
    story.append(Paragraph("Business Logic Vulnerability Automation Framework", body))
    story.append(Spacer(1, 10))

    # Metadata table
    meta_tbl = [
        ["Run ID", str(run_id)],
        ["Commit SHA", str(commit_sha)],
        ["Branch", str(branch)],
        ["Status", str(status)],
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

    # Executive summary
    story.append(Paragraph("Executive Summary", h2))
    summary_text = (
        f"This automated CI scan validated <b>{total_rules}</b> business logic rules against the target e-commerce API. "
        f"The run status is <b>{status}</b> with <b>{passed_rules}</b> passed and <b>{failed_rules}</b> failed. "
        "Failed rules indicate potential logic bypasses that can impact pricing integrity, checkout workflow, coupon controls, "
        "and authorization enforcement."
    )
    story.append(Paragraph(summary_text, body))
    story.append(Spacer(1, 10))

    # Overview table
    story.append(Paragraph("Results Overview", h2))
    overview = [
        ["Metric", "Value"],
        ["Total Rules", str(total_rules)],
        ["Passed", str(passed_rules)],
        ["Failed", str(failed_rules)],
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

    # Detailed findings
    story.append(Paragraph("Detailed Findings", h2))

    if not failed_ids:
        story.append(Paragraph("No failed rules were recorded for this run.", body))
    else:
        for rid in failed_ids:
            rmeta = rules_idx.get(rid, {})
            name = rmeta.get("name", "Unknown Rule")
            endpoint = rmeta.get("endpoint", "-")
            sev = rmeta.get("severity", "LOW")
            expected = rmeta.get("expected_behavior", {})
            observed = reasons_map.get(rid, "No reason recorded.")

            story.append(Paragraph(f"<b>{rid}</b> — {name}", body))
            story.append(Paragraph(
                f"<b>Severity:</b> {sev} &nbsp;&nbsp; <b>Endpoint:</b> <font name='Courier'>{endpoint}</font>",
                body
            ))
            story.append(Spacer(1, 4))

            exp_txt = json.dumps(expected, indent=2) if expected else "As per rule definition (validation enforced server-side)."
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

            # Evidence (Proof)
            ev = {}
            if isinstance(evidence_map, dict):
                ev = evidence_map.get(rid, {}) or {}

            ev_endpoint = ev.get("endpoint", endpoint)
            ev_payload = ev.get("request_payload", {})
            ev_code = ev.get("status_code", "-")
            ev_snippet = ev.get("response_snippet", "")

            story.append(Paragraph("<b>Evidence (Proof)</b>", body))
            story.append(Paragraph(
                f"<b>Endpoint:</b> <font name='Courier'>{ev_endpoint}</font><br/>"
                f"<b>Status Code:</b> {ev_code}<br/>"
                f"<b>Request Payload:</b> <font name='Courier'>{json.dumps(ev_payload)[:400]}</font><br/>"
                f"<b>Response Snippet:</b> {ev_snippet}",
                body
            ))
            story.append(Spacer(1, 6))

            # Impact + Recommendation
            story.append(Paragraph(
                "<b>Impact:</b> Attackers can abuse this logic flaw to bypass intended business constraints, "
                "causing financial loss or unauthorized access.",
                body
            ))
            story.append(Paragraph("<b>Recommendation:</b>", body))

            recs = [
                "Validate inputs strictly on the server side (reject invalid values instead of normalizing).",
                "Enforce workflow state checks (e.g., checkout requires non-empty cart, verified totals).",
                "Apply authorization controls for privileged endpoints (role checks, session-based auth).",
                "Add unit/integration tests to prevent regression and keep CI blocking HIGH/CRITICAL failures.",
            ]
            for rline in recs:
                story.append(Paragraph(f"• {rline}", body))

            story.append(Spacer(1, 12))

    story.append(Paragraph(
        "Generated automatically by BLV Automation Framework (CI/CD).",
        ParagraphStyle("foot", parent=body, textColor=colors.grey, fontSize=9)
    ))
    story.append(PageBreak())

    story.append(Paragraph("Appendix: Rules File", h2))
    story.append(Paragraph(f"Rules Source: <font name='Courier'>{RULE_FILE}</font>", body))
    story.append(Paragraph(
        "Method: Automated rule validation executed in GitHub Actions against a Dockerized target app.",
        body
    ))

    doc.build(story)
    buf.seek(0)

    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"blv_report_{run_id}.pdf"
    )


# -----------------------------
# Charts stats (unchanged)
# -----------------------------
@app.route("/api/stats/daily", methods=["GET"])
def stats_daily():
    conn = get_db()
    cur = conn.cursor()

    if DATABASE_URL:
        cur.execute("""
            SELECT DATE(created_at) AS d,
                   SUM(CASE WHEN status = 'PASS' THEN 1 ELSE 0 END) AS pass_count,
                   SUM(CASE WHEN status = 'FAIL' THEN 1 ELSE 0 END) AS fail_count
            FROM ci_results
            WHERE created_at >= (CURRENT_DATE - INTERVAL '13 days')
            GROUP BY d
            ORDER BY d ASC
        """)
    else:
        cur.execute("""
            SELECT DATE(created_at) AS d,
                   SUM(CASE WHEN status = 'PASS' THEN 1 ELSE 0 END) AS pass_count,
                   SUM(CASE WHEN status = 'FAIL' THEN 1 ELSE 0 END) AS fail_count
            FROM ci_results
            WHERE DATE(created_at) >= DATE('now', '-13 day')
            GROUP BY d
            ORDER BY d ASC
        """)

    rows = cur.fetchall()
    conn.close()

    data = []
    for d, p, f in rows:
        data.append({"date": str(d), "pass": int(p or 0), "fail": int(f or 0)})

    return jsonify(data), 200


@app.route("/api/stats/severity", methods=["GET"])
def stats_severity():
    try:
        sev_map = load_rule_severity_map()

        conn = get_db()
        cur = conn.cursor()

        if DATABASE_URL:
            cur.execute("""
                SELECT failed_rule_details
                FROM ci_results
                WHERE status = 'FAIL'
                  AND created_at >= (CURRENT_DATE - INTERVAL '13 days')
                  AND failed_rule_details IS NOT NULL
            """)
        else:
            cur.execute("""
                SELECT failed_rule_details
                FROM ci_results
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


# -----------------------------
# Entrypoint
# -----------------------------
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=not bool(DATABASE_URL))
