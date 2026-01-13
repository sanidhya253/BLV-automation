from flask import Flask, request, jsonify, render_template
import psycopg2
import os

DATABASE_URL = os.environ.get("DATABASE_URL")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates")
)

def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db()
    cur = conn.cursor()

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
               passed_rules, failed_rules, created_at
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

    required = [
        "run_id", "commit_sha", "branch",
        "status", "passed_rules", "failed_rules, failed_rule_details"
    ]

    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing field: {field}"}), 400

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ci_results
            (run_id, commit_sha, branch, status, passed_rules, failed_rules, failed_rule_details)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            data["run_id"],
            data["commit_sha"],
            data["branch"],
            data["status"],
            int(data["passed_rules"]),
            int(data["failed_rules"]),
            data.get("failed_rule_details", "")
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
               passed_rules, failed_rules,failed_rule_details, created_at
        FROM ci_results
        ORDER BY created_at DESC
    """)
    results = cur.fetchall()
    conn.close()

    return render_template("dashboard.html", results=results)

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
