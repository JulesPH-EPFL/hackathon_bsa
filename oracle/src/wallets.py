import json
import os
from xrpl.wallet import Wallet, generate_faucet_wallet
from src.config2 import client

def create_wallet() -> dict:
    wallet = generate_faucet_wallet(client, debug=True)
    return {
        "address": wallet.address,
        "seed": wallet.seed
    }
        
def get_wallet(seed: str) -> Wallet:
    return Wallet.from_seed(seed)