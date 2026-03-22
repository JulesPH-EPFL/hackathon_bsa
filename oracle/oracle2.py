import asyncio
import logging
import sys
import uuid
from functools import partial
from typing import Optional

import structlog
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.wallet import Wallet

import config
from crypto_condition import JobCryptoKeys
from quantum_executor import execute_job, QuantumResult
from escrow_monitor import monitor_escrows, register_escrow, unregister_escrow
from xrpl_client import (
    XRPLOracleWatcher,
    EscrowJob,
    escrow_finish,
    pay_provider,
)

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, config.LOG_LEVEL, logging.INFO)
    )
)
log = structlog.get_logger()

COMMISSION = 0.10


#  Job Store 

class InMemoryJobStore:
    def __init__(self):
        self._store: dict[str, dict] = {}

    def create_quote(self, job_id: str) -> JobCryptoKeys:
        keys = JobCryptoKeys()
        self._store[job_id] = {"keys": keys, "status": "quoted"}
        log.debug("quote_created", job_id=job_id)
        return keys

    def get_fulfillment(self, job_id: str) -> Optional[str]:
        e = self._store.get(job_id)
        return e["keys"].fulfillment if e else None

    def get_condition(self, job_id: str) -> Optional[str]:
        e = self._store.get(job_id)
        return e["keys"].condition if e else None

    def mark_done(self, job_id: str):
        if job_id in self._store:
            self._store[job_id]["status"] = "done"


JOB_STORE = InMemoryJobStore()


#  Quote (appelé par bridge.py avant l'escrow) 

async def handle_quote_request(job_id: Optional[str] = None) -> dict:

    jid  = job_id or str(uuid.uuid4())[:16]
    keys = JOB_STORE.create_quote(jid)
    log.info("quote_issued", job_id=jid, condition=keys.condition[:20])
    return {
        "job_id":    jid,
        "condition": keys.condition,
        "oracle":    config.ORACLE_ADDRESS,
        "dest_tag":  config.QUANTUMGRID_TAG,
    }


#  Validation 

def validate_job(job: EscrowJob) -> Optional[str]:
    if not job.qasm or len(job.qasm) < 10:
        return "Payload vide ou trop court"
    if job.shots <= 0 or job.shots > config.MAX_SHOTS:
        return f"Shots invalide : {job.shots}"
    if int(job.amount_drops) < config.MIN_ESCROW_DROPS:
        return f"Montant insuffisant : {job.amount_drops} drops"
    return None


#  Traitement automatique d'un job 

async def process_job(
    client: AsyncWebsocketClient,
    wallet: Wallet,
    job:    EscrowJob,
) -> None:

    log.info("job_received",
             job_id     = job.job_id,
             amount_xrp = str(int(job.amount_drops) / 1_000_000),
             owner      = job.owner[:16])

    # 1. Validation
    error = validate_job(job)
    if error:
        log.warning("job_invalid", job_id=job.job_id, reason=error)
        return

    # Enregistrer dans le monitor anti-timeout
    register_escrow(job)

    # Créer le quote si pas encore fait (cas où oracle détecte on-chain)
    if not JOB_STORE.get_fulfillment(job.job_id):
        JOB_STORE.create_quote(job.job_id)

    # 2. Exécution quantique
    log.info("job_executing", job_id=job.job_id)
    loop = asyncio.get_event_loop()
    result: QuantumResult = await loop.run_in_executor(
        None, lambda: execute_job(
            qasm   = job.qasm,
            shots  = job.shots,
            job_id = job.job_id,
        )
    )

    if not result.success:
        log.error("job_failed", job_id=job.job_id, error=result.error)
        unregister_escrow(job.job_id)
        return

    log.info("job_executed",
             job_id      = job.job_id,
             backend     = result.backend,
             elapsed_s   = f"{result.execution_time:.2f}",
             result_hash = result.result_hash[:16],
             ibm_job_id  = result.ibm_job_id or "simulator")

    # 3. EscrowFinish — libère le paiement
    fulfillment = JOB_STORE.get_fulfillment(job.job_id)
    if not fulfillment:
        log.error("fulfillment_not_found", job_id=job.job_id)
        unregister_escrow(job.job_id)
        return

    result_memo = {
        "job_id":       job.job_id,
        "backend":      result.backend,
        "shots":        result.shots,
        "counts":       result.counts,
        "result_hash":  result.result_hash,
        "ibm_job_id":   result.ibm_job_id,
        "ibm_url":      result.ibm_verification_url(),
        "elapsed_s":    round(result.execution_time, 3),
    }

    try:
        response = await escrow_finish(
            client      = client,
            wallet      = wallet,
            job         = job,
            fulfillment = fulfillment,
            result_memo = result_memo,
        )
        tx_result = response.result.get("meta", {}).get("TransactionResult", "?")
        log.info("escrow_finished",
                 job_id    = job.job_id,
                 tx_result = tx_result,
                 tx_hash   = response.result.get("hash", ""))

        if tx_result != "tesSUCCESS":
            log.error("escrow_finish_failed", job_id=job.job_id, result=tx_result)
            unregister_escrow(job.job_id)
            return

    except Exception as e:
        log.error("escrow_finish_error", job_id=job.job_id, error=str(e))
        unregister_escrow(job.job_id)
        return

    # 4. Payer le fournisseur (90%)
    try:
        # Trouver l'adresse du fournisseur depuis wallets.json
        from src.wallets import get_wallet as get_provider_wallet
        provider_wallet = get_provider_wallet("fournisseur_cern")
        await pay_provider(
            client           = client,
            oracle_wallet    = wallet,
            provider_address = provider_wallet.address,
            total_drops      = int(job.amount_drops),
            commission_pct   = COMMISSION,
        )
        log.info("provider_paid",
                 job_id   = job.job_id,
                 provider = provider_wallet.address[:16],
                 amount   = f"{int(job.amount_drops) * (1 - COMMISSION) / 1_000_000:.2f} XRP")
    except Exception as e:
        log.error("provider_payment_failed", job_id=job.job_id, error=str(e))

    # 5. NFT résultat
    try:
        from src.nft import mint_slot
        nft_id = await loop.run_in_executor(
            None, partial(mint_slot, "fournisseur_cern", {
                "taxon":        2,
                "transfer_fee": 0,
                "uri":          f"quantumgrid://result/{job.job_id}/{result.result_hash[:12]}",
            })
        )
        log.info("nft_minted", job_id=job.job_id, nft_id=nft_id[:24])
    except Exception as e:
        log.warning("nft_mint_failed", job_id=job.job_id, error=str(e))

    JOB_STORE.mark_done(job.job_id)
    unregister_escrow(job.job_id)
    log.info("job_complete", job_id=job.job_id)


#  Boucle principale 

async def run_oracle():
    if not config.ORACLE_WALLET_SEED:
        log.error("ORACLE_WALLET_SEED manquant dans .env")
        sys.exit(1)

    wallet = Wallet.from_seed(config.ORACLE_WALLET_SEED)
    log.info("oracle_started",
             address   = wallet.address,
             network   = config.XRPL_WS_URL,
             simulator = config.USE_SIMULATOR)

    async with AsyncWebsocketClient(config.XRPL_WS_URL) as client:

        # Monitor anti-timeout en tâche de fond
        asyncio.create_task(monitor_escrows(client, wallet, interval=30))
        log.info("escrow_monitor_started")

        # Écoute les nouveaux escrows — traite chacun automatiquement
        async with XRPLOracleWatcher(wallet.address, config.XRPL_WS_URL) as watcher:
            log.info("watching_ledger", oracle=wallet.address[:16])
            async for job in watcher.escrow_jobs():
                asyncio.create_task(process_job(client, wallet, job))


if __name__ == "__main__":
    try:
        asyncio.run(run_oracle())
    except KeyboardInterrupt:
        log.info("oracle_stopped")