import json
import os
from xrpl.wallet import Wallet
from xrpl.wallet import generate_faucet_wallet
from src.config2 import client

WALLETS_FILE = "data/wallets.json"

def create_wallet(name: str) -> dict:
    wallet = generate_faucet_wallet(client, debug=True)
    return {
        "name": name,
        "address": wallet.address,
        "seed": wallet.seed
    }
    
def load_wallets() -> dict:
    with open(WALLETS_FILE, "r") as f:
        return json.load(f)
    
def add_wallet(name: str, role: str) -> dict:
    wallets = load_wallets() if os.path.exists(WALLETS_FILE) else {}
    wallet_id = f"{role}_{name.lower().replace(' ', '_')}"
    if wallet_id in wallets:
        print("Ce portefeuille existe déjà !")
        return wallets[wallet_id], wallet_id
    wallets[wallet_id] = create_wallet(name)
    print(f"Wallet '{wallet_id}': {wallets[wallet_id]['address']}")
    with open(WALLETS_FILE, "w") as f:
        json.dump(wallets, f, indent=2)
    return wallets[wallet_id], wallet_id

        
def get_wallet(id: str) -> Wallet:
    wallets = load_wallets() if os.path.exists(WALLETS_FILE) else {}
    if id not in wallets:
        raise KeyError(f"Wallet '{id}' not found in {WALLETS_FILE}")
    wallet_data = wallets[id]
    return Wallet.from_seed(wallet_data["seed"])

def get_public_wallet(id: str) -> dict:
    wallets = load_wallets() if os.path.exists(WALLETS_FILE) else {}
    if id not in wallets:
        raise KeyError(f"Wallet '{id}' introuvable dans {WALLETS_FILE}")
    wallet = wallets[id]
    return {
        "id": id,
        "name": wallet["name"],
        "address": wallet["address"]
    }