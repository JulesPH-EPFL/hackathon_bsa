import asyncio
import uuid
from functools import partial

from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.wallet import Wallet

from src.wallets import add_wallet, get_wallet
from src.nft import mint_slot, create_sell_offer, buy_slot

import config
import oracle2 as oracle_module
from xrpl_client import client_create_escrow

BELL_CIRCUIT_QASM = """
OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0], q[1];
measure q[0] -> c[0];
measure q[1] -> c[1];
""".strip()


async def run_client(provider_id: str, researcher_id: str):
    print("═══════════════════════════════════════════")
    print("     QuantumGrid — Côté Client")
    print("═══════════════════════════════════════════")

    loop = asyncio.get_event_loop()

    #  1. Wallets 
    researcher_wallet = get_wallet(researcher_id)
    oracle_wallet     = Wallet.from_seed(config.ORACLE_WALLET_SEED)
    print(f"\n[1] Wallets chargés")
    print(f"    Chercheur : {researcher_wallet.address}")
    print(f"    Oracle    : {oracle_wallet.address}")

    #  2. NFT slot 
    print("\n[2] CERN mint un slot de calcul quantique (NFT)...")
    nftoken_id = await loop.run_in_executor(
        None, partial(mint_slot, provider_id, {
            "taxon": 1, "transfer_fee": 5,
            "uri": "quantumgrid://slot/2qubits/bell_state"
        })
    )
    print(f"    NFT slot : {nftoken_id[:28]}...")

    print("\n[3] Arnaud achète le slot...")
    offer_id = await loop.run_in_executor(
        None, partial(create_sell_offer, provider_id, nftoken_id, 0)
    )
    await loop.run_in_executor(None, partial(buy_slot, researcher_id, offer_id))
    print("    Slot acheté ✓")

    #  3. Quote oracle 
    print("\n[4] Arnaud demande un quote à l'oracle...")
    job_id = str(uuid.uuid4())[:16]
    quote  = await oracle_module.handle_quote_request(job_id)
    print(f"    job_id    : {quote['job_id']}")
    print(f"    condition : {quote['condition'][:30]}...")

    #  4. Escrow — c'est tout ce que le client fait 
    print("\n[5] Arnaud crée l'escrow (1 XRP)...")
    print(f"    Circuit   : Bell State (2 qubits)")
    print(f"    Montant   : 1 XRP")

    async with AsyncWebsocketClient(config.XRPL_WS_URL) as client:
        escrow_response = await client_create_escrow(
            client         = client,
            client_wallet  = researcher_wallet,
            oracle_address = oracle_wallet.address,
            condition      = quote["condition"],
            xrp_amount     = 1.0,
            qasm           = BELL_CIRCUIT_QASM,
            shots          = 1024,
            job_id         = job_id,
            ttl_seconds    = 300,
        )
        escrow_tx = escrow_response.result
        tx_result = escrow_tx.get("meta", {}).get("TransactionResult")
        print(f"    EscrowCreate → {tx_result}")
        print(f"    TX hash      : {escrow_tx.get('hash', '')}")

        if tx_result != "tesSUCCESS":
            raise RuntimeError(f"Escrow échoué : {tx_result}")

    print("\n═══════════════════════════════════════════")
    print("  ✓ Escrow créé — l'oracle prend le relais")
    print(f"  L'oracle va détecter l'escrow sur le ledger")
    print(f"  et traiter automatiquement :")
    print(f"    → Exécuter le circuit quantique")
    print(f"    → Vérifier le résultat")
    print(f"    → Libérer le paiement au CERN")
    print("═══════════════════════════════════════════")


if __name__ == "__main__":
    _, provider_id   = add_wallet("CERN",   "fournisseur")
    _, researcher_id = add_wallet("Arnaud", "chercheur")
    print(f"CERN   : {get_wallet(provider_id).address}")
    print(f"Arnaud : {get_wallet(researcher_id).address}")
    asyncio.run(run_client(provider_id, researcher_id))