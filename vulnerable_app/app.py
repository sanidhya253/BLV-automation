from flask import Flask, request, jsonify

app = Flask(__name__)

# In-memory demo state
CART = {
    "items": [],
    "subtotal": 0.0,
    "discount": 0.0,
    "total": 0.0
}

VALID_COUPONS = {
    "SAVE10": 0.10,
    "SAVE20": 0.20
}

# --------------------------------------------------
# HEALTH
# --------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "vulnerable demo app running"}), 200


# --------------------------------------------------
# ADD TO CART (INTENTIONALLY VULNERABLE)
# --------------------------------------------------
@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    data = request.get_json(silent=True) or {}

    product_id = data.get("product_id")
    price = float(data.get("price", 0))
    quantity = int(data.get("quantity", 1))

    # ❌ Vulnerability 1: No price validation
    # ❌ Vulnerability 2: No minimum quantity check
    # ❌ Vulnerability 3: No maximum quantity check

    line_total = price * quantity

    CART["items"].append({
        "product_id": product_id,
        "price": price,
        "quantity": quantity,
        "line_total": line_total
    })

    CART["subtotal"] += line_total
    CART["total"] = CART["subtotal"] - CART["discount"]

    return jsonify({
        "message": "Added (vulnerable)",
        "cart": CART
    }), 200


# --------------------------------------------------
# APPLY COUPON (INTENTIONALLY VULNERABLE)
# --------------------------------------------------
@app.route("/apply-coupon", methods=["POST"])
def apply_coupon():
    data = request.get_json(silent=True) or {}
    code = (data.get("coupon_code") or "").upper()

    if code not in VALID_COUPONS:
        return jsonify({"error": "Invalid coupon"}), 400

    rate = VALID_COUPONS[code]

    # ❌ Vulnerability 4: Coupon reuse allowed
    # ❌ Vulnerability 5: Coupon stacking allowed
    # ❌ No max discount cap

    discount_amount = CART["subtotal"] * rate
    CART["discount"] += discount_amount
    CART["total"] = CART["subtotal"] - CART["discount"]

    return jsonify({
        "message": "Coupon applied (vulnerable)",
        "cart": CART
    }), 200


# --------------------------------------------------
# CHECKOUT (INTENTIONALLY VULNERABLE)
# --------------------------------------------------
@app.route("/checkout", methods=["POST"])
def checkout():
    # ❌ Vulnerability 6: Checkout allowed even if cart empty
    # ❌ Vulnerability 7: No total validation

    order = {
        "items": CART["items"],
        "subtotal": CART["subtotal"],
        "discount": CART["discount"],
        "total": CART["total"],
        "status": "PAID"
    }

    # No cart clearing (race condition prone)

    return jsonify({
        "message": "Checkout complete (vulnerable)",
        "order": order
    }), 200


# --------------------------------------------------
# ADMIN ENDPOINT (INTENTIONALLY VULNERABLE)
# --------------------------------------------------
@app.route("/admin/report", methods=["GET"])
def admin_report():
    # ❌ Vulnerability 8: No authorization check

    return jsonify({
        "report": "Sensitive financial report data",
        "total_sales": CART["total"]
    }), 200

@app.route("/checkout-with-shipping", methods=["POST"])
def checkout_with_shipping():
    data = request.get_json(silent=True) or {}

    # ❌ Vulnerability: client controls shipping_fee (should be server-side)
    shipping_fee = float(data.get("shipping_fee", 0))

    # Pretend subtotal comes from cart
    subtotal = sum(i.get("line_total", 0) for i in CART["items"])
    total = subtotal + shipping_fee  # attacker can send negative shipping_fee

    return jsonify({
        "subtotal": subtotal,
        "shipping_fee": shipping_fee,
        "total": total,
        "status": "PAID"
    }), 200


# --------------------------------------------------
# RESET (For Testing)
# --------------------------------------------------
@app.route("/reset", methods=["POST"])
def reset():
    CART["items"] = []
    CART["subtotal"] = 0.0
    CART["discount"] = 0.0
    CART["total"] = 0.0
    return jsonify({"message": "Cart reset"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)



