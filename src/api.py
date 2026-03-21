from flask import Flask, request, jsonify
from src.wallets import load_wallets
from src.wallets import add_wallet
from src.nft import mint_slot
from src.nft import create_sell_offer
from src.nft import buy_slot
from src.nft import get_nfts
from src.nft import get_sell_offers

app = Flask(__name__)

@app.route('/wallets', methods=['GET'])
def get_wallets():
    list_ = []
    wallets = load_wallets()
    for key, wallet in wallets.items():
        list_.append({
            "id": key,
            "name": wallet["name"],
            "address": wallet["address"]
        })
    return jsonify(list_)

@app.route('/wallets/add', methods=['POST'])
def add_wallet_api():
    data = request.get_json()
    name = data["name"]
    role = data["role"]
    result = add_wallet(name, role)
    return jsonify({"name": result["name"],
        "address": result["address"]})
    
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
    return jsonify({"nftoken_id": buy_slot(buyer_id, offer_id)})

@app.route('/slots/<address>', methods=["GET"])
def get_nfts_api(address):
    return jsonify({"nfts": get_nfts(address)})

@app.route('/offers/<nftoken_id>', methods=["GET"])
def get_sell_offers_api(nftoken_id):
    return jsonify({"offers": get_sell_offers(nftoken_id)})
    
if __name__ == "__main__":
    app.run(debug=True, port=5001)