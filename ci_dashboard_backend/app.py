from io import BytesIO
from flask import Flask, request, jsonify, render_template, send_file
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import os
import sqlite3
import json

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


DATABASE_URL = os.environ.get("DATABASE_URL")

# Lazy import: only required when DATABASE_URL is set
if DATABASE_URL:
    import psycopg2

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))


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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    conn.commit()
    conn.close()

def fetch_run_by_run_id(run_id):
    conn = get_db()
    cur = conn.cursor()

    if DATABASE_URL:
        cur.execute("""
            SELECT run_id, commit_sha, branch, status,
                   passed_rules, failed_rules, failed_rule_details, created_at, failed_rule_reasons
            FROM ci_results
            WHERE run_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (run_id,))
    else:
        cur.execute("""
            SELECT run_id, commit_sha, branch, status,
                   passed_rules, failed_rules, failed_rule_details, created_at, failed_rule_reasons
            FROM ci_results
            WHERE run_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (run_id,))

    row = cur.fetchone()
    conn.close()
    return row


@app.route("/api/ci-results", methods=["GET"])
def get_ci_results():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT run_id, commit_sha, branch, status,
               passed_rules, failed_rules, failed_rule_details, created_at, failed_rule_reasons
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

    # --- NEW: accept reasons from validator ---
    # The validator may send a dict like {"BLV-CPN-001": "Coupon reuse allowed"}.
    # We store as a simple string: "BLV-CPN-001: ...||BLV-WF-001: ..."
    reasons_dict = data.get("failed_rule_reasons") or {}
    if isinstance(reasons_dict, dict) and reasons_dict:
        reasons_str = "||".join([f"{k}: {v}" for k, v in reasons_dict.items()])
    elif isinstance(reasons_dict, str) and reasons_dict.strip():
        # If already a string, store as-is
        reasons_str = reasons_dict.strip()
    else:
        reasons_str = None

    try:
        conn = get_db()
        cur = conn.cursor()

        if DATABASE_URL:
            # Postgres placeholders
            cur.execute("""
                INSERT INTO ci_results
                (run_id, commit_sha, branch, status, passed_rules, failed_rules, failed_rule_details, failed_rule_reasons)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data["run_id"],
                data["commit_sha"],
                data["branch"],
                data["status"],
                int(data["passed_rules"]),
                int(data["failed_rules"]),
                data.get("failed_rule_details"),
                reasons_str
            ))
        else:
            # SQLite placeholders
            cur.execute("""
                INSERT INTO ci_results
                (run_id, commit_sha, branch, status, passed_rules, failed_rules, failed_rule_details, failed_rule_reasons)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["run_id"],
                data["commit_sha"],
                data["branch"],
                data["status"],
                int(data["passed_rules"]),
                int(data["failed_rules"]),
                data.get("failed_rule_details"),
                reasons_str
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
               passed_rules, failed_rules, failed_rule_details, created_at, failed_rule_reasons
        FROM ci_results
        ORDER BY created_at DESC
    """)
    results = cur.fetchall()
    conn.close()
    return render_template("dashboard.html", results=results)

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
    }
    return jsonify(report), 200

@app.route("/report/<run_id>.pdf", methods=["GET"])
def download_report_pdf(run_id):
    row = fetch_run_by_run_id(run_id)
    if not row:
        return jsonify({"error": "Run not found"}), 404

    run_id, commit_sha, branch, status, passed_rules, failed_rules, failed_rule_details, created_at, failed_rule_reasons = row

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    y = height - 60

    # Title
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "BLV CI Scan Report")
    y -= 30

    c.setFont("Helvetica", 11)
    meta_lines = [
        f"Run ID: {run_id}",
        f"Commit SHA: {commit_sha}",
        f"Branch: {branch}",
        f"Status: {status}",
        f"Passed Rules: {passed_rules}",
        f"Failed Rules: {failed_rules}",
        f"Failed Rule IDs: {failed_rule_details or '-'}",
        f"Time: {created_at}",
        ""
    ]

    for line in meta_lines:
        c.drawString(50, y, line)
        y -= 16
        if y < 80:
            c.showPage()
            y = height - 60
            c.setFont("Helvetica", 11)

    # Reasons
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Failure Reasons")
    y -= 20
    c.setFont("Helvetica", 11)

    if failed_rule_reasons:
        for item in str(failed_rule_reasons).split("||"):
            c.drawString(60, y, f"- {item}")
            y -= 16
            if y < 80:
                c.showPage()
                y = height - 60
                c.setFont("Helvetica", 11)
    else:
        c.drawString(60, y, "- None")
        y -= 16

    c.showPage()
    c.save()
    buf.seek(0)

    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"blv_report_{run_id}.pdf"
    )
    
@app.route("/api/stats/daily", methods=["GET"])
def stats_daily():
    """
    Returns daily counts for PASS/FAIL runs for the last 14 days.
    Output: [{date: "YYYY-MM-DD", pass: 3, fail: 1}, ...]
    """
    conn = get_db()
    cur = conn.cursor()

    if DATABASE_URL:
        # Postgres
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
        # SQLite
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
        data.append({
            "date": str(d),
            "pass": int(p or 0),
            "fail": int(f or 0),
        })

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


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=not bool(DATABASE_URL))
