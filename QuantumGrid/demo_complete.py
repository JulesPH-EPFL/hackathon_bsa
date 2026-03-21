import os
import hashlib
import time
from datetime import datetime, timedelta
from xrpl.clients import JsonRpcClient
from xrpl.wallet import generate_faucet_wallet
from xrpl.models.transactions import EscrowCreate, EscrowFinish
from xrpl.transaction import submit_and_wait
from xrpl.utils import datetime_to_ripple_time

print("🌐 Connexion au réseau de test XRPL...")
client = JsonRpcClient("https://s.altnet.rippletest.net:51234")

print("\n🧑‍🎓 Création du compte Étudiant...")
student_wallet = generate_faucet_wallet(client)
print(f"   -> Adresse : {student_wallet.classic_address}")

print("🔬 Création du compte Labo Quantique (Oracle)...")
oracle_wallet = generate_faucet_wallet(client)
print(f"   -> Adresse : {oracle_wallet.classic_address}")

# --- 2. LA SERRURE CRYPTOGRAPHIQUE ---
ORACLE_SECRET = os.urandom(32)
hash_hex = hashlib.sha256(ORACLE_SECRET).hexdigest().upper()
CONDITION = f"A0258020{hash_hex}810120"
FULFILLMENT = f"A0228020{ORACLE_SECRET.hex().upper()}"
print(f"\n🔒 L'Oracle génère la Condition : {CONDITION[:20]}...")

# --- 3. L'ÉTUDIANT BLOQUE L'ARGENT (ESCROW) ---
print("\n💸 L'étudiant envoie 10 XRP dans le Smart Contract (Escrow)...")
demain = datetime.now() + timedelta(days=1)

escrow_tx = EscrowCreate(
    account=student_wallet.classic_address,
    amount="10000000", # 10 XRP
    destination=oracle_wallet.classic_address,
    condition=CONDITION,
    cancel_after=datetime_to_ripple_time(demain)
)

response_create = submit_and_wait(escrow_tx, client, student_wallet)
sequence_number = response_create.result["tx_json"]["Sequence"]
print(f"✅ Argent verrouillé ! (Séquence n°{sequence_number})")

# --- 4. LE JOB QUANTIQUE (L'ORACLE TRAVAILLE) ---
print("\n🚀 [ORACLE] Lancement du circuit quantique sur le processeur...")
for i in range(3, 0, -1):
    print(f"   Calcul en cours... {i}s")
    time.sleep(1)
print("🎯 [ORACLE] Calcul terminé ! Résultat de l'algo de Shor trouvé.")

# --- 5. L'ORACLE DÉBLOQUE L'ARGENT ---
print("\n🔓 L'Oracle utilise sa clé secrète pour débloquer les 10 XRP...")
finish_tx = EscrowFinish(
    account=oracle_wallet.classic_address, 
    owner=student_wallet.classic_address,  
    offer_sequence=sequence_number,        
    condition=CONDITION,
    fulfillment=FULFILLMENT              
)

response_finish = submit_and_wait(finish_tx, client, oracle_wallet)

if response_finish.is_successful():
    print("\n🎉 BINGO ! L'Escrow a été brisé par l'Oracle.")
    print("💰 Les 10 XRP sont maintenant sur le compte du Labo Quantique !")
else:
    print("\n❌ Échec du déblocage...", response_finish.result)