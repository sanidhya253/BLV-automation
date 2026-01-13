from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    data = request.json

    product_id = data.get("product_id")
    price = data.get("price")
    quantity = data.get("quantity")

    # ✅ BUSINESS LOGIC VALIDATION (FIX)
    if price is None or quantity is None:
        return jsonify({"error": "Missing price or quantity"}), 400

    if not isinstance(price, (int, float)) or not isinstance(quantity, int):
        return jsonify({"error": "Invalid data type"}), 400

    if price <= 0:
        return jsonify({"error": "Price must be greater than zero"}), 400

    if quantity <= 0:
        return jsonify({"error": "Quantity must be greater than zero"}), 400

    if quantity > 100:
        return jsonify({"error": "Quantity limit exceeded"}), 400

    total = price * quantity

    return jsonify({
        "product_id": product_id,
        "price": price,
        "quantity": quantity,
        "total": total
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
