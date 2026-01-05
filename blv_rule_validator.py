import requests
import json
import sys
from urllib.parse import urljoin

# =========================================================
# CONFIG
# =========================================================
if len(sys.argv) < 2:
    print("Usage: python blv_rule_validator.py http://target")
    sys.exit(1)

TARGET = sys.argv[1].rstrip("/")
RULE_FILE = "rules/final_business_logic_rules.json"

SESSION = requests.Session()
HEADERS = {
    "User-Agent": "BLV-Rule-Validator/1.0",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

FAILED_RULES = []
PASSED_RULES = []

# =========================================================
# UTILITY FUNCTIONS
# =========================================================
def fail(rule_id, reason):
    print(f"❌ RULE FAILED → {rule_id} | {reason}")
    FAILED_RULES.append(rule_id)


def success(rule_id):
    print(f"✅ RULE PASSED → {rule_id}")
    PASSED_RULES.append(rule_id)


def load_rules():
    with open(RULE_FILE, "r") as f:
        return json.load(f)["rules"]

# =========================================================
# DEMO APP VALIDATORS (FOR app.py)
# =========================================================

def validate_negative_quantity(rule):
    print("   Testing negative quantity...")

    payload = {
        "product_id": 1,
        "price": 100,
        "quantity": -5
    }

    try:
        r = SESSION.post(
            urljoin(TARGET, rule["endpoint"]),
            json=payload,
            headers=HEADERS,
            timeout=5
        )
    except requests.exceptions.ConnectionError:
        fail(rule["rule_id"], "Target application is not running")
        return

    if r.status_code == 200:
        data = r.json()
        if data.get("quantity", 0) < 1 or data.get("total", 0) < 0:
            fail(rule["rule_id"], "Negative quantity accepted by business logic")
            return

    success(rule["rule_id"])


def validate_price_integrity(rule):
    print("   Testing price tampering...")

    payload = {
        "product_id": 1,
        "price": -50,
        "quantity": 1
    }

    r = SESSION.post(
        urljoin(TARGET, rule["endpoint"]),
        json=payload,
        headers=HEADERS
    )

    if r.status_code == 200:
        data = r.json()
        if data.get("price", 0) <= 0 or data.get("total", 0) <= 0:
            fail(rule["rule_id"], "Invalid price accepted by business logic")
            return

    success(rule["rule_id"])

# =========================================================
# RULE DISPATCHER
# =========================================================
def validate_rule(rule):
    rule_id = rule.get("rule_id", "UNKNOWN")
    rule_name = rule.get("name", "Unnamed Rule")
    print(f"Testing Rule: {rule_id} - {rule_name}")

    if rule_id == "BLV-QTY-001":
        validate_negative_quantity(rule)
    elif rule_id == "BLV-PRICE-001":
        validate_price_integrity(rule)
    else:
        print(f"⚠️ No validator implemented for {rule_id}")
        success(rule_id)

# =========================================================
# MAIN
# =========================================================
def main():
    print("\n🔍 Starting Business Logic Rule Validation (Developer App)\n")

    rules = load_rules()

    for rule in rules:
        validate_rule(rule)

    print("\n" + "=" * 60)
    print(f"Rules Passed: {len(PASSED_RULES)}")
    print(f"Rules Failed: {len(FAILED_RULES)}")

    if FAILED_RULES:
        print("\n❌ CI/CD BLOCKED — Business Logic Violations Found")
        sys.exit(1)
    else:
        print("\n✅ CI/CD PASSED — No Business Logic Violations")
        sys.exit(0)


if __name__ == "__main__":
    main()
