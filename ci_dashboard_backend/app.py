from flask import Flask, request, jsonify
import sqlite3
from datetime import datetime

app = Flask(__name__)
DB = "ci_results.db"

def init_db():
    with sqlite3.connect(DB) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS ci_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            commit_sha TEXT,
            branch TEXT,
            status TEXT,
            passed_rules INTEGER,
            failed_rules INTEGER,
            timestamp TEXT
        )
        """)

@app.route("/api/ci-results", methods=["POST"])
def receive_ci_result():
    data = request.json

    with sqlite3.connect(DB) as conn:
        conn.execute("""
        INSERT INTO ci_results 
        (run_id, commit_sha, branch, status, passed_rules, failed_rules, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data["run_id"],
            data["commit_sha"],
            data["branch"],
            data["status"],
            data["passed_rules"],
            data["failed_rules"],
            datetime.utcnow().isoformat()
        ))

    return jsonify({"message": "CI result stored"}), 201

@app.route("/api/ci-results", methods=["GET"])
def get_ci_results():
    with sqlite3.connect(DB) as conn:
        rows = conn.execute("""
        SELECT run_id, commit_sha, branch, status, passed_rules, failed_rules, timestamp
        FROM ci_results
        ORDER BY id DESC
        """).fetchall()

    return jsonify(rows)

if __name__ == "__main__":
    init_db()
    app.run(port=5001, debug=True)
