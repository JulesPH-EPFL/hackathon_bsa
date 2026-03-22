import asyncio
import os
import uuid
import json
import time
import logging

import httpx
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.wallet import Wallet

import config
from crypto_condition import JobCryptoKeys, verify_fulfillment
from quantum_executor import execute_job
from xrpl_client import (
    client_create_escrow,
    escrow_finish,
    build_memo,
    parse_memos,
)

async def faucet_wallet() -> Wallet:
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post("https://faucet.altnet.rippletest.net/accounts")
        r.raise_for_status()
        data = r.json()
        log.debug(f"Faucet raw response: {data}")

        # Le faucet peut retourner la seed sous différentes clés selon la version
        account = data.get("account", {})
        seed = (
            account.get("secret")
            or account.get("seed")
            or account.get("master_seed")
            or account.get("master_key")
            or data.get("secret")
            or data.get("seed")
            or data.get("master_seed")
        )
        if seed is None:
            raise ValueError(
                f"Impossible de trouver la seed dans la réponse du faucet.\n"
                f"Réponse complète : {data}\n"
                f"Solution : crée un wallet manuellement sur https://xrpl.org/resources/dev-tools/xrp-faucets "
                f"et mets ORACLE_WALLET_SEED et CLIENT_WALLET_SEED dans ton .env"
            )
        return Wallet.from_seed(seed)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("e2e_test")

#  Circuit de test : Bell State 

BELL_CIRCUIT_QASM = """
OPENQASM 2.0;
include "qelib1.inc";

qreg q[2];
creg c[2];

h q[0];
cx q[0], q[1];
measure q[0] -> c[0];
measure q[1] -> c[1];
"""

#  Test 
async def run_e2e_test():
    log.info("═══ QuantumGrid Oracle — Test E2E ═══")

    async with AsyncWebsocketClient(config.XRPL_WS_URL) as client:

        # 1. Wallets de test
        log.info("1. Création des wallets testnet...")
        if config.ORACLE_WALLET_SEED:
            oracle_wallet = Wallet.from_seed(config.ORACLE_WALLET_SEED)
            log.info("   Oracle  : wallet chargé depuis .env")
        else:
            oracle_wallet = await faucet_wallet()
            log.info("   Oracle  : wallet créé via faucet")

        client_seed = os.getenv("CLIENT_WALLET_SEED", "")
        if client_seed:
            client_wallet = Wallet.from_seed(client_seed)
            log.info("   Client  : wallet chargé depuis .env")
        else:
            client_wallet = await faucet_wallet()
            log.info("   Client  : wallet créé via faucet")

        log.info(f"   Oracle  : {oracle_wallet.address}")
        log.info(f"   Client  : {client_wallet.address}")

        log.info("2. Oracle génère la condition (quote)...")
        job_id = str(uuid.uuid4())[:16]
        keys   = JobCryptoKeys()
        log.info(f"   Job ID    : {job_id}")
        log.info(f"   Condition : {keys.condition[:40]}...")

        # 3. Client crée l'EscrowCreate
        log.info("3. Client crée l'EscrowCreate (1 XRP)...")
        from xrpl_client import EscrowJob

        try:
            escrow_response = await client_create_escrow(
                client         = client,
                client_wallet  = client_wallet,
                oracle_address = oracle_wallet.address,
                condition      = keys.condition,
                xrp_amount     = 1.0,
                qasm           = BELL_CIRCUIT_QASM.strip(),
                shots          = 1024,
                job_id         = job_id,
                ttl_seconds    = 300,
            )
            escrow_tx = escrow_response.result
            tx_result = escrow_tx.get("meta", {}).get("TransactionResult", "?")
            log.info(f"   EscrowCreate → {tx_result}")
            log.info(f"   TX hash     : {escrow_tx.get('hash', '')}")
            log.debug(f"   Full response keys: {list(escrow_tx.keys())}")

            if tx_result != "tesSUCCESS":
                log.error(f"EscrowCreate échoué : {tx_result}")
                return
        except Exception as e:
            log.error(f"Erreur EscrowCreate : {e}")
            return

        # xrpl-py peut le mettre à différents endroits selon la version
        def extract_sequence(tx: dict) -> int:
            candidates = [
                tx.get("Sequence"),
                tx.get("tx_json", {}).get("Sequence"),
                tx.get("transaction", {}).get("Sequence"),
            ]
            for v in candidates:
                if v is not None and v != 0:
                    return int(v)
            return None

        sequence = extract_sequence(escrow_tx)

        if sequence is None:
            # Dernier recours : requêter le ledger directement pour retrouver l'escrow
            log.warning("Sequence introuvable dans la réponse — requête account_tx...")
            from xrpl.models.requests import AccountTx
            resp = await client.request(AccountTx(account=client_wallet.address, limit=5))
            txs = resp.result.get("transactions", [])
            log.debug(f"   Dernières txs: {[t.get('tx', {}).get('TransactionType') for t in txs]}")
            for tx_entry in txs:
                tx_inner = tx_entry.get("tx", tx_entry.get("tx_json", {}))
                if tx_inner.get("TransactionType") == "EscrowCreate":
                    sequence = tx_inner.get("Sequence")
                    log.info(f"   Sequence trouvé via account_tx: {sequence}")
                    break

        if sequence is None:
            log.error("Impossible de trouver le Sequence — abandon")
            return

        log.info(f"   Sequence utilisé : {sequence}")
        job = EscrowJob(
            tx_hash      = escrow_tx.get("hash", ""),
            sequence     = sequence,
            owner        = client_wallet.address,
            destination  = oracle_wallet.address,
            amount_drops = str(1_000_000),
            condition    = keys.condition,
            cancel_after = None,
            qasm         = BELL_CIRCUIT_QASM.strip(),
            shots        = 1024,
            job_id       = job_id,
        )
        log.info(f"   EscrowJob sequence={job.sequence} owner={job.owner[:12]}...")

        # 4. Oracle exécute le circuit quantique
        log.info("4. Oracle exécute le circuit (Bell State)...")
        result = execute_job(
            qasm   = job.qasm,
            shots  = job.shots,
            job_id = job.job_id,
        )

        if not result.success:
            log.error(f"Exécution quantique échouée : {result.error}")
            return

        log.info(f"   Backend       : {result.backend}")
        log.info(f"   Counts        : {result.counts}")
        log.info(f"   Temps exec    : {result.execution_time:.3f}s")
        log.info(f"   Result hash   : {result.result_hash[:32]}...")

        # Vérification Bell State : on attend ~50% |00⟩ et ~50% |11⟩
        total = sum(result.counts.values())
        p00 = result.counts.get("00", 0) / total
        p11 = result.counts.get("11", 0) / total
        log.info(f"   P(|00⟩) = {p00:.2%}   P(|11⟩) = {p11:.2%}")
        assert abs(p00 - 0.5) < 0.1, f"Distribution inattendue : {result.counts}"
        log.info("   ✓ Bell State validé (50/50 attendu)")

        # 5. Oracle vérifie le fulfillment avant de le révéler
        assert verify_fulfillment(keys.fulfillment, keys.condition), \
            "Vérification fulfillment/condition échouée !"
        log.info("5. Fulfillment vérifié cryptographiquement ✓")

        # 6. Oracle soumet EscrowFinish
        log.info("6. Oracle soumet EscrowFinish (révèle fulfillment)...")
        result_memo = {
            "job_id":      job.job_id,
            "backend":     result.backend,
            "shots":       result.shots,
            "counts":      result.counts,
            "result_hash": result.result_hash,
        }

        try:
            finish_response = await escrow_finish(
                client      = client,
                wallet      = oracle_wallet,
                job         = job,
                fulfillment = keys.fulfillment,
                result_memo = result_memo,
            )
            finish_result = finish_response.result.get("meta", {}).get("TransactionResult", "?")
            log.info(f"   EscrowFinish → {finish_result}")
            log.info(f"   TX hash      : {finish_response.result.get('hash', '')}")

            if finish_result == "tesSUCCESS":
                log.info("")
                log.info("═══════════════════════════════════════")
                log.info(" ✓ Job QuantumGrid complété avec succès ")
                log.info(f"  XRP libérés → {oracle_wallet.address[:12]}...")
                log.info(f"  Résultats publiés on-chain")
                log.info("═══════════════════════════════════════")
            else:
                log.error(f"EscrowFinish échoué : {finish_result}")

        except Exception as e:
            log.error(f"Erreur EscrowFinish : {e}")


if __name__ == "__main__":
    asyncio.run(run_e2e_test())

    