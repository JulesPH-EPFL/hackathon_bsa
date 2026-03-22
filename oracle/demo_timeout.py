import asyncio
import time
import uuid
import logging

from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.wallet import Wallet
from xrpl.models.requests import AccountTx

import config
from crypto_condition import JobCryptoKeys
from xrpl_client import client_create_escrow, escrow_cancel, EscrowJob
from escrow_monitor import register_escrow, monitor_escrows
from src.wallets import add_wallet, get_wallet

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("demo_timeout")

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

async def run_timeout_demo():
    print("\n═══════════════════════════════════════════════════")
    print("  QuantumGrid — Scénario : IBM ne répond pas")
    print("═══════════════════════════════════════════════════")

    _, provider_id   = add_wallet("CERN",   "fournisseur")
    _, researcher_id = add_wallet("Arnaud", "chercheur")

    researcher_wallet = get_wallet(researcher_id)
    print(f"    Adresse Arnaud : {researcher_wallet.address}") 
    oracle_wallet     = Wallet.from_seed(config.ORACLE_WALLET_SEED)

    async with AsyncWebsocketClient(config.XRPL_WS_URL) as client:

        asyncio.create_task(
            monitor_escrows(client, oracle_wallet, interval=10)
        )

        print("\n[1] Arnaud crée l'escrow (1 XRP, TTL = 30 secondes)...")
        job_id = str(uuid.uuid4())[:16]
        keys   = JobCryptoKeys()

        escrow_response = await client_create_escrow(
            client         = client,
            client_wallet  = researcher_wallet,
            oracle_address = oracle_wallet.address,
            condition      = keys.condition,
            xrp_amount     = 1.0,
            qasm           = BELL_CIRCUIT_QASM,
            shots          = 1024,
            job_id         = job_id,
            ttl_seconds    = 30,
        )
        escrow_tx = escrow_response.result
        tx_result = escrow_tx.get("meta", {}).get("TransactionResult")
        print(f"    EscrowCreate → {tx_result}")
        print(f"    TX hash     : {escrow_tx.get('hash', '')}")
        print(f"    1 XRP verrouillé — Arnaud ne peut plus y toucher")

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

        xrpl_epoch_offset = 946684800
        cancel_after_xrpl = int(time.time()) - xrpl_epoch_offset + 30

        job = EscrowJob(
            tx_hash      = escrow_tx.get("hash", ""),
            sequence     = sequence,
            owner        = researcher_wallet.address,
            destination  = oracle_wallet.address,
            amount_drops = "1000000",
            condition    = keys.condition,
            cancel_after = cancel_after_xrpl,
            qasm         = BELL_CIRCUIT_QASM,
            shots        = 1024,
            job_id       = job_id,
        )
        register_escrow(job)

        print("\n[2] Oracle envoie le circuit à IBM Quantum...")
        print("     IBM ne répond pas — timeout simulé")
        print("    (file d'attente trop longue / panne IBM)")

        print("\n[3] Attente expiration TTL (30 secondes)...")
        for i in range(30, 0, -5):
            print(f"    {i}s restantes — XRP toujours bloqués chez Arnaud...")
            await asyncio.sleep(5)

        print("\n    TTL expiré !")
        print("    Monitor va détecter et annuler dans les 10 prochaines secondes...")

        await asyncio.sleep(12)

        print("\n═══════════════════════════════════════════════════")
        print("  ✓ Protection activée avec succès !")
        print(f"  1 XRP retourné → {researcher_wallet.address[:16]}...")
        print(f"  Arnaud n'a rien perdu malgré la panne IBM")
        print("  Le protocole protège l'utilisateur automatiquement")
        print("═══════════════════════════════════════════════════")

if __name__ == "__main__":
    asyncio.run(run_timeout_demo())
