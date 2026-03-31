from flask import Flask, request, jsonify

app = Flask(__name__)

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

USED_COUPONS = set()
MAX_DISCOUNT_RATE = 0.30
MAX_QUANTITY = 10
SHIPPING_FEE = 5.00

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "secure demo app running"}), 200

@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    data = request.get_json(silent=True) or {}
    product_id = data.get("product_id")

    try:
        price = float(data.get("price", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid price format"}), 400

    if price <= 0:
        return jsonify({"error": "Price must be greater than 0"}), 400

    raw_qty = data.get("quantity")
    if raw_qty is None:
        return jsonify({"error": "Quantity is required"}), 400

    try:
        quantity = int(str(raw_qty).strip())
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid quantity format"}), 400

    if quantity < 1:
        return jsonify({"error": "Quantity must be at least 1"}), 400

    if quantity > MAX_QUANTITY:
        return jsonify({"error": f"Quantity cannot exceed {MAX_QUANTITY}"}), 400

    line_total = price * quantity
    CART["items"].append({"product_id": product_id, "price": price, "quantity": quantity, "line_total": line_total})
    CART["subtotal"] += line_total
    CART["total"] = CART["subtotal"] - CART["discount"]
    return jsonify({"message": "Added", "cart": CART}), 200

@app.route("/apply-coupon", methods=["POST"])
def apply_coupon():
    data = request.get_json(silent=True) or {}
    code = (data.get("coupon_code") or "").strip().upper()

    if code not in VALID_COUPONS:
        return jsonify({"error": "Invalid coupon"}), 400

    if code in USED_COUPONS:
        return jsonify({"error": "Coupon has already been used"}), 400

    rate = VALID_COUPONS[code]
    discount_amount = CART["subtotal"] * rate
    new_total_discount = CART["discount"] + discount_amount
    max_allowed = CART["subtotal"] * MAX_DISCOUNT_RATE

    if new_total_discount > max_allowed:
        return jsonify({"error": f"Total discount cannot exceed {int(MAX_DISCOUNT_RATE * 100)}%"}), 400

    CART["discount"] += discount_amount
    CART["total"] = CART["subtotal"] - CART["discount"]
    USED_COUPONS.add(code)
    return jsonify({"message": "Coupon applied", "cart": CART}), 200

@app.route("/checkout", methods=["POST"])
def checkout():
    if not CART["items"]:
        return jsonify({"error": "Cart is empty"}), 400

    if CART["total"] <= 0:
        return jsonify({"error": "Invalid cart total"}), 400

    order = {"items": CART["items"], "subtotal": CART["subtotal"], "discount": CART["discount"], "total": CART["total"], "status": "PAID"}
    CART["items"] = []
    CART["subtotal"] = 0.0
    CART["discount"] = 0.0
    CART["total"] = 0.0
    USED_COUPONS.clear()
    return jsonify({"message": "Checkout complete", "order": order}), 200

@app.route("/admin/report", methods=["GET"])
def admin_report():
    role = request.headers.get("X-Role", "").strip().lower()
    if role != "admin":
        return jsonify({"error": "Unauthorized. Admin role required."}), 403
    return jsonify({"report": "Sensitive financial report data", "total_sales": CART["total"]}), 200

@app.route("/checkout-with-shipping", methods=["POST"])
def checkout_with_shipping():
    data = request.get_json(silent=True) or {}

    if "shipping_fee" in data:
        return jsonify({"error": "Shipping fee cannot be set by client"}), 400

    subtotal = sum(i.get("line_total", 0) for i in CART["items"])
    shipping_fee = SHIPPING_FEE if subtotal > 0 else 0
    total = subtotal + shipping_fee
    return jsonify({"subtotal": subtotal, "shipping_fee": shipping_fee, "total": total, "status": "PAID"}), 200

@app.route("/reset", methods=["POST"])
def reset():
    CART["items"] = []
    CART["subtotal"] = 0.0
    CART["discount"] = 0.0
    CART["total"] = 0.0
    USED_COUPONS.clear()
    return jsonify({"message": "Cart reset"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
