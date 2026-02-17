from flask import Flask, request, jsonify, render_template
import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "ci_results.db")

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))


def get_db():
    conn = sqlite3.connect(DB_PATH)
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


@app.route("/api/ci-results", methods=["GET"])
def get_ci_results():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT run_id, commit_sha, branch, status,
               passed_rules, failed_rules, failed_rule_details, created_at
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

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ci_results
            (run_id, commit_sha, branch, status, passed_rules, failed_rules, failed_rule_details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data["run_id"],
            data["commit_sha"],
            data["branch"],
            data["status"],
            int(data["passed_rules"]),
            int(data["failed_rules"]),
            data.get("failed_rule_details")
        ))
        conn.commit()
        conn.close()
        return jsonify({"message": "CI result stored"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return {"status": "BLV CI Dashboard API running (SQLite local)"}


@app.route("/dashboard")
def dashboard():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT run_id, commit_sha, branch, status,
               passed_rules, failed_rules, failed_rule_details, created_at
        FROM ci_results
        ORDER BY created_at DESC
    """)
    results = cur.fetchall()
    conn.close()
    return render_template("dashboard.html", results=results)


if __name__ == "__main__":
    init_db()
    port = 5000
    app.run(host="0.0.0.0", port=port, debug=True)
