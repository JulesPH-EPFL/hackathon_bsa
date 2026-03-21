import asyncio
import json
import time
import sys
import os

# ─── Code du binôme ───────────────────────────────────────────────────────────
# Cherche le dossier src/ dans les dossiers parents
_here   = os.path.dirname(os.path.abspath(__file__))   # .../hackathon/oracle
_parent = os.path.dirname(_here)                        # .../hackathon
_grand  = os.path.dirname(_parent)                      # .../python

for _p in [_here, _parent, _grand]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from wallets import add_wallet, get_wallet
from nft import mint_slot, create_sell_offer, buy_slot

# ─── Ton code oracle ──────────────────────────────────────────────────────────
import config2 as config
from crypto_condition import JobCryptoKeys
from quantum_executor import execute_job
from xrpl_client import client_create_escrow, escrow_finish, EscrowJob
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.wallet import Wallet

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


async def run_demo():
    print("═══════════════════════════════════════════")
    print("     QuantumGrid — Démo Hackathon")
    print("═══════════════════════════════════════════")

    # ── 1. Créer les wallets (code binôme) ────────────────────────────────────
    print("\n[1] Création des wallets...")
    _, provider_id   = add_wallet("CERN",  "fournisseur")
    result_r, researcher_id = add_wallet("Jules", "chercheur")
    researcher_wallet = get_wallet(researcher_id)
    oracle_wallet     = Wallet.from_seed(config.ORACLE_WALLET_SEED)
    print(f"    Chercheur : {researcher_wallet.address}")
    print(f"    Oracle    : {oracle_wallet.address}")

    # ── 2. Fournisseur mint un slot NFT (code binôme) ─────────────────────────
    print("\n[2] CERN mint un slot de calcul quantique (NFT)...")
    nftoken_id = mint_slot(provider_id, {
        "taxon": 1, "transfer_fee": 5,
        "uri": "quantumgrid://slot/2qubits/bell_state"
    })
    print(f"    NFT slot : {nftoken_id[:24]}...")

    # ── 3. Chercheur achète le slot (code binôme) ─────────────────────────────
    print("\n[3] Jules achète le slot...")
    offer_id = create_sell_offer(provider_id, nftoken_id, 1.0)
    buy_slot(researcher_id, offer_id)
    print("    Slot acheté ✓")

    # ── 4. Oracle génère la condition (ton code) ──────────────────────────────
    print("\n[4] Oracle génère la condition cryptographique...")
    import uuid
    job_id = str(uuid.uuid4())[:16]
    keys   = JobCryptoKeys()
    print(f"    job_id    : {job_id}")
    print(f"    condition : {keys.condition[:30]}...")

    # ── 5. Chercheur crée l'escrow XRPL (ton code) ────────────────────────────
    print("\n[5] Jules crée l'escrow (1 XRP)...")
    async with AsyncWebsocketClient(config.XRPL_WS_URL) as client:
        escrow_response = await client_create_escrow(
            client         = client,
            client_wallet  = researcher_wallet,
            oracle_address = oracle_wallet.address,
            condition      = keys.condition,
            xrp_amount     = 1.0,
            qasm           = BELL_CIRCUIT_QASM,
            shots          = 1024,
            job_id         = job_id,
            ttl_seconds    = 300,
        )
        escrow_tx = escrow_response.result
        tx_result = escrow_tx.get("meta", {}).get("TransactionResult")
        print(f"    EscrowCreate → {tx_result}")
        if tx_result != "tesSUCCESS":
            raise RuntimeError(f"Escrow échoué : {tx_result}")

        # Extraire le sequence
        sequence = (
            escrow_tx.get("Sequence") or
            escrow_tx.get("tx_json", {}).get("Sequence")
        )
        if not sequence:
            from xrpl.models.requests import AccountTx
            resp = await client.request(AccountTx(account=researcher_wallet.address, limit=5))
            for tx_entry in resp.result.get("transactions", []):
                tx_inner = tx_entry.get("tx", tx_entry.get("tx_json", {}))
                if tx_inner.get("TransactionType") == "EscrowCreate":
                    sequence = tx_inner.get("Sequence")
                    break

        job = EscrowJob(
            tx_hash      = escrow_tx.get("hash", ""),
            sequence     = sequence,
            owner        = researcher_wallet.address,
            destination  = oracle_wallet.address,
            amount_drops = str(1_000_000),
            condition    = keys.condition,
            cancel_after = None,
            qasm         = BELL_CIRCUIT_QASM,
            shots        = 1024,
            job_id       = job_id,
        )
        print(f"    Sequence  : {sequence}")

        # ── 6. Oracle exécute le circuit (ton code) ───────────────────────────
        print("\n[6] Oracle exécute le circuit quantique...")
        result = execute_job(qasm=BELL_CIRCUIT_QASM, shots=1024, job_id=job_id)
        if not result.success:
            raise RuntimeError(f"Exécution échouée : {result.error}")
        total = sum(result.counts.values())
        p00 = result.counts.get("00", 0) / total
        p11 = result.counts.get("11", 0) / total
        print(f"    Counts    : {result.counts}")
        print(f"    P(|00⟩)   : {p00:.1%}   P(|11⟩) : {p11:.1%}")

        # ── 7. Oracle libère le paiement (ton code) ───────────────────────────
        print("\n[7] Oracle soumet EscrowFinish (paiement libéré)...")
        finish = await escrow_finish(
            client      = client,
            wallet      = oracle_wallet,
            job         = job,
            fulfillment = keys.fulfillment,
            result_memo = {"job_id": job_id, "counts": result.counts,
                           "result_hash": result.result_hash},
        )
        finish_result = finish.result.get("meta", {}).get("TransactionResult")
        print(f"    EscrowFinish → {finish_result}")

        # ── 8. Mint NFT résultat (code binôme) ────────────────────────────────
        print("\n[8] Mint du NFT résultat (preuve on-chain)...")
        result_nft = mint_slot(provider_id, {
            "taxon": 2,
            "transfer_fee": 0,
            "uri": f"quantumgrid://result/{job_id}/{result.result_hash[:16]}",
        })
        print(f"    NFT résultat : {result_nft[:24]}...")

    print("\n═══════════════════════════════════════════")
    print("  ✓ Démo complétée avec succès !")
    print(f"  Job ID   : {job_id}")
    print(f"  Résultat : {result.counts}")
    print(f"  1 XRP libéré → {oracle_wallet.address[:16]}...")
    print("═══════════════════════════════════════════")


if __name__ == "__main__":
    asyncio.run(run_demo())