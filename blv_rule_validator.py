import json
import os
import sys
import datetime
from urllib.parse import urljoin

import requests

# =========================================================
# CONFIG
# =========================================================
if len(sys.argv) < 2:
    print("Usage: python blv_rule_validator.py http://target")
    sys.exit(1)

TARGET = sys.argv[1].rstrip("/")
RULE_FILE = os.environ.get("RULE_FILE", "rules/final_business_logic_rules.json")

SESSION = requests.Session()
HEADERS = {
    "User-Agent": "BLV-Rule-Validator/2.0",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

FAILED = []
PASSED = []
SKIPPED = []

# =========================================================
# UTIL
# =========================================================
def load_config():
    with open(RULE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_rules():
    return load_config()["rules"]


def load_quality_gate():
    config = load_config()
    return config.get("quality_gate", {})


def record_fail(rule, reason, evidence=None):
    rid = rule.get("rule_id", "UNKNOWN")
    sev = (rule.get("severity") or "LOW").upper()
    cat = rule.get("category", "General")
    print(f"  [FAIL] {rid} [{sev}] | {reason}")
    FAILED.append({
        "rule_id": rid,
        "severity": sev,
        "category": cat,
        "reason": reason,
        "evidence": evidence or {}
    })


def record_pass(rule):
    rid = rule.get("rule_id", "UNKNOWN")
    sev = (rule.get("severity") or "LOW").upper()
    cat = rule.get("category", "General")
    print(f"  [PASS] {rid} [{sev}]")
    PASSED.append({"rule_id": rid, "severity": sev, "category": cat})


def record_skip(rule, reason):
    rid = rule.get("rule_id", "UNKNOWN")
    print(f"  [SKIP] {rid} | {reason}")
    SKIPPED.append({"rule_id": rid, "reason": reason})


def post_json(endpoint, payload):
    return SESSION.post(urljoin(TARGET, endpoint), json=payload, headers=HEADERS, timeout=8)


def get(endpoint, extra_headers=None):
    h = dict(HEADERS)
    if extra_headers:
        h.update(extra_headers)
    return SESSION.get(urljoin(TARGET, endpoint), headers=h, timeout=8)


def safe_text(resp, limit=400):
    try:
        t = resp.text or ""
        t = t.replace("\n", " ").replace("\r", " ").strip()
        return t[:limit]
    except Exception:
        return ""


def build_evidence(endpoint, payload, resp):
    return {
        "endpoint": endpoint,
        "request_payload": payload,
        "status_code": getattr(resp, "status_code", None),
        "response_snippet": safe_text(resp),
    }


def reset_app():
    try:
        post_json("/reset", {})
    except Exception:
        pass


# =========================================================
# CUSTOM RULE ENGINE
# Runs test_payloads defined in JSON — no Python needed
# =========================================================
def run_custom_payloads(rule):
    """
    Generic validator: reads test_payloads from the rule JSON
    and sends each one. If expect=reject and server returns 200,
    or expect=accept and server returns non-200, the rule fails.
    """
    payloads = rule.get("test_payloads", [])
    if not payloads:
        return None  # no custom payloads, fall through to built-in

    endpoint = rule.get("endpoint", "/")
    method = rule.get("method", "POST").upper()

    # Run preconditions first (e.g., add item to cart before coupon test)
    for pre in rule.get("preconditions", []):
        pre_ep = pre.get("endpoint", "/")
        pre_payload = pre.get("payload", {})
        try:
            post_json(pre_ep, pre_payload)
        except Exception:
            pass

    for tc in payloads:
        label = tc.get("label", "unnamed test")
        expect = tc.get("expect", "reject")

        # Build clean payload (remove meta keys)
        payload = {k: v for k, v in tc.items() if k not in ("expect", "label")}

        try:
            if method == "GET":
                r = get(endpoint)
            else:
                r = post_json(endpoint, payload)
        except Exception as e:
            record_fail(rule, f"Request crashed on '{label}': {e}")
            return True  # handled

        if expect == "reject" and r.status_code == 200:
            record_fail(
                rule,
                f"'{label}' — server accepted invalid input (expected rejection)",
                evidence=build_evidence(endpoint, payload, r)
            )
            return True  # handled

        if expect == "accept" and r.status_code != 200:
            record_fail(
                rule,
                f"'{label}' — server rejected valid input (status {r.status_code})",
                evidence=build_evidence(endpoint, payload, r)
            )
            return True  # handled

    record_pass(rule)
    return True  # handled


# =========================================================
# BUILT-IN VALIDATORS (fallback for rules without test_payloads)
# =========================================================
def v_qty_min(rule):
    if run_custom_payloads(rule):
        return

    invalid_cases = [
        {"product_id": 1, "price": 100, "quantity": -1},
        {"product_id": 1, "price": 100, "quantity": 0},
        {"product_id": 1, "price": 100, "quantity": "-1"},
        {"product_id": 1, "price": 100, "quantity": " -5 "},
        {"product_id": 1, "price": 100, "quantity": 10**9},
        {"product_id": 1, "price": 100},
    ]
    for case in invalid_cases:
        try:
            r = post_json(rule["endpoint"], case)
        except Exception as e:
            record_fail(rule, f"Request crashed: {e}")
            return
        if r.status_code == 200:
            record_fail(rule,
                f"Invalid quantity accepted: {case.get('quantity')}",
                evidence=build_evidence(rule["endpoint"], case, r))
            return
    record_pass(rule)


def v_price_positive(rule):
    if run_custom_payloads(rule):
        return

    payload = {"product_id": 1, "price": -50, "quantity": 1}
    r = post_json(rule["endpoint"], payload)
    if r.status_code == 200:
        record_fail(rule, "Non-positive price accepted",
            evidence=build_evidence(rule["endpoint"], payload, r))
        return
    record_pass(rule)


def v_qty_upper_bound(rule):
    if run_custom_payloads(rule):
        return

    max_qty = int(rule.get("expected_behavior", {}).get("quantity_maximum", 10))
    payload = {"product_id": 1, "price": 100, "quantity": max_qty + 999}
    r = post_json(rule["endpoint"], payload)
    if r.status_code == 200:
        record_fail(rule, f"Unreasonably large quantity accepted (> {max_qty})")
        return
    record_pass(rule)


def v_coupon_single_use(rule):
    if run_custom_payloads(rule):
        return

    add = post_json("/add-to-cart", {"product_id": 1, "price": 100, "quantity": 1})
    if add.status_code != 200:
        record_fail(rule, "Precondition failed: could not add item to cart")
        return
    code = rule.get("test", {}).get("coupon_code", "SAVE10")
    first = post_json(rule["endpoint"], {"coupon_code": code})
    second = post_json(rule["endpoint"], {"coupon_code": code})
    if first.status_code != 200:
        record_fail(rule, f"Coupon apply failed (status {first.status_code})")
        return
    if second.status_code == 200:
        record_fail(rule, "Coupon reuse allowed (should be single-use)")
        return
    record_pass(rule)


def v_coupon_stacking_cap(rule):
    add = post_json("/add-to-cart", {"product_id": 2, "price": 200, "quantity": 1})
    if add.status_code != 200:
        record_fail(rule, "Precondition failed: could not add item to cart")
        return
    cap = float(rule.get("expected_behavior", {}).get("max_discount_rate", 0.30))
    r1 = post_json("/apply-coupon", {"coupon_code": "SAVE20"})
    r2 = post_json("/apply-coupon", {"coupon_code": "SAVE10"})
    if r1.status_code != 200:
        record_fail(rule, f"First coupon failed (status {r1.status_code})")
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
    record_pass(rule)


def v_checkout_workflow(rule):
    empty = post_json(rule["endpoint"], {})
    if empty.status_code == 200:
        record_fail(rule, "Checkout succeeded with empty cart (workflow bypass)")
        return
    add = post_json("/add-to-cart", {"product_id": 3, "price": 50, "quantity": 1})
    if add.status_code != 200:
        record_fail(rule, "Precondition failed: could not add item")
        return
    ok = post_json(rule["endpoint"], {})
    if ok.status_code != 200:
        record_fail(rule, f"Checkout failed unexpectedly (status {ok.status_code})")
        return
    record_pass(rule)


def v_admin_authz(rule):
    r = get(rule["endpoint"])
    if r.status_code == 200:
        record_fail(rule, "Admin endpoint accessible without admin role")
        return
    r2 = get(rule["endpoint"], extra_headers={"X-Role": "admin"})
    if r2.status_code != 200:
        record_fail(rule, f"Admin access failed with admin role (status {r2.status_code})")
        return
    record_pass(rule)


def v_shipping_fee_integrity(rule):
    if run_custom_payloads(rule):
        return

    post_json("/reset", {})
    add = post_json("/add-to-cart", {"product_id": 1, "price": 100, "quantity": 1})
    if add.status_code != 200:
        record_fail(rule, "Precondition failed: could not add item")
        return
    payload = {"shipping_fee": -50}
    r = post_json(rule["endpoint"], payload)
    if r.status_code == 200:
        try:
            body = r.json()
            total = float(body.get("total", 0))
            subtotal = float(body.get("subtotal", 0))
            if total < subtotal:
                record_fail(rule,
                    f"Negative shipping fee accepted (total {total} < subtotal {subtotal})",
                    evidence=build_evidence(rule["endpoint"], payload, r))
                return
        except Exception:
            pass
    record_pass(rule)


# =========================================================
# DISPATCH TABLE
# =========================================================
DISPATCH = {
    "BLV-QTY-001": v_qty_min,
    "BLV-PRICE-001": v_price_positive,
    "BLV-QTY-002": v_qty_upper_bound,
    "BLV-CPN-001": v_coupon_single_use,
    "BLV-CPN-002": v_coupon_stacking_cap,
    "BLV-WF-001": v_checkout_workflow,
    "BLV-AUTH-001": v_admin_authz,
    "BLV-SHIP-001": v_shipping_fee_integrity,
}


def validate_rule(rule):
    rid = rule.get("rule_id", "UNKNOWN")
    name = rule.get("name", "")
    cat = rule.get("category", "General")
    print(f"\n>> [{cat}] Testing {rid} -- {name}")

    reset_app()

    fn = DISPATCH.get(rid)
    if fn:
        try:
            fn(rule)
        except Exception as e:
            record_fail(rule, f"Validator crashed: {e}")
    else:
        # No built-in validator — try custom payloads from JSON
        if rule.get("test_payloads"):
            print(f"   Using custom test payloads from JSON")
            run_custom_payloads(rule)
        else:
            record_skip(rule, "No validator or test_payloads defined")


# =========================================================
# SECURITY SCORE
# =========================================================
def calculate_security_score():
    """
    Calculate a 0-100 security score based on:
    - Rule pass rate (weighted by severity)
    - Coverage (rules with validators vs total)
    """
    if not PASSED and not FAILED:
        return 0

    severity_weights = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    total_weight = 0
    passed_weight = 0

    for p in PASSED:
        w = severity_weights.get(p["severity"], 1)
        total_weight += w
        passed_weight += w

    for f in FAILED:
        w = severity_weights.get(f["severity"], 1)
        total_weight += w

    if total_weight == 0:
        return 100

    # Base score from weighted pass rate
    base_score = (passed_weight / total_weight) * 100

    # Coverage bonus: if all rules have validators, add up to 5 points
    total_rules = len(PASSED) + len(FAILED) + len(SKIPPED)
    tested_rules = len(PASSED) + len(FAILED)
    coverage = (tested_rules / total_rules) if total_rules > 0 else 0
    coverage_bonus = coverage * 5

    score = min(100, base_score + coverage_bonus)
    return round(score, 1)


def get_score_grade(score):
    if score >= 90:
        return "A"
    elif score >= 75:
        return "B"
    elif score >= 60:
        return "C"
    elif score >= 40:
        return "D"
    else:
        return "F"


# =========================================================
# QUALITY GATE
# =========================================================
def evaluate_quality_gate(gate_config, security_score, regressions):
    """
    Returns (passed: bool, reasons: list[str])
    """
    if not gate_config.get("enabled", False):
        return True, ["Quality gate disabled"]

    reasons = []
    passed = True

    # Check severity thresholds
    thresholds = gate_config.get("thresholds", {})
    severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in FAILED:
        sev = f["severity"]
        if sev in severity_counts:
            severity_counts[sev] += 1

    for sev, max_allowed in thresholds.items():
        actual = severity_counts.get(sev, 0)
        if actual > max_allowed:
            passed = False
            reasons.append(f"{sev}: {actual} failures (max allowed: {max_allowed})")

    # Check minimum security score
    min_score = gate_config.get("min_security_score", 0)
    if security_score < min_score:
        passed = False
        reasons.append(f"Security score {security_score} below minimum {min_score}")

    # Check regressions
    if gate_config.get("block_on_regression", False) and regressions:
        passed = False
        reasons.append(f"Regressions detected: {', '.join(regressions)}")

    if passed:
        reasons = ["All quality gate conditions met"]

    return passed, reasons


# =========================================================
# REGRESSION DETECTION
# =========================================================
def detect_regressions():
    """
    Compare current results with the last scan from the API.
    A regression = a rule that PASSED before but FAILS now.
    """
    api_url = os.getenv("CI_RESULT_API")
    if not api_url:
        return [], []  # can't check without API

    try:
        r = requests.get(api_url, timeout=10)
        if r.status_code != 200:
            return [], []

        history = r.json()
        if not history or len(history) < 1:
            return [], []

        # Get the most recent previous run
        last_run = history[0]
        last_failed_str = last_run[6] if len(last_run) > 6 else ""
        last_status = last_run[3] if len(last_run) > 3 else ""

        last_failed_ids = set()
        if last_failed_str:
            last_failed_ids = {x.strip() for x in str(last_failed_str).split(",") if x.strip()}

        current_failed_ids = {x["rule_id"] for x in FAILED}
        current_passed_ids = {x["rule_id"] for x in PASSED}

        # Regressions: was passing before, failing now
        regressions = []
        for rid in current_failed_ids:
            if rid not in last_failed_ids:
                regressions.append(rid)

        # Fixed: was failing before, passing now
        fixed = []
        for rid in current_passed_ids:
            if rid in last_failed_ids:
                fixed.append(rid)

        return regressions, fixed

    except Exception as e:
        print(f"   Regression check error: {e}")
        return [], []


# =========================================================
# REPORTING
# =========================================================
def send_ci_result_to_api(security_score, gate_passed, gate_reasons, regressions, fixed):
    api_url = os.getenv("CI_RESULT_API")
    if not api_url:
        print("\n   CI_RESULT_API not set, skipping API logging")
        return

    failed_ids = [x["rule_id"] for x in FAILED]
    failed_reasons = {x["rule_id"]: x["reason"] for x in FAILED}
    failed_evidence = {x["rule_id"]: x.get("evidence", {}) for x in FAILED}

    # Category breakdown
    category_summary = {}
    for item in PASSED + FAILED:
        cat = item.get("category", "General")
        if cat not in category_summary:
            category_summary[cat] = {"passed": 0, "failed": 0}
        if item in PASSED:
            category_summary[cat]["passed"] += 1
        else:
            category_summary[cat]["failed"] += 1

    payload = {
        "run_id": os.getenv("GITHUB_RUN_ID", f"local-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"),
        "commit_sha": os.getenv("GITHUB_SHA", "local"),
        "branch": os.getenv("GITHUB_REF_NAME", "local"),
        "status": "FAIL" if FAILED else "PASS",
        "passed_rules": len(PASSED),
        "failed_rules": len(FAILED),
        "failed_rule_details": ", ".join(failed_ids) if failed_ids else None,
        "failed_rule_reasons": failed_reasons,
        "failed_rule_evidence": failed_evidence,
        "total_rules": len(PASSED) + len(FAILED) + len(SKIPPED),
        "implemented_rules": len(PASSED) + len(FAILED),
        "security_score": security_score,
        "score_grade": get_score_grade(security_score),
        "quality_gate_passed": gate_passed,
        "quality_gate_reasons": gate_reasons,
        "regressions": regressions,
        "fixed": fixed,
        "category_summary": category_summary,
    }

    try:
        r = requests.post(api_url, json=payload, timeout=10)
        print(f"   CI result sent to API -> {r.status_code}")
    except Exception as e:
        print(f"   Failed to send CI result: {e}")


def print_summary(security_score, gate_passed, gate_reasons, regressions, fixed):
    rules = load_rules()
    total = len(rules)
    tested = len(PASSED) + len(FAILED)
    coverage = (tested / total * 100) if total > 0 else 0

    grade = get_score_grade(security_score)

    print("\n" + "=" * 64)
    print("  BLV SCAN REPORT")
    print("=" * 64)

    # Security Score
    print(f"\n  Security Score  : {security_score}/100 (Grade: {grade})")
    print(f"  Rule Coverage   : {tested}/{total} ({coverage:.0f}%)")
    print(f"  Rules Passed    : {len(PASSED)}")
    print(f"  Rules Failed    : {len(FAILED)}")
    print(f"  Rules Skipped   : {len(SKIPPED)}")

    # Severity Breakdown
    sev_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in FAILED:
        sev = f["severity"]
        if sev in sev_counts:
            sev_counts[sev] += 1

    print(f"\n  Severity Breakdown:")
    print(f"    CRITICAL : {sev_counts['CRITICAL']}")
    print(f"    HIGH     : {sev_counts['HIGH']}")
    print(f"    MEDIUM   : {sev_counts['MEDIUM']}")
    print(f"    LOW      : {sev_counts['LOW']}")

    # Category Breakdown
    categories = {}
    for item in PASSED:
        cat = item.get("category", "General")
        categories.setdefault(cat, {"p": 0, "f": 0})["p"] += 1
    for item in FAILED:
        cat = item.get("category", "General")
        categories.setdefault(cat, {"p": 0, "f": 0})["f"] += 1

    print(f"\n  Category Breakdown:")
    for cat, counts in categories.items():
        total_cat = counts["p"] + counts["f"]
        print(f"    {cat}: {counts['p']}/{total_cat} passed")

    # Regressions & Fixes
    if regressions:
        print(f"\n  !! REGRESSIONS DETECTED (was passing, now failing):")
        for rid in regressions:
            print(f"     - {rid}")

    if fixed:
        print(f"\n  ++ FIXED (was failing, now passing):")
        for rid in fixed:
            print(f"     + {rid}")

    # Failed rule details
    if FAILED:
        print(f"\n  Failed Rules:")
        for f in FAILED:
            print(f"    - {f['rule_id']} [{f['severity']}] {f['reason']}")

    # Quality Gate
    print(f"\n  " + "-" * 60)
    if gate_passed:
        print(f"  QUALITY GATE: PASSED")
    else:
        print(f"  QUALITY GATE: FAILED")
        for reason in gate_reasons:
            print(f"    - {reason}")
    print("=" * 64)


# =========================================================
# MAIN
# =========================================================
def main():
    print("\n" + "=" * 64)
    print("  BLV Rule Validation Engine v2.0")
    print("  Business Logic Security Automation Framework")
    print("=" * 64)

    config = load_config()
    rules = config["rules"]
    gate_config = config.get("quality_gate", {})

    print(f"\n  Target       : {TARGET}")
    print(f"  Rules File   : {RULE_FILE}")
    print(f"  Total Rules  : {len(rules)}")
    print(f"  Quality Gate : {'Enabled' if gate_config.get('enabled') else 'Disabled'}")

    # Run all validators
    for rule in rules:
        validate_rule(rule)

    # Calculate security score
    security_score = calculate_security_score()

    # Detect regressions
    regressions, fixed = detect_regressions()

    # Evaluate quality gate
    gate_passed, gate_reasons = evaluate_quality_gate(
        gate_config, security_score, regressions
    )

    # Print summary
    print_summary(security_score, gate_passed, gate_reasons, regressions, fixed)

    # Send to API
    send_ci_result_to_api(security_score, gate_passed, gate_reasons, regressions, fixed)

    # Exit code based on quality gate
    if not gate_passed:
        print("\n  CI/CD BLOCKED -- Quality Gate Failed")
        sys.exit(1)

    print("\n  CI/CD PASSED -- Quality Gate Passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
