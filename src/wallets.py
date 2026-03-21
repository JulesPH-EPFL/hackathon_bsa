import json
from xrpl.wallet import generate_faucet_wallet
from src.config import client

WALLETS_FILE = "data/wallets.json"

def create_wallet(name: str) -> dict:
    wallet = generate_faucet_wallet(client, debug=True)
    return {
        "name": name,
        "adress": wallet.address,
        "seed": wallet.seed
    }
    
def load_wallets() -> dict:
    with open(WALLETS_FILE, "r") as f:
        return json.load(f)
    
def add_wallet(name: str, role: str) -> dict:
    wallets = load_wallets() if os.path.exists(WALLETS_FILE) else {}
    wallet_id = f"{role}_{name.lower().replace(' ', '_')}"
    wallets[wallet_id] = create_wallet(name)
    with open(WALLETS_FILE, "w") as f:
        json.dump(wallets, f, indent=2)
    return wallets[wallet_id]
        