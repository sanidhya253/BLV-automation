# BLV Automation Framework

Business Logic Vulnerability (BLV) detection tool for CI/CD pipelines.

This framework helps developers automatically detect business logic issues such as:

- Quantity tampering
- Price manipulation
- Coupon abuse
- Workflow bypass
- Authorization errors


## Quick Start

**1. Clone the repository**

git clone https://github.com/sanidhya253/BLV-automation.git
cd BLV-automation

**2. Install dashboard dependencies**
cd ci_dashboard_backend
pip install -r requirements.txt

**3. Run the dashboard**
python app.py

Open in browser:

http://localhost:5000/dashboard

**4. Run the validator**
Start your target application first.

Then run:
python blv_rule_validator.py http://localhost:5000

**⚙ Configure Rules**

Rules are defined in:
rules/final_business_logic_rules.json

You can modify endpoints, payloads, and severity levels according to your application.

**🔄 CI/CD Integration**
Example GitHub Actions step:

- name: Run BLV Validator
  env:
    CI_RESULT_API: https://<your-dashboard-url>/api/ci-results
  run: python blv_rule_validator.py http://127.0.0.1:5000

If HIGH or CRITICAL rules fail, the pipeline will stop.

**📊 Dashboard Features**

Total & Failed runs
Trend chart
Severity breakdown
JSON & PDF report download
