import xrpl
from xrpl.clients import JsonRpcClient
from xrpl.wallet import generate_faucet_wallet
from xrpl.core import addresscodec
from xrpl.models.requests.account_info import AccountInfo
from xrpl.wallet import Wallet
from xrpl.constants import CryptoAlgorithm
import json

JSON_RPC_URL = "https://s.altnet.rippletest.net:51234/"
client = JsonRpcClient(JSON_RPC_URL)

# Create a wallet using the Testnet faucet:
print("\nCreating a new wallet and funding it with Testnet XRP...")

# New wallet with 1000 XRP
test_wallet = generate_faucet_wallet(client, debug=True)

# "rMCcNuTcajgw7YTgBy1sys3b89QqjUrMpH"
# test_wallet = Wallet.from_seed(seed="sn3nxiW7v8KXzPzAqzyHXbSSKNuN9", algorithm=CryptoAlgorithm.SECP256K1) 

test_account  = test_wallet.classic_address

print("Public address :", test_account)
print("Private address :", test_wallet.seed)

# Look up info about your account
print("\nGetting account info...")
acct_info = AccountInfo(
    account=test_account,
    ledger_index="validated",
    strict=True
)

response = client.request(acct_info)
result = response.result
print("Response Status: ", response.status)
print(json.dumps(response.result, indent=4, sort_keys=True))

# Prepare transaction
{
    "TransactionType": "Payment",
    "DeliverMax": "2000000",
    "Destination": "rUCzEr6jrEyMpjhs4wSdQdz4g8Y382NxfM"
}

my_payment = xrpl.models.transactions.Payment(
    account=test_wallet.address,
    amount=xrpl.utils.xrp_to_drops(22),
    destination="rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe"
)

print("Payment object:", my_payment)

# Sign transaction
signed_tx = xrpl.transaction.autofill_and_sign(
    my_payment, client, test_wallet
)
max_ledger = signed_tx.last_ledger_sequence
tx_id = signed_tx.get_hash()
print("Signed transaction:", signed_tx)
print("Transaction cost:", xrpl.utils.drops_to_xrp(signed_tx.fee), "XRP")
print("Transaction expires after ledger:", max_ledger)
print("Identifying hash:", tx_id)

# Submit transaction 
try:
    tx_response = xrpl.transaction.submit_and_wait(signed_tx, client)
except xrpl.transaction.XRPLReliableSubmissionException as e:
    exit(f"Submit failed: {e}")
    
# Check transaction results
print(json.dumps(tx_response.result, indent=4, sort_keys=True))
print(f"Explorer link: https://testnet.xrpl.org/transactions/{tx_id}")
metadata = tx_response.result.get("meta", {})
if metadata.get("TransactionResult"):
    print("Result code:", metadata["TransactionResult"])
if metadata.get("delivered_amount"):
    print("XRP delivered:", xrpl.utils.drops_to_xrp(
                metadata["delivered_amount"]))