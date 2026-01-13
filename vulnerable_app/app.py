from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    data = request.get_json()

    # INTENTIONALLY VULNERABLE LOGIC
    # ❌ No validation
    # ❌ No server-side recalculation

    price = data.get("price")
    quantity = data.get("quantity")

    total = price * quantity  # vulnerable on purpose

    return jsonify({
        "product_id": data.get("product_id"),
        "price": price,
        "quantity": quantity,
        "total": total
    }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
