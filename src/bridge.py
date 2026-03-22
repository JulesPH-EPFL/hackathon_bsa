import asyncio
import json
import time
import sys
import os
from functools import partial

from src.wallets import get_wallet, create_wallet
from src.nft import mint_slot, create_sell_offer, buy_slot

import src.config2 as config
from src.crypto_condition import JobCryptoKeys
from src.quantum_executor import execute_job, verify_ibm_job
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


async def run_demo(provider_seed: str, researcher_seed: str):
    researcher_wallet = get_wallet(researcher_seed)
    provider_wallet_data = get_wallet(provider_seed)
    print("═══════════════════════════════════════════")
    print("     QuantumGrid — Démo Hackathon")
    print("═══════════════════════════════════════════")

    loop = asyncio.get_event_loop()

    # ── 1. Wallets 
    print("\n[1] Wallets prêts...")

    oracle_wallet     = Wallet.from_seed(config.ORACLE_WALLET_SEED)
    print(f"    Chercheur : {researcher_wallet.address}")
    print(f"    Oracle    : {oracle_wallet.address}")

    # ── 2. Chercheur paie et certifie ─────────────────────────────────────────
    print("\n[2] Arnaud paie le CERN et crée son NFT reçu...")
    from src.nft import buy_and_certify
    receipt = await loop.run_in_executor(
        None, partial(buy_and_certify,
            researcher_seed,
            provider_wallet_data.address,
            30,
            "MIN",
            "2026-03-22",
            0.1,
            "cern_quantum"
        )
    )
    print(f"    Paiement tx : {receipt['tx_hash'][:24]}...")
    print(f"    NFT reçu    : {receipt['nftoken_id'][:24]}...")

    # ── 4. Oracle génère la condition 
    print("\n[4] Oracle génère la condition cryptographique...")
    import uuid
    job_id = str(uuid.uuid4())[:16]
    keys   = JobCryptoKeys()
    print(f"    job_id    : {job_id}")
    print(f"    condition : {keys.condition[:30]}...")

    # ── 5. Chercheur crée l'escrow XRPL 
    print("\n[5] Arnaud crée l'escrow (1 XRP)...")
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

        # ── 6. Oracle exécute le circuit 
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

        # ── 7. Vérification IBM (si mode réel) 
        if not config.USE_SIMULATOR and result.ibm_job_id:
            print("\n[7] Vérification du job sur IBM Quantum...")
            verification = verify_ibm_job(result.ibm_job_id, result.counts)
            print(f"    IBM Job ID  : {result.ibm_job_id}")
            print(f"    Statut IBM  : {verification.get('status', '?')}")
            print(f"    Backend IBM : {verification.get('backend', '?')}")
            print(f"    Counts OK   : {verification.get('counts_match', False)}")
            print(f"    URL preuve  : {result.ibm_verification_url()}")
            if not verification["verified"]:
                raise RuntimeError(f"Vérification IBM échouée : {verification['message']}")
            print("    ✓ Job IBM vérifié — paiement autorisé")
        else:
            print("\n[7] Mode simulateur — vérification IBM ignorée")

        # ── 7b. Oracle libère le paiement 
        print("\n[7b] Oracle soumet EscrowFinish (paiement libéré)...")
        result_memo = {
            "job_id":      job_id,
            "counts":      result.counts,
            "result_hash": result.result_hash,
            "ibm_job_id":  result.ibm_job_id,
            "ibm_url":     result.ibm_verification_url(),
        }
        finish = await escrow_finish(
            client      = client,
            wallet      = oracle_wallet,
            job         = job,
            fulfillment = keys.fulfillment,
            result_memo = result_memo,
        )
        finish_result = finish.result.get("meta", {}).get("TransactionResult")
        print(f"    EscrowFinish → {finish_result}")

        print("\n[7c] Oracle reverse la part du CERN...")
        provider_wallet_data = get_wallet(provider_seed)
        await pay_provider(
            client           = client,
            oracle_wallet    = oracle_wallet,
            provider_address = provider_wallet_data.address,
            total_drops      = 1_000_000,
            commission_pct   = COMMISSION,
            job_id           = job_id,
        )

        # ── 8. Chercheur minte NFT résultat ──────────────────────────────────────
        print("\n[8] Mint du NFT résultat (preuve on-chain)...")
        result_nft = await loop.run_in_executor(
            None, partial(mint_slot, researcher_seed, {
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
    provider   = create_wallet()
    researcher = create_wallet()
    print(f"Fournisseur CERN   : {provider['address']}")
    print(f"Chercheur Arnaud   : {researcher['address']}")
    asyncio.run(run_demo(provider["seed"], researcher["seed"]))