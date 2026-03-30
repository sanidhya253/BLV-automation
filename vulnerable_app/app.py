@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    data = request.get_json(silent=True) or {}

    product_id = data.get("product_id")
    price = float(data.get("price", 0))
    quantity = int(data.get("quantity", 1))

    # VULNERABLE: silently normalize negative quantity
    if quantity < 0:
        quantity = abs(quantity)

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
        "message": "Added",
        "cart": CART
    }), 200

