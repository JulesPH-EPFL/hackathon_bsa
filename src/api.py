from flask import Flask, request, jsonify
from src.wallets import load_wallets
from src.wallets import add_wallet
from src.nft import mint_slot

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

if __name__ == "__main__":
    app.run(debug=True, port=5001)