import asyncio
import json
import logging
import sys
import uuid
from typing import Optional

import structlog
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.wallet import Wallet

import config
from crypto_condition import JobCryptoKeys, verify_fulfillment
from quantum_executor import execute_job, QuantumResult
from escrow_monitor import monitor_escrows, register_escrow, unregister_escrow
from xrpl_client import (
    XRPLOracleWatcher,
    EscrowJob,
    escrow_finish,
    escrow_cancel,
)

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, config.LOG_LEVEL, logging.INFO)
    )
)
log = structlog.get_logger()


#  Job Store en mémoire (inchangé) 

class InMemoryJobStore:
    def __init__(self):
        self._store: dict[str, dict] = {}

    def create_quote(self, job_id: str) -> JobCryptoKeys:
        keys = JobCryptoKeys()
        self._store[job_id] = {"keys": keys, "status": "quoted"}
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

#  Validation des jobs entrants (exemples de règles simples)
def validate_job(job: EscrowJob) -> Optional[str]:
    if not job.qasm or len(job.qasm) < 10:
        return "Circuit QASM vide ou trop court"
    if job.shots <= 0 or job.shots > config.MAX_SHOTS:
        return f"Shots invalide : {job.shots}"
    if int(job.amount_drops) < config.MIN_ESCROW_DROPS:
        return f"Montant insuffisant : {job.amount_drops} drops"
    return None


#  Traitement d'un job : exécution du circuit et fulfillment de l'escrow
async def process_job(
    client: AsyncWebsocketClient,
    wallet: Wallet,
    job:    EscrowJob,
) -> None:

    log.info("job_received",
             job_id     = job.job_id,
             amount_xrp = str(int(job.amount_drops) / 1_000_000),
             shots      = job.shots,
             owner      = job.owner)

    error = validate_job(job)
    if error:
        log.warning("job_invalid", job_id=job.job_id, reason=error)
        return

    register_escrow(job)

    keys = JOB_STORE.create_quote(job.job_id)

    log.info("job_executing", job_id=job.job_id)

    result: QuantumResult = execute_job(
        qasm   = job.qasm,
        shots  = job.shots,
        job_id = job.job_id,
    )

    if not result.success:
        log.error("job_failed", job_id=job.job_id, error=result.error)
        unregister_escrow(job.job_id)
        return

    log.info("job_executed",
             job_id      = job.job_id,
             backend     = result.backend,
             elapsed_s   = f"{result.execution_time:.2f}",
             result_hash = result.result_hash[:16])

    result_summary = {
        "job_id":       job.job_id,
        "backend":      result.backend,
        "shots":        result.shots,
        "counts":       result.counts,
        "result_hash":  result.result_hash,
        "circuit_hash": result.circuit_hash,
        "ibm_job_id":   result.ibm_job_id,
        "ibm_url":      result.ibm_verification_url(),
        "elapsed_s":    round(result.execution_time, 3),
    }

    fulfillment = JOB_STORE.get_fulfillment(job.job_id)
    if not fulfillment:
        log.error("fulfillment_not_found", job_id=job.job_id)
        unregister_escrow(job.job_id)
        return

    try:
        response = await escrow_finish(
            client      = client,
            wallet      = wallet,
            job         = job,
            fulfillment = fulfillment,
            result_memo = result_summary,
        )
        tx_result = response.result.get("meta", {}).get("TransactionResult", "?")
        log.info("escrow_finished",
                 job_id    = job.job_id,
                 tx_result = tx_result,
                 tx_hash   = response.result.get("hash", ""))
        JOB_STORE.mark_done(job.job_id)
        unregister_escrow(job.job_id)

    except Exception as e:
        log.error("escrow_finish_failed", job_id=job.job_id, error=str(e))


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

        asyncio.create_task(
            monitor_escrows(client, wallet, interval=30)
        )
        log.info("escrow_monitor_started")

        async with XRPLOracleWatcher(wallet.address, config.XRPL_WS_URL) as watcher:
            async for job in watcher.escrow_jobs():
                asyncio.create_task(process_job(client, wallet, job))


if __name__ == "__main__":
    try:
        asyncio.run(run_oracle())
    except KeyboardInterrupt:
        log.info("oracle_stopped")