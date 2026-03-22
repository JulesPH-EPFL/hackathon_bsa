import asyncio
import json
import time
import sys
import os
from functools import partial

from src.wallets import add_wallet, get_wallet
from src.nft import mint_slot, create_sell_offer, buy_slot

import src.config2 as config
from src.crypto_condition import JobCryptoKeys
from src.quantum_executor import execute_job
from src.xrpl_client import client_create_escrow, escrow_finish, EscrowJob, pay_provider
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.wallet import Wallet

COMMISSION = 0.10

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


async def run_demo(provider_id: str, researcher_id: str):
    print("═══════════════════════════════════════════")
    print("     QuantumGrid — Démo Hackathon")
    print("═══════════════════════════════════════════")

    loop = asyncio.get_event_loop()

    # ── 1. Wallets ────────────────────────────────────────────────────────────
    print("\n[1] Wallets prêts...")
    researcher_wallet = get_wallet(researcher_id)
    oracle_wallet     = Wallet.from_seed(config.ORACLE_WALLET_SEED)
    print(f"    Chercheur : {researcher_wallet.address}")
    print(f"    Oracle    : {oracle_wallet.address}")

    # ── 2. Fournisseur mint un slot NFT ───────────────────────────────────────
    print("\n[2] CERN mint un slot de calcul quantique (NFT)...")
    nftoken_id = await loop.run_in_executor(
        None, partial(mint_slot, provider_id, {
            "taxon": 1, "transfer_fee": 5,
            "uri": "quantumgrid://slot/2qubits/bell_state"
        })
    )
    print(f"    NFT slot : {nftoken_id[:24]}...")

    # ── 3. Chercheur achète le slot ───────────────────────────────────────────
    print("\n[3] Jules achète le slot...")
    offer_id = await loop.run_in_executor(
        None, partial(create_sell_offer, provider_id, nftoken_id, 0)
    )
    await loop.run_in_executor(
        None, partial(buy_slot, researcher_id, offer_id)
    )
    print("    Slot acheté ✓")

    # ── 4. Oracle génère la condition ─────────────────────────────────────────
    print("\n[4] Oracle génère la condition cryptographique...")
    import uuid
    job_id = str(uuid.uuid4())[:16]
    keys   = JobCryptoKeys()
    print(f"    job_id    : {job_id}")
    print(f"    condition : {keys.condition[:30]}...")

    # ── 5. Chercheur crée l'escrow XRPL ──────────────────────────────────────
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

        # ── 6. Oracle exécute le circuit ──────────────────────────────────────
        print("\n[6] Oracle exécute le circuit quantique...")
        result = await loop.run_in_executor(
            None, partial(execute_job, BELL_CIRCUIT_QASM, 1024, job_id)
        )
        if not result.success:
            raise RuntimeError(f"Exécution échouée : {result.error}")
        total = sum(result.counts.values())
        p00 = result.counts.get("00", 0) / total
        p11 = result.counts.get("11", 0) / total
        print(f"    Counts    : {result.counts}")
        print(f"    P(|00⟩)   : {p00:.1%}   P(|11⟩) : {p11:.1%}")

        # ── 7. Oracle libère le paiement ──────────────────────────────────────
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
        
        # ── 7b. Oracle paie le fournisseur ────────────────────────────────────
        print("\n[7b] Oracle redistribue le paiement au fournisseur...")
        provider_wallet = get_wallet(provider_id)
        payment = await pay_provider(
            client           = client,
            oracle_wallet    = oracle_wallet,
            provider_address = provider_wallet.classic_address,
            total_drops      = 1_000_000,
            commission_pct   = COMMISSION,
            job_id           = job_id,
        )
        payment_result = payment.result.get("meta", {}).get("TransactionResult")
        print(f"    Payment Fournisseur → {payment_result}")

        # ── 8. Mint NFT résultat ──────────────────────────────────────────────
        print("\n[8] Mint du NFT résultat (preuve on-chain)...")
        result_nft = await loop.run_in_executor(
            None, partial(mint_slot, provider_id, {
                "taxon": 2,
                "transfer_fee": 0,
                "uri": f"quantumgrid://result/{job_id}/{result.result_hash[:16]}",
            })
        )
        print(f"    NFT résultat : {result_nft[:24]}...")

    print("\n═══════════════════════════════════════════")
    print("  ✓ Démo complétée avec succès !")
    print(f"  Job ID   : {job_id}")
    print(f"  Résultat : {result.counts}")
    print(f"  1 XRP libéré → {oracle_wallet.address[:16]}...")
    print("═══════════════════════════════════════════")


if __name__ == "__main__":
    _, provider_id = add_wallet("CERN", "fournisseur")
    result_r, researcher_id = add_wallet("Jules", "chercheur")
    asyncio.run(run_demo(provider_id, researcher_id))