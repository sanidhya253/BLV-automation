from flask import Flask, jsonify, request
import sqlite3
import os

app = Flask(__name__)
DB_FILE = "ci_results.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS ci_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            commit_sha TEXT,
            branch TEXT,
            status TEXT,
            passed_rules INTEGER,
            failed_rules INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

@app.route("/api/ci-results", methods=["GET"])
def get_ci_results():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT run_id, commit_sha, branch, status, passed_rules, failed_rules, created_at
        FROM ci_results
        ORDER BY created_at DESC
    """)
    rows = c.fetchall()
    conn.close()
    return jsonify(rows)

@app.route("/api/ci-results", methods=["POST"])
def add_ci_result():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Invalid or missing JSON"}), 400

    required_fields = [
        "run_id", "commit_sha", "branch",
        "status", "passed_rules", "failed_rules"
    ]

    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"Missing field: {field}"}), 400

    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO ci_results
            (run_id, commit_sha, branch, status, passed_rules, failed_rules)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                data["run_id"],
                data["commit_sha"],
                data["branch"],
                data["status"],
                int(data["passed_rules"]),
                int(data["failed_rules"]),
            )
        )
        conn.commit()
        conn.close()

        return jsonify({"message": "CI result stored"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
