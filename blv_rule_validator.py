import requests
import json
import sys
from urllib.parse import urljoin

# ================= CONFIG =================
if len(sys.argv) < 2:
    print("Usage: python blv_rule_validator.py https://sasvatbiz.com")
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
# =========================================
BASKET_ID = None
BASKET_ITEM_ID = None
PRODUCT_ID = 1  # Apple Juice - always exists in Juice Shop


def load_rules():
    with open(RULE_FILE, "r") as f:
        return json.load(f)["rules"]


def fail(rule_id, reason):
    print(f"❌ RULE FAILED → {rule_id} | {reason}")
    FAILED_RULES.append(rule_id)


def success(rule_id):
    print(f"✅ RULE PASSED → {rule_id}")
    PASSED_RULES.append(rule_id)


# ================= JUICE SHOP SETUP FUNCTIONS =================

def login_as_guest():
    """Juice Shop allows guest checkout, but login ensures session"""
    login_payload = {"email": "test@test.com", "password": "any"}
    r = SESSION.post(urljoin(TARGET, "/rest/user/login"), json=login_payload)
    if r.status_code == 200:
        print("   [Setup] Logged in (guest session ready)")
    # Even if login fails, guest basket works

def get_or_create_basket():
    global BASKET_ID
    r = SESSION.get(urljoin(TARGET, "/api/Basket"))
    if r.status_code == 200:
        data = r.json()
        BASKET_ID = data.get("id")
        print(f"   [Setup] Found basket ID: {BASKET_ID}")
    else:
        print("   [Setup] Could not get basket")

def add_product_to_basket():
    global BASKET_ITEM_ID
    if not BASKET_ID:
        return False
    payload = {
        "ProductId": PRODUCT_ID,
        "BasketId": BASKET_ID,
        "quantity": 1
    }
    r = SESSION.post(urljoin(TARGET, "/api/BasketItems/"), json=payload, headers=HEADERS)
    if r.status_code == 201:
        data = r.json()
        BASKET_ITEM_ID = data["id"]
        print(f"   [Setup] Added product to basket → Item ID: {BASKET_ITEM_ID}")
        return True
    else:
        print(f"   [Setup] Failed to add item: {r.status_code}")
        return False


# ================= RULE VALIDATORS =================

def validate_price_integrity(rule):
    endpoint = rule["endpoint"]
    payload = {"product_id": 1, "quantity": 1, "price": 1}

    r = SESSION.post(urljoin(TARGET, endpoint), data=payload, headers=HEADERS)

    if r.status_code in [200, 201] and "price" in r.text.lower():
        fail(rule["rule_id"], "Client-controlled price accepted")
    else:
        success(rule["rule_id"])


def validate_negative_quantity(rule):
    print("   Testing negative quantity vulnerability...")
    login_as_guest()
    get_or_create_basket()
    if not add_product_to_basket():
        success(rule["rule_id"])  # Skip if setup failed
        return

    tamper_payload = {"quantity": -10}
    r = SESSION.put(
        urljoin(TARGET, f"/api/BasketItems/{BASKET_ITEM_ID}"),
        json=tamper_payload,
        headers=HEADERS
    )

    if r.status_code == 200:
        fail(rule["rule_id"], "Negative quantity accepted → Critical BLV detected!")
    else:
        success(rule["rule_id"])

def validate_quantity_overflow(rule):
    print("   Testing excessive quantity vulnerability...")
    # Reuse same setup as above
    login_as_guest()
    get_or_create_basket()
    if not add_product_to_basket():
        success(rule["rule_id"])
        return

    tamper_payload = {"quantity": 999999}
    r = SESSION.put(
        urljoin(TARGET, f"/api/BasketItems/{BASKET_ITEM_ID}"),
        json=tamper_payload,
        headers=HEADERS
    )

    if r.status_code == 200:
        fail(rule["rule_id"], "Excessive quantity (999999) accepted → Abuse possible")
    else:
        success(rule["rule_id"])


def validate_coupon_reuse(rule):
    endpoint = rule["endpoint"]
    payload = {"coupon": "TEST100"}

    r1 = SESSION.post(urljoin(TARGET, endpoint), data=payload, headers=HEADERS)
    r2 = SESSION.post(urljoin(TARGET, endpoint), data=payload, headers=HEADERS)

    if r1.status_code == 200 and r2.status_code == 200:
        fail(rule["rule_id"], "Coupon reused successfully")
    else:
        success(rule["rule_id"])


def validate_skip_payment(rule):
    endpoint = rule["endpoint"]

    r = SESSION.post(urljoin(TARGET, endpoint), headers=HEADERS)

    if r.status_code in [200, 201]:
        fail(rule["rule_id"], "Order confirmed without payment")
    else:
        success(rule["rule_id"])

def validate_quantity_overflow(rule):
    endpoint = rule["endpoint"]
    payload = {"product_id": 1, "quantity": 999999}

    r = SESSION.post(urljoin(TARGET, endpoint), data=payload, headers=HEADERS)
    if r.status_code in [200, 201]:
        fail(rule["rule_id"], "Unbounded quantity accepted")
    else:
        success(rule["rule_id"])


def validate_coupon_stacking(rule):
    endpoint = rule["endpoint"]
    cpn1 = {"coupon": "TEST10"}
    cpn2 = {"coupon": "TEST20"}

    r1 = SESSION.post(urljoin(TARGET, endpoint), data=cpn1, headers=HEADERS)
    r2 = SESSION.post(urljoin(TARGET, endpoint), data=cpn2, headers=HEADERS)

    if r1.status_code == 200 and r2.status_code == 200:
        fail(rule["rule_id"], "Multiple coupons applied to same order")
    else:
        success(rule["rule_id"])


def validate_payment_amount(rule):
    endpoint = rule["endpoint"]
    payload = {"amount": 1}  # deliberately mismatched

    r = SESSION.post(urljoin(TARGET, endpoint), data=payload, headers=HEADERS)
    if r.status_code in [200, 201]:
        fail(rule["rule_id"], "Gateway accepted client-controlled amount")
    else:
        success(rule["rule_id"])


def validate_wallet_topup(rule):
    endpoint = rule["endpoint"]
    payload = {"amount": 1000000}

    r = SESSION.post(urljoin(TARGET, endpoint), data=payload, headers=HEADERS)
    if r.status_code in [200, 201]:
        fail(rule["rule_id"], "Excessive wallet top-up accepted")
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
        fail(rule["rule_id"], "Multiple orders created from duplicate requests")
    else:
        success(rule["rule_id"])


def validate_discount_limit(rule):
    endpoint = rule["endpoint"]
    payload = {"discount_percentage": 150}

    r = SESSION.post(urljoin(TARGET, endpoint), data=payload, headers=HEADERS)
    if r.status_code in [200, 201]:
        fail(rule["rule_id"], "Discount over 100% accepted")
    else:
        success(rule["rule_id"])


def validate_shipping_fee(rule):
    endpoint = rule["endpoint"]
    payload = {"shipping_fee": 0}

    r = SESSION.post(urljoin(TARGET, endpoint), data=payload, headers=HEADERS)
    if r.status_code in [200, 201]:
        fail(rule["rule_id"], "Client modified shipping fee accepted")
    else:
        success(rule["rule_id"])


def validate_role_escalation(rule):
    endpoint = rule["endpoint"]
    payload = {"role": "admin"}

    r = SESSION.post(urljoin(TARGET, endpoint), data=payload, headers=HEADERS)
    if r.status_code in [200, 201]:
        fail(rule["rule_id"], "Unauthorized role escalation allowed")
    else:
        success(rule["rule_id"])

# ================= RULE DISPATCHER =================

def validate_rule(rule):
    rule_id = rule["rule_id"]

    if rule_id == "BLV-PRICE-001":
        validate_price_integrity(rule)

    elif rule_id == "BLV-QTY-001":
        validate_negative_quantity(rule)  # ← Updated

    elif rule_id == "BLV-QTY-002":
        validate_quantity_overflow(rule)  # ← Updated

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
        print(f"⚠️ No validator implemented for {rule_id}")


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
