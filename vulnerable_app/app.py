from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    data = request.json

    product_id = data.get("product_id")
    price = data.get("price")
    quantity = data.get("quantity")

    # ❌ INTENTIONAL BUSINESS LOGIC ISSUE
    # No validation on quantity or price
    total = price * quantity

    return jsonify({
        "product_id": product_id,
        "price": price,
        "quantity": quantity,
        "total": total
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
