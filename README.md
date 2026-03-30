# BLV Automation Framework v2.0

**Business Logic Vulnerability Detection — SAST + DAST Security Pipeline**

An automated framework that detects business logic vulnerabilities using both **static analysis (SAST)** via Semgrep and **dynamic analysis (DAST)** via a custom rule validator, integrated into a CI/CD pipeline with quality gates, regression detection, and security scoring.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     BLV Security Pipeline                       │
│                                                                 │
│  ┌─────────────────────┐     ┌─────────────────────┐           │
│  │  STAGE 1: SAST       │     │  STAGE 2: DAST       │          │
│  │  (Semgrep)           │────>│  (BLV Validator)     │          │
│  │                      │     │                      │          │
│  │  Scans SOURCE CODE   │     │  Tests RUNNING APP   │          │
│  │  for logic flaws     │     │  with attack payloads│          │
│  │  without running it  │     │  to confirm vulns    │          │
│  └──────────┬───────────┘     └──────────┬───────────┘          │
│             │                            │                      │
│             └──────────┬─────────────────┘                      │
│                        ▼                                        │
│             ┌─────────────────────┐                             │
│             │    CI Dashboard     │                             │
│             │   (Flask :8080)     │                             │
│             │                     │                             │
│             │  - Quality Gate     │                             │
│             │  - Security Score   │                             │
│             │  - Regressions      │                             │
│             │  - PDF Reports      │                             │
│             │  - Score History    │                             │
│             └─────────────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
```

## SAST vs DAST — What's the Difference?

| Aspect | SAST (Semgrep) | DAST (BLV Validator) |
|--------|---------------|---------------------|
| What it scans | Source code (files) | Running application (HTTP) |
| When it runs | Before building | After app is running |
| How it works | Pattern matching on code | Sends attack payloads |
| Finds | Code-level logic flaws | Runtime exploitable vulns |
| Example | "abs() used instead of reject" | "Negative qty accepted via API" |

**Both together = comprehensive coverage.** SAST catches issues at code level, DAST confirms they're exploitable.

---

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (v20+)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2+)

### 1. Start the System

```bash
docker compose up --build -d
```

### 2. Run SAST Scan (Semgrep — Static Analysis)

```bash
docker compose run --rm semgrep
```

This scans the vulnerable app's source code and finds logic flaws like missing validation, no auth checks, and client-controlled values.

### 3. Run DAST Scan (BLV Validator — Dynamic Analysis)

```bash
docker compose run --rm validator
```

This sends attack payloads to the running app and confirms vulnerabilities are exploitable.

### 4. View Dashboard

```
http://localhost:8080
```

Both SAST and DAST results appear in the dashboard with quality gate status, security score, severity breakdown, and regression tracking.

### 5. Stop

```bash
docker compose down
```

---

## Project Structure

```
blv-framework/
├── docker-compose.yml              # Orchestrates all 4 services
├── Dockerfile.dashboard            # Dashboard container
├── Dockerfile.validator            # DAST validator container
├── Dockerfile.semgrep              # SAST scanner container
│
├── vulnerable_app/                 # Intentionally vulnerable demo app
│   ├── app.py
│   └── Dockerfile
│
├── semgrep-rules/                  # Custom SAST rules
│   └── blv-business-logic.yaml    # BLV-specific Semgrep rules
│
├── blv_semgrep_runner.py           # SAST scan runner script
├── blv_rule_validator.py           # DAST rule validation engine
│
├── ci_dashboard_backend/           # Dashboard with quality gate
│   ├── app.py
│   ├── requirements.txt
│   └── templates/
│       └── dashboard.html
│
├── rules/
│   └── final_business_logic_rules.json   # Rule definitions + quality gate config
│
└── .github/
    └── workflows/
        └── blv-validation.yml      # CI/CD: SAST → DAST pipeline
```

---

## Semgrep Rules (SAST)

Custom rules that detect business logic vulnerabilities in source code:

| Rule | Detects | Severity | CWE |
|------|---------|----------|-----|
| blv-qty-001 | Negative quantity normalized with abs() | HIGH | CWE-20 |
| blv-price-001 | Client-controlled price without validation | HIGH | CWE-20 |
| blv-cpn-001 | Coupon reuse allowed (no tracking) | HIGH | CWE-799 |
| blv-cpn-002 | No discount cap enforcement | MEDIUM | CWE-840 |
| blv-wf-001 | Checkout without cart validation | CRITICAL | CWE-840 |
| blv-auth-001 | Admin endpoint without authorization | CRITICAL | CWE-862 |
| blv-ship-001 | Client-controlled shipping fee | MEDIUM | CWE-472 |

---

## Dynamic Rules (DAST)

| Rule ID | Name | Severity | Endpoint |
|---------|------|----------|----------|
| BLV-QTY-001 | Quantity must be >= 1 | HIGH | /add-to-cart |
| BLV-PRICE-001 | Price must be > 0 | HIGH | /add-to-cart |
| BLV-QTY-002 | Quantity upper bound enforced | HIGH | /add-to-cart |
| BLV-CPN-001 | Single-use coupon enforcement | HIGH | /apply-coupon |
| BLV-CPN-002 | Coupon stacking prevention | MEDIUM | /apply-coupon |
| BLV-WF-001 | Checkout requires cart + total | CRITICAL | /checkout |
| BLV-AUTH-001 | Admin endpoint requires auth | CRITICAL | /admin/report |
| BLV-SHIP-001 | Shipping fee integrity | MEDIUM | /checkout-with-shipping |

---

## Quality Gate

Configured in `rules/final_business_logic_rules.json`:

```json
"quality_gate": {
    "thresholds": {
        "CRITICAL": 0,
        "HIGH": 0,
        "MEDIUM": 3,
        "LOW": 5
    },
    "min_security_score": 60,
    "block_on_regression": true
}
```

The pipeline blocks if thresholds are exceeded, security score drops below minimum, or regressions are detected.

---

## Commands Reference

| Command | Description |
|---------|-------------|
| `docker compose up --build -d` | Start vulnerable app + dashboard |
| `docker compose run --rm semgrep` | Run SAST scan (Semgrep) |
| `docker compose run --rm validator` | Run DAST scan (Rule Validator) |
| `docker compose logs dashboard` | View dashboard logs |
| `docker compose down` | Stop everything |

---

## CI/CD Pipeline (GitHub Actions)

The pipeline runs in two stages on every push/PR:

1. **SAST Stage** — Semgrep scans source code for business logic patterns
2. **DAST Stage** — BLV Validator tests the running application with attack payloads

Both results are sent to the dashboard and each stage can independently block the pipeline.

---

## Tech Stack

- **Python 3.11** — Validator, SAST runner, and dashboard backend
- **Flask** — Web framework
- **Semgrep** — Static analysis engine
- **SQLite / PostgreSQL** — Database
- **ReportLab** — PDF report generation
- **Chart.js** — Dashboard visualizations
- **Docker & Docker Compose** — Containerization
- **GitHub Actions** — CI/CD automation

---

## Author

Sanidhya Kafle — Final Year Project (CS6P05NI)
Islington College / London Metropolitan University
