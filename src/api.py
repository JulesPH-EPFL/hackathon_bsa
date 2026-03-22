from flask import Flask, request, jsonify
from src.wallets import load_wallets
from src.wallets import add_wallet
from src.wallets import get_public_wallet
from src.nft import mint_slot
from src.nft import create_sell_offer
from src.nft import buy_slot
from src.nft import get_nfts
from src.nft import get_sell_offers
import requests as http_requests
from src.tokens import buy_minutes, redeem_minutes, get_minutes_balance

app = Flask(__name__)
ORACLE_API = "http://localhost:5002"

@app.route('/wallets', methods=['GET'])
def get_wallets():
    wallets = load_wallets()
    return jsonify([get_public_wallet(key) for key in wallets])

@app.route('/wallets/add', methods=['POST'])
def add_wallet_api():
    data = request.get_json()
    name = data["name"]
    role = data["role"]
    result, wallet_id = add_wallet(name, role)
    return jsonify(get_public_wallet(wallet_id))
    
@app.route('/slots/mint', methods=['POST'])
def mint_slot_api():
    data = request.get_json()
    id = data["id"]
    metadata = data["metadata"]
    return jsonify({"nftoken_id": mint_slot(id, metadata)})

@app.route('/slots/sell', methods=['POST'])
def create_sell_offer_api():
    data = request.get_json()
    id = data["id"]
    nftoken_id = data["nftoken_id"]
    price_xrp = data["price_xrp"]
    return jsonify({"offer_id": create_sell_offer(id, nftoken_id, price_xrp)})

@app.route('/slots/buy', methods=["POST"])
def buy_slot_api():
    data = request.get_json()
    buyer_id = data["buyer_id"]
    offer_id = data["offer_id"]
    amount_xrp = data["amount_xrp"]
    finish_after = data["finish_after"]
    
    nftoken_id = buy_slot(buyer_id, offer_id)
    
    observatory_address = get_public_wallet(data["observatory_id"])["address"]
    http_requests.post(f"{ORACLE_API}/escrow/create", json={
        "buyer_id": buyer_id,
        "observatory_address": observatory_address,
        "amount_xrp": amount_xrp,
        "finish_after": finish_after
    })
    
    return jsonify({"nftoken_id": nftoken_id})

@app.route('/slots/<address>', methods=["GET"])
def get_nfts_api(address):
    return jsonify({"nfts": get_nfts(address)})

@app.route('/offers/<nftoken_id>', methods=["GET"])
def get_sell_offers_api(nftoken_id):
    return jsonify({"offers": get_sell_offers(nftoken_id)})

@app.route('/minutes/buy', methods=['POST'])
def buy_minutes_api():
    data = request.get_json()
    result = buy_minutes(
        data["buyer_id"],
        data["observatory_id"],
        data["currency"],
        data["minutes"],
        data["price_xrp_per_minute"],
        data["limit"]
    )
    return jsonify(result)

@app.route('/minutes/redeem', methods=['POST'])
def redeem_minutes_api():
    data = request.get_json()
    nftoken_id = redeem_minutes(
        data["buyer_id"],
        data["observatory_id"],
        data["currency"],
        data["minutes"]
    )
    return jsonify({"nftoken_id": nftoken_id})

@app.route('/minutes/balance/<address>/<currency>/<issuer>', methods=['GET'])
def get_minutes_balance_api(address, currency, issuer):
    balance = get_minutes_balance(address, currency, issuer)
    return jsonify({"balance": balance, "currency": currency})
    
if __name__ == "__main__":
    app.run(debug=True, port=5001)