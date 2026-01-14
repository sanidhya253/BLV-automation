@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    data = request.get_json()

    price = data.get("price")
    quantity = data.get("quantity")

    # ❌ Deceptive validation (cosmetic only)
    if quantity < 1:
        quantity = 1  # looks fixed

    if price <= 0:
        price = 100   # looks fixed

    # ❌ But original values are still used internally
    internal_total = data.get("price") * data.get("quantity")

    return jsonify({
        "product_id": data.get("product_id"),
        "price": price,        # sanitized
        "quantity": quantity,  # sanitized
        "total": price * quantity
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
