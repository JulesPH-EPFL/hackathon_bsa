from xrpl.models.requests import AccountInfo, AccountLines, AccountOffers, AccountNFTs
from src.nft import get_nfts, buy_and_certify
from src.wallets import create_wallet
from src.config import client
from xrpl.utils import drops_to_xrp
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/new_wallet', methods=["GET"])
def new_wallet():
    response = create_wallet()
    return jsonify(response)
    
@app.route('/users_infos/<address>', methods=['GET'])
def get_address(address):
    # Solde XRP
    info = client.request(AccountInfo(account=address))
    balance_xrp = float(drops_to_xrp(info.result["account_data"]["Balance"]))
    
    # NFTs
    nfts = get_nfts(address)
    
    return jsonify({
        "address": address,
        "balance_xrp": balance_xrp,
        "nfts": nfts,
    })
    
@app.route('/payment', methods=['POST'])
def payment():
    data = request.get_json()
    response = buy_and_certify(
        buyer_seed=data["buyer_seed"],
        observatory_address=data["observatory_address"],
        units=data["units"],
        date=data["date"],
        price_xrp_per_unit=data["price_xrp_per_unit"],
        observatory_id=data["observatory_id"],
        currency=data["currency"]
    )
    return jsonify(response)

if __name__ == "__main__":
    app.run(debug=True, port=5001)