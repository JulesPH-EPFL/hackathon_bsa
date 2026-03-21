from xrpl.clients import JsonRpcClient
from xrpl.wallet import generate_faucet_wallet
from xrpl.models.transactions import EscrowCreate
from xrpl.transaction import submit_and_wait
from xrpl.utils import datetime_to_ripple_time
from datetime import datetime, timedelta

print("--- 1. CONNEXION DE L'ÉTUDIANT ---")
client = JsonRpcClient("https://s.altnet.rippletest.net:51234")
student_wallet = generate_faucet_wallet(client)
print(f"Wallet de l'Étudiant : {student_wallet.classic_address}")


ORACLE_ADDRESS = "rNu79Fn9MymieB3vpitKpZAcNKbaCnFg3d"
CONDITION = "A0258020814D88EC1D89613D455583FE766053A833F3789A186FDAC383EEA7453C9A718F810120"

print("\n--- 2. CRÉATION DU SMART CONTRACT (ESCROW) ---")

demain = datetime.now() + timedelta(days=1)
horloge_ripple = datetime_to_ripple_time(demain)

escrow_tx = EscrowCreate(
    account=student_wallet.classic_address,
    amount="10000000", 
    destination=ORACLE_ADDRESS,
    condition=CONDITION,
    cancel_after=horloge_ripple 
)

print("Envoi en cours, attente de validation par le réseau...")
response = submit_and_wait(escrow_tx, client, student_wallet)

if response.is_successful():
    print("✅ SUCCÈS ! L'argent est bloqué dans le coffre-fort.")
    sequence_number = response.result.get("Sequence")
    print(f"📌 NUMÉRO DE SÉQUENCE DE L'ESCROW (À noter pour l'Oracle) : {sequence_number}")
    print(f"🕵️‍♂️ Adresse de l'étudiant (owner) : {student_wallet.classic_address}")
else:
    print("❌ Erreur lors de la création de l'Escrow. Détail du réseau :")
    print(response.result) 