from flask import Flask, request, jsonify

app = Flask(__name__)

# Simple in-memory state for demo/testing
CART = {"items": [], "subtotal": 0.0, "discount": 0.0, "total": 0.0}
USED_COUPONS = set()

VALID_COUPONS = {
    "SAVE10": 0.10,
    "SAVE20": 0.20
}

MAX_QTY_PER_ITEM = 10
MAX_DISCOUNT_RATE = 0.30  # 30% max allowed


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    data = request.get_json(silent=True) or {}

    product_id = data.get("product_id")
    price = data.get("price")
    quantity = data.get("quantity")

    try:
        price = float(price)
        quantity = int(quantity)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid types for price/quantity"}), 400

    # Existing rules
    if quantity < 1:
        return jsonify({"error": "Quantity must be >= 1"}), 400

    if price <= 0:
        return jsonify({"error": "Price must be > 0"}), 400

    # NEW rule support: upper bound quantity (app-side guard)
    if quantity > MAX_QTY_PER_ITEM:
        return jsonify({"error": f"Quantity must be <= {MAX_QTY_PER_ITEM}"}), 400

    line_total = price * quantity

    CART["items"].append({
        "product_id": product_id,
        "price": price,
        "quantity": quantity,
        "line_total": line_total
    })

    CART["subtotal"] = sum(i["line_total"] for i in CART["items"])
    CART["total"] = max(CART["subtotal"] - CART["discount"], 0.0)

    return jsonify({
        "message": "Added to cart",
        "cart": CART
    }), 200


@app.route("/apply-coupon", methods=["POST"])
def apply_coupon():
    data = request.get_json(silent=True) or {}
    code = (data.get("coupon_code") or "").strip().upper()

    if not code:
        return jsonify({"error": "coupon_code required"}), 400

    # Must have items before applying coupon (workflow)
    if not CART["items"]:
        return jsonify({"error": "Cart is empty"}), 400

    if code not in VALID_COUPONS:
        return jsonify({"error": "Invalid coupon"}), 400

    # Coupon reuse protection
    if code in USED_COUPONS:
        return jsonify({"error": "Coupon already used"}), 400

    rate = VALID_COUPONS[code]
    # Max discount cap (business rule)
    if rate > MAX_DISCOUNT_RATE:
        return jsonify({"error": "Discount rate too high"}), 400

    discount_amount = CART["subtotal"] * rate
    CART["discount"] += discount_amount
    CART["total"] = max(CART["subtotal"] - CART["discount"], 0.0)

    USED_COUPONS.add(code)

    return jsonify({
        "message": "Coupon applied",
        "coupon_code": code,
        "discount_added": discount_amount,
        "cart": CART
    }), 200


@app.route("/checkout", methods=["POST"])
def checkout():
    # Workflow enforcement: cannot checkout without cart
    if not CART["items"]:
        return jsonify({"error": "Cannot checkout with empty cart"}), 400

    # Prevent nonsense totals
    if CART["total"] <= 0:
        return jsonify({"error": "Invalid total"}), 400

    order = {
        "items": CART["items"],
        "subtotal": CART["subtotal"],
        "discount": CART["discount"],
        "total": CART["total"],
        "status": "PAID"  # simplified for demo
    }

    # Clear cart after checkout
    CART["items"] = []
    CART["subtotal"] = 0.0
    CART["discount"] = 0.0
    CART["total"] = 0.0

    return jsonify({"message": "Checkout complete", "order": order}), 200


@app.route("/admin/report", methods=["GET"])
def admin_report():
    # Simple authz control for demo: require header X-Role: admin
    role = (request.headers.get("X-Role") or "").lower()
    if role != "admin":
        return jsonify({"error": "Forbidden"}), 403

    return jsonify({
        "report": "Sensitive admin report data",
        "used_coupons_count": len(USED_COUPONS)
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
