from flask import Flask, request, jsonify

app = Flask(__name__)

# In-memory storage (vulnerable)
cart = []
orders = []
wallet_balance = 0
coupons_applied = []

@app.route('/api/cart/add', methods=['POST'])
def add_to_cart():
    data = request.get_json() or request.form
    product_id = data.get('product_id', 1)
    quantity = int(data.get('quantity', 1))
    price = float(data.get('price', 100))  # Vulnerable: client controls price
    # No checks → allows negative, huge quantity, low price
    cart.append({"product_id": product_id, "quantity": quantity, "price": price})
    return jsonify({"message": "added"}), 200

@app.route('/api/cart/apply-coupon', methods=['POST'])
def apply_coupon():
    # Vulnerable: allows reuse and stacking
    data = request.get_json() or request.form
    coupon = data.get('coupon', 'TEST100')
    coupons_applied.append(coupon)
    return jsonify({"message": "coupon applied"}), 200

@app.route('/api/order/confirm', methods=['POST'])
def confirm_order():
    # Vulnerable: no payment required
    if cart:
        orders.append({"items": cart.copy()})
        cart.clear()
        return jsonify({"message": "order confirmed"}), 200
    return jsonify({"error": "cart empty"}), 400

# Add other endpoints similarly if you want more failures
@app.route('/api/payment/initiate', methods=['POST'])
def payment():
    data = request.get_json() or request.form
    amount = float(data.get('amount', 0))  # Accepts any amount
    return jsonify({"status": "paid"}), 200

@app.route('/api/wallet/topup', methods=['POST'])
def topup():
    global wallet_balance
    amount = int(request.get_json().get('amount', 0))
    wallet_balance += amount  # No limit
    return jsonify({"balance": wallet_balance}), 200

@app.route('/')
def home():
    return "Vulnerable App Running - Ready for BLV Testing"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
