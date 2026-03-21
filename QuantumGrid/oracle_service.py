import os
import hashlib
from xrpl.clients import JsonRpcClient
from xrpl.wallet import generate_faucet_wallet

print("--- 1. CONNEXION AU XRPL (TESTNET) ---")
client = JsonRpcClient("https://s.altnet.rippletest.net:51234")
oracle_wallet = generate_faucet_wallet(client)
print(f"✅ Wallet de l'Oracle créé ! \nAdresse : {oracle_wallet.classic_address}")

print("\n--- 2. GÉNÉRATION DE LA SERRURE CRYPTOGRAPHIQUE ---")
ORACLE_SECRET = os.urandom(32)
hash_hex = hashlib.sha256(ORACLE_SECRET).hexdigest().upper()

CONDITION = f"A0258020{hash_hex}810120"

print(f"🔒 CONDITION (Serrure à donner à l'étudiant) : \n{CONDITION}")
print(f"🔑 FULFILLMENT (Clé secrète de l'Oracle) : \n{ORACLE_SECRET.hex().upper()}")