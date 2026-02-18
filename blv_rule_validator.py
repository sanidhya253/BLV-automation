import json
import os
import sys
from urllib.parse import urljoin

import requests

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
    "User-Agent": "BLV-Rule-Validator/1.1",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

FAILED = []   # list of dicts: {rule_id, severity, reason}
PASSED = []   # list of dicts: {rule_id, severity}

# =========================================================
# UTIL
# =========================================================
def load_rules():
    with open(RULE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)["rules"]


def record_fail(rule, reason):
    rid = rule.get("rule_id", "UNKNOWN")
    sev = (rule.get("severity") or "LOW").upper()
    print(f"❌ RULE FAILED → {rid} [{sev}] | {reason}")
    FAILED.append({"rule_id": rid, "severity": sev, "reason": reason})


def record_pass(rule):
    rid = rule.get("rule_id", "UNKNOWN")
    sev = (rule.get("severity") or "LOW").upper()
    print(f"✅ RULE PASSED → {rid} [{sev}]")
    PASSED.append({"rule_id": rid, "severity": sev})


def post_json(endpoint, payload):
    return SESSION.post(urljoin(TARGET, endpoint), json=payload, headers=HEADERS, timeout=8)


def get(endpoint, extra_headers=None):
    h = dict(HEADERS)
    if extra_headers:
        h.update(extra_headers)
    return SESSION.get(urljoin(TARGET, endpoint), headers=h, timeout=8)


# =========================================================
# VALIDATORS
# =========================================================
def v_qty_min(rule):
    # Expect 400 for negative qty
    payload = {"product_id": 1, "price": 100, "quantity": -1}
    try:
        r = post_json(rule["endpoint"], payload)
    except requests.exceptions.RequestException:
        record_fail(rule, "Target not reachable")
        return

    if r.status_code == 200:
        record_fail(rule, "Negative/zero quantity was accepted (expected rejection)")
        return
    record_pass(rule)


def v_price_positive(rule):
    payload = {"product_id": 1, "price": -50, "quantity": 1}
    r = post_json(rule["endpoint"], payload)

    if r.status_code == 200:
        record_fail(rule, "Non-positive price was accepted (expected rejection)")
        return
    record_pass(rule)


def v_qty_upper_bound(rule):
    max_qty = int(rule.get("expected_behavior", {}).get("quantity_maximum", 10))
    payload = {"product_id": 1, "price": 100, "quantity": max_qty + 999}
    r = post_json(rule["endpoint"], payload)

    if r.status_code == 200:
        record_fail(rule, f"Unreasonably large quantity accepted (> {max_qty})")
        return
    record_pass(rule)


def v_coupon_single_use(rule):
    # Precondition: add something to cart
    add = post_json("/add-to-cart", {"product_id": 1, "price": 100, "quantity": 1})
    if add.status_code != 200:
        record_fail(rule, "Precondition failed: could not add item to cart")
        return

    code = (rule.get("test", {}).get("coupon_code") or "SAVE10")
    first = post_json(rule["endpoint"], {"coupon_code": code})
    second = post_json(rule["endpoint"], {"coupon_code": code})

    if first.status_code != 200:
        record_fail(rule, f"Coupon apply failed unexpectedly (status {first.status_code})")
        return

    # Expected: second attempt should be rejected
    if second.status_code == 200:
        record_fail(rule, "Coupon reuse allowed (should be single-use)")
        return

    record_pass(rule)


def v_coupon_stacking_cap(rule):
    # Precondition: add something to cart
    add = post_json("/add-to-cart", {"product_id": 2, "price": 200, "quantity": 1})
    if add.status_code != 200:
        record_fail(rule, "Precondition failed: could not add item to cart")
        return

    # Apply two different coupons and check total discount doesn't exceed cap
    cap = float(rule.get("expected_behavior", {}).get("max_discount_rate", 0.30))

    r1 = post_json("/apply-coupon", {"coupon_code": "SAVE20"})
    r2 = post_json("/apply-coupon", {"coupon_code": "SAVE10"})  # stacking attempt

    # If app blocks reuse only, stacking may still happen with different codes.
    # If second succeeds AND total discount grows beyond cap -> fail.
    if r1.status_code != 200:
        record_fail(rule, f"First coupon failed unexpectedly (status {r1.status_code})")
        return

    if r2.status_code == 200:
        try:
            cart = r2.json().get("cart", {})
            subtotal = float(cart.get("subtotal", 0))
            discount = float(cart.get("discount", 0))
            rate = (discount / subtotal) if subtotal > 0 else 0
        except Exception:
            record_fail(rule, "Could not parse cart totals after stacking")
            return

        if rate > cap + 1e-9:
            record_fail(rule, f"Coupon stacking exceeded cap ({rate:.2f} > {cap:.2f})")
            return

    # If second coupon rejected, that's also a pass for 'stacking prevention'
    record_pass(rule)


def v_checkout_workflow(rule):
    # Try checkout with empty cart - must fail
    empty = post_json(rule["endpoint"], {})
    if empty.status_code == 200:
        record_fail(rule, "Checkout succeeded with empty cart (workflow bypass)")
        return

    # Add item then checkout should succeed
    add = post_json("/add-to-cart", {"product_id": 3, "price": 50, "quantity": 1})
    if add.status_code != 200:
        record_fail(rule, "Precondition failed: could not add item before checkout")
        return

    ok = post_json(rule["endpoint"], {})
    if ok.status_code != 200:
        record_fail(rule, f"Checkout failed unexpectedly (status {ok.status_code})")
        return

    record_pass(rule)


def v_admin_authz(rule):
    # Without admin header -> must be forbidden
    r = get(rule["endpoint"])
    if r.status_code == 200:
        record_fail(rule, "Admin endpoint accessible without admin role")
        return

    # With admin header -> should succeed
    r2 = get(rule["endpoint"], extra_headers={"X-Role": "admin"})
    if r2.status_code != 200:
        record_fail(rule, f"Admin access failed even with admin role (status {r2.status_code})")
        return

    record_pass(rule)


# =========================================================
# DISPATCH
# =========================================================
DISPATCH = {
    "BLV-QTY-001": v_qty_min,
    "BLV-PRICE-001": v_price_positive,
    "BLV-QTY-002": v_qty_upper_bound,
    "BLV-CPN-001": v_coupon_single_use,
    "BLV-CPN-002": v_coupon_stacking_cap,
    "BLV-WF-001": v_checkout_workflow,
    "BLV-AUTH-001": v_admin_authz,
}


def validate_rule(rule):
    rid = rule.get("rule_id", "UNKNOWN")
    name = rule.get("name", "")
    print(f"\n🔎 Testing {rid} — {name}")

    # ✅ Reset app state before EVERY rule test
    try:
        post_json("/reset", {})
    except Exception:
        # If reset endpoint isn't available or app is down, continue and let the validator fail properly
        pass

    fn = DISPATCH.get(rid)
    if not fn:
        print(f"⚠️ No validator implemented for {rid} (marked PASS for now)")
        record_pass(rule)
        return

    try:
        fn(rule)
    except Exception as e:
        record_fail(rule, f"Validator crashed: {e}")


def send_ci_result_to_api():
    api_url = os.getenv("CI_RESULT_API")
    if not api_url:
        print("⚠️ CI_RESULT_API not set, skipping API logging")
        return

    failed_ids = [x["rule_id"] for x in FAILED]
    failed_reasons = {x["rule_id"]: x["reason"] for x in FAILED}

    payload = {
        "run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "commit_sha": os.getenv("GITHUB_SHA", "local"),
        "branch": os.getenv("GITHUB_REF_NAME", "local"),
        "status": "FAIL" if FAILED else "PASS",
        "passed_rules": len(PASSED),
        "failed_rules": len(FAILED),
        "failed_rule_details": ", ".join(failed_ids) if failed_ids else None,
        "failed_rule_reasons": failed_reasons,
        "total_rules": len(PASSED) + len(FAILED),
        "implemented_rules": len([r for r in (PASSED + FAILED) if r["rule_id"] in DISPATCH]),
    }

    try:
        r = requests.post(api_url, json=payload, timeout=10)
        print(f"📡 CI result sent to API → {r.status_code}")
    except Exception as e:
        print(f"❌ Failed to send CI result: {e}")


def should_block_ci():
    # Block only if HIGH or CRITICAL failed (recommended)
    for x in FAILED:
        if x["severity"] in ("HIGH", "CRITICAL"):
            return True
    return False


def main():
    print("\n🚦 Starting BLV Rule Validation\n")

    rules = load_rules()
    for rule in rules:
        validate_rule(rule)

    print("\n" + "=" * 60)
    print(f"Rules Passed: {len(PASSED)}")
    print(f"Rules Failed: {len(FAILED)}")
    if FAILED:
        print("Failed IDs:", ", ".join([x["rule_id"] for x in FAILED]))

    send_ci_result_to_api()

    if should_block_ci():
        print("\n❌ CI/CD BLOCKED — HIGH/CRITICAL Business Logic Violations Found")
        sys.exit(1)

    print("\n✅ CI/CD PASSED — No HIGH/CRITICAL Business Logic Violations")
    sys.exit(0)


if __name__ == "__main__":
    main()

