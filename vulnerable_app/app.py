from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    data = request.get_json(silent=True) or {}

    # Basic required fields
    product_id = data.get("product_id")
    price = data.get("price")
    quantity = data.get("quantity")

    # Validate presence + types
    try:
        price = float(price)
        quantity = int(quantity)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid types for price/quantity"}), 400

    # ✅ Business logic validation (the two rules your validator checks)
    if quantity < 1:
        return jsonify({"error": "Quantity must be >= 1"}), 400

    if price <= 0:
        return jsonify({"error": "Price must be > 0"}), 400

    # Server-side calculation
    total = price * quantity

    return jsonify({
        "product_id": product_id,
        "price": price,
        "quantity": quantity,
        "total": total
    }), 200


if __name__ == "__main__":
    # IMPORTANT for Docker
    app.run(host="0.0.0.0", port=5000)
