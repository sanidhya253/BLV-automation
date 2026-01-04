from flask import Flask, request, jsonify

app = Flask(__name__)

cart = []
coupons_applied = []

@app.route('/api/cart/add', methods=['POST'])
def add_to_cart():
    data = request.get_json() or request.form
    product_id = data.get('product_id', 1)
    quantity = int(data.get('quantity', 1))  # Vulnerable: allows negative
    price = float(data.get('price', 100))    # Vulnerable: client controls price
    cart.append({"product_id": product_id, "quantity": quantity, "price": price})
    return jsonify({"message": "added"}), 200

@app.route('/api/cart/apply-coupon', methods=['POST'])
def apply_coupon():
    # Vulnerable: allows reuse and stacking
    data = request.get_json() or request.form
    coupons_applied.append(data.get('coupon'))
    return jsonify({"message": "applied"}), 200

@app.route('/api/order/confirm', methods=['POST'])
def confirm_order():
    # Vulnerable: no payment required
    return jsonify({"message": "confirmed without payment"}), 200

@app.route('/api/payment/initiate', methods=['POST'])
def payment():
    return jsonify({"status": "accepted any amount"}), 200

@app.route('/api/wallet/topup', methods=['POST'])
def topup():
    return jsonify({"message": "topup no limit"}), 200

@app.route('/api/user/update-profile', methods=['POST'])
def update_profile():
    return jsonify({"message": "role change allowed"}), 200

@app.route('/')
def home():
    return "Vulnerable App Running"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
