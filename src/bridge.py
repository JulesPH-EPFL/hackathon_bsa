import asyncio
import json
import time
from functools import partial

from src.wallets import get_wallet, create_wallet
from src.nft import mint_slot, buy_and_certify
from src.xrpl_client import client_create_escrow, escrow_finish, EscrowJob, pay_provider
from src.crypto_condition import JobCryptoKeys
from src.quantum_executor import execute_job, verify_ibm_job
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.wallet import Wallet
from xrpl.models.requests import AccountTx
import src.config2 as config
import uuid

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


async def run_demo(provider_address: str, researcher_seed: str, amount_xrp: float = 1.0):
    researcher_wallet = get_wallet(researcher_seed)
    oracle_wallet     = Wallet.from_seed(config.ORACLE_WALLET_SEED)
    loop              = asyncio.get_event_loop()

    print("═══════════════════════════════════════════")
    print("     QuantumGrid — Démo Hackathon")
    print("═══════════════════════════════════════════")

    # ── 1. Wallets ────────────────────────────────────────────────────────────
    print("\n[1] Wallets prêts...")
    print(f"    Chercheur : {researcher_wallet.address}")
    print(f"    Oracle    : {oracle_wallet.address}")

    # ── 2. Chercheur paie et certifie ─────────────────────────────────────────
    print("\n[2] Arnaud paie le CERN et crée son NFT reçu...")
    receipt = await loop.run_in_executor(
        None, partial(buy_and_certify,
            researcher_seed,
            provider_address,
            int(amount_xrp * 10),
            "QBT",
            "2026-03-22",
            0.1,
            "cern_quantum"
        )
    )
    print(f"    Paiement tx : {receipt['tx_hash'][:24]}...")
    print(f"    NFT reçu    : {receipt['nftoken_id'][:24]}...")

    # ── 3. Oracle génère la condition ─────────────────────────────────────────
    print("\n[3] Oracle génère la condition cryptographique...")
    job_id = str(uuid.uuid4())[:16]
    keys   = JobCryptoKeys()
    print(f"    job_id    : {job_id}")
    print(f"    condition : {keys.condition[:30]}...")

    # ── 4. Chercheur crée l'escrow XRPL ──────────────────────────────────────
    print("\n[4] Arnaud crée l'escrow...")
    async with AsyncWebsocketClient(config.XRPL_WS_URL) as client:
        escrow_response = await client_create_escrow(
            client         = client,
            client_wallet  = researcher_wallet,
            oracle_address = oracle_wallet.address,
            condition      = keys.condition,
            xrp_amount     = amount_xrp,
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
            amount_drops = str(int(amount_xrp * 1_000_000)),
            condition    = keys.condition,
            cancel_after = None,
            qasm         = BELL_CIRCUIT_QASM,
            shots        = 1024,
            job_id       = job_id,
        )
        print(f"    Sequence  : {sequence}")

        # ── 5. Oracle exécute le circuit ──────────────────────────────────────
        print("\n[5] Oracle exécute le circuit quantique...")
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

        # ── 6. Vérification IBM ───────────────────────────────────────────────
        if not config.USE_SIMULATOR and result.ibm_job_id:
            print("\n[6] Vérification IBM Quantum...")
            verification = verify_ibm_job(result.ibm_job_id, result.counts)
            if not verification["verified"]:
                raise RuntimeError(f"Vérification IBM échouée : {verification['message']}")
            print("    ✓ Job IBM vérifié")
        else:
            print("\n[6] Mode simulateur — vérification IBM ignorée")

        # ── 7. EscrowFinish ───────────────────────────────────────────────────
        print("\n[7] Oracle soumet EscrowFinish...")
        finish = await escrow_finish(
            client      = client,
            wallet      = oracle_wallet,
            job         = job,
            fulfillment = keys.fulfillment,
            result_memo = {
                "job_id":      job_id,
                "counts":      result.counts,
                "result_hash": result.result_hash,
            },
        )
        finish_result = finish.result.get("meta", {}).get("TransactionResult")
        print(f"    EscrowFinish → {finish_result}")

        # ── 7b. Redistribution fournisseur ────────────────────────────────────
        print("\n[7b] Oracle redistribue au fournisseur...")
        await pay_provider(
            client           = client,
            oracle_wallet    = oracle_wallet,
            provider_address = provider_address,
            total_drops      = int(amount_xrp * 1_000_000),
            commission_pct   = COMMISSION,
            job_id           = job_id,
        )
        print(f"    {amount_xrp * (1 - COMMISSION):.2f} XRP → Fournisseur")
        print(f"    {amount_xrp * COMMISSION:.2f} XRP → Oracle")

        # ── 8. NFT résultat ───────────────────────────────────────────────────
        print("\n[8] Chercheur minte NFT résultat...")
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
    print(f"  {amount_xrp * (1-COMMISSION):.2f} XRP → {provider_address[:16]}...")
    print("═══════════════════════════════════════════")
    
    return {
        "job_id":      job_id,
        "counts":      result.counts,
        "result_hash": result.result_hash,
        "receipt_nft": receipt["nftoken_id"],
        "result_nft":  result_nft,
    }


if __name__ == "__main__":
    provider   = create_wallet()
    researcher = create_wallet()
    print(f"Fournisseur : {provider['address']}")
    print(f"Chercheur   : {researcher['address']}")
    asyncio.run(run_demo(provider["address"], researcher["seed"]))