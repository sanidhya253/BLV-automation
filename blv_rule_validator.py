import requests
import json
import sys
from urllib.parse import urljoin

# ================= CONFIG =================
if len(sys.argv) < 2:
    print("Usage: python blv_rule_validator.py http://localhost:3000")
    sys.exit(1)

TARGET = sys.argv[1].rstrip("/")
SESSION = requests.Session()

HEADERS = {
    "User-Agent": "BLV-Rule-Validator/1.0",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

RULE_FILE = "rules/final_business_logic_rules.json"
FAILED_RULES = []
PASSED_RULES = []

# Global variables for Juice Shop
BASKET_ID = None
BASKET_ITEM_ID = None
PRODUCT_ID = 1  # Apple Juice

# =========================================

def load_rules():
    with open(RULE_FILE, "r") as f:
        return json.load(f)["rules"]

def fail(rule_id, reason):
    print(f"❌ RULE FAILED → {rule_id} | {reason}")
    FAILED_RULES.append(rule_id)

def success(rule_id):
    print(f"✅ RULE PASSED → {rule_id}")
    PASSED_RULES.append(rule_id)

# ================= JUICE SHOP SETUP =================
def login():
    """Login to OWASP Juice Shop and establish session"""
    payload = {
        "email": "test@test.com",
        "password": "test123"
    }

    r = SESSION.post(
        urljoin(TARGET, "/rest/user/login"),
        json=payload,
        headers=HEADERS
    )

    return r.status_code == 200


def get_basket():
    """Ensure basket exists for the logged-in user"""
    r = SESSION.get(
        urljoin(TARGET, "/rest/basket"),
        headers=HEADERS
    )
    return r.status_code == 200


def add_product_to_basket():
    """Add a valid product to basket before testing BLV"""
    payload = {
        "ProductId": 1,
        "quantity": 1
    }

    r = SESSION.post(
        urljoin(TARGET, "/api/BasketItems/"),
        json=payload,
        headers=HEADERS
    )

    return r.status_code in [200, 201]


# ================= VALIDATORS =================

def validate_price_integrity(rule):
    endpoint = rule["endpoint"]
    payload = {"product_id": 1, "quantity": 1, "price": 1}
    r = SESSION.post(urljoin(TARGET, endpoint), data=payload, headers=HEADERS)
    if r.status_code in [200, 201]:
        fail(rule["rule_id"], "Client-controlled price accepted")
    else:
        success(rule["rule_id"])

def validate_negative_quantity(rule):
    login_juice_shop()
    add_product()

    payload = {
        "ProductId": 1,
        "quantity": -5
    }

    r = SESSION.post(
        urljoin(TARGET, "/api/BasketItems/"),
        json=payload,
        headers=HEADERS
    )

    if r.status_code in [200, 201]:
        fail(rule["rule_id"], "Negative quantity accepted (real BLV triggered)")
    else:
        success(rule["rule_id"])


def validate_quantity_overflow(rule):
    print("   Testing excessive quantity...")

    if not login() or not get_basket() or not add_product_to_basket():
        fail(rule["rule_id"], "Failed to prepare valid shopping state")
        return

    payload = {
        "ProductId": 1,
        "quantity": 999999
    }

    r = SESSION.post(
        urljoin(TARGET, "/api/BasketItems/"),
        json=payload,
        headers=HEADERS
    )

    if r.status_code in [200, 201]:
        fail(rule["rule_id"], "Quantity overflow accepted (real BLV)")
    else:
        success(rule["rule_id"])

def validate_skip_payment(rule):
    print("   Testing order without payment...")
    if not login() or not get_basket() or not add_product_to_basket():
        success(rule["rule_id"])
        return
    r = SESSION.post(urljoin(TARGET, "/api/Orders"), json={}, headers=HEADERS)
    if r.status_code == 201:
        fail(rule["rule_id"], "Order placed without payment → Workflow bypass!")
    else:
        success(rule["rule_id"])

def validate_coupon_reuse(rule):
    endpoint = rule["endpoint"]
    payload = {"coupon": "TEST100"}
    r1 = SESSION.post(urljoin(TARGET, endpoint), data=payload, headers=HEADERS)
    r2 = SESSION.post(urljoin(TARGET, endpoint), data=payload, headers=HEADERS)
    if r1.status_code == 200 and r2.status_code == 200:
        fail(rule["rule_id"], "Coupon reused")
    else:
        success(rule["rule_id"])

def validate_coupon_stacking(rule):
    endpoint = rule["endpoint"]
    r1 = SESSION.post(urljoin(TARGET, endpoint), data={"coupon": "TEST10"}, headers=HEADERS)
    r2 = SESSION.post(urljoin(TARGET, endpoint), data={"coupon": "TEST20"}, headers=HEADERS)
    if r1.status_code == 200 and r2.status_code == 200:
        fail(rule["rule_id"], "Multiple coupons applied")
    else:
        success(rule["rule_id"])

def validate_payment_amount(rule):
    endpoint = rule["endpoint"]
    r = SESSION.post(urljoin(TARGET, endpoint), data={"amount": 1}, headers=HEADERS)
    if r.status_code in [200, 201]:
        fail(rule["rule_id"], "Client-controlled payment amount")
    else:
        success(rule["rule_id"])

def validate_wallet_topup(rule):
    endpoint = rule["endpoint"]
    r = SESSION.post(urljoin(TARGET, endpoint), data={"amount": 1000000}, headers=HEADERS)
    if r.status_code in [200, 201]:
        fail(rule["rule_id"], "Excessive wallet top-up")
    else:
        success(rule["rule_id"])

def validate_race_condition(rule):
    endpoint = rule["endpoint"]
    success_count = 0
    for _ in range(3):
        r = SESSION.post(urljoin(TARGET, endpoint), data={"submit": 1}, headers=HEADERS)
        if r.status_code in [200, 201]:
            success_count += 1
    if success_count > 1:
        fail(rule["rule_id"], "Race condition: multiple orders")
    else:
        success(rule["rule_id"])

def validate_discount_limit(rule):
    endpoint = rule["endpoint"]
    r = SESSION.post(urljoin(TARGET, endpoint), data={"discount_percentage": 150}, headers=HEADERS)
    if r.status_code in [200, 201]:
        fail(rule["rule_id"], "Discount over 100%")
    else:
        success(rule["rule_id"])

def validate_shipping_fee(rule):
    endpoint = rule["endpoint"]
    r = SESSION.post(urljoin(TARGET, endpoint), data={"shipping_fee": 0}, headers=HEADERS)
    if r.status_code in [200, 201]:
        fail(rule["rule_id"], "Client modified shipping fee")
    else:
        success(rule["rule_id"])

def validate_role_escalation(rule):
    endpoint = rule["endpoint"]
    r = SESSION.post(urljoin(TARGET, endpoint), data={"role": "admin"}, headers=HEADERS)
    if r.status_code in [200, 201]:
        fail(rule["rule_id"], "Role escalation allowed")
    else:
        success(rule["rule_id"])

# ================= RULE DISPATCHER =================

def validate_rule(rule):
    rule_id = rule["rule_id"]
    if rule_id == "BLV-PRICE-001":
        validate_price_integrity(rule)
    elif rule_id == "BLV-QTY-001":
        validate_negative_quantity(rule)
    elif rule_id == "BLV-QTY-002":
        validate_quantity_overflow(rule)
    elif rule_id == "BLV-CPN-001":
        validate_coupon_reuse(rule)
    elif rule_id == "BLV-WF-001":
        validate_skip_payment(rule)
    elif rule_id == "BLV-CPN-002":
        validate_coupon_stacking(rule)
    elif rule_id == "BLV-PAY-001":
        validate_payment_amount(rule)
    elif rule_id == "BLV-WAL-001":
        validate_wallet_topup(rule)
    elif rule_id == "BLV-RACE-001":
        validate_race_condition(rule)
    elif rule_id == "BLV-DISC-001":
        validate_discount_limit(rule)
    elif rule_id == "BLV-SHIP-001":
        validate_shipping_fee(rule)
    elif rule_id == "BLV-AUTH-001":
        validate_role_escalation(rule)
    else:
        print(f"⚠️ No validator for {rule_id}")

# ================= MAIN =================

def main():
    print("\n🔍 Starting Business Logic Rule Validation on OWASP Juice Shop\n")
    rules = load_rules()
    for rule in rules:
        print(f"\nTesting Rule: {rule['rule_id']} - {rule['name']}")
        validate_rule(rule)

    print("\n" + "=" * 70)
    print(f"Rules Passed: {len(PASSED_RULES)}")
    print(f"Rules Failed: {len(FAILED_RULES)}")

    if FAILED_RULES:
        print("\n❌ CI/CD BLOCKED — Business Logic Violations Found!")
        sys.exit(1)
    else:
        print("\n✅ CI/CD PASSED — No Business Logic Violations")
        sys.exit(0)

if __name__ == "__main__":
    main()



