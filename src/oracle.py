import asyncio
import json
import logging
import sys
import uuid
from typing import Optional

import structlog
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.wallet import Wallet

import src.config2 as config2
from crypto_condition import JobCryptoKeys, verify_fulfillment
from quantum_executor import execute_job, QuantumResult
from xrpl_client import (
    XRPLOracleWatcher,
    EscrowJob,
    escrow_finish,
    escrow_cancel,
)

# ─── Logging ──────────────────────────────────────────────────────────────────

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, config2.LOG_LEVEL, logging.INFO)
    )
)
log = structlog.get_logger()


# ─── Validation ───────────────────────────────────────────────────────────────

def validate_job(job: EscrowJob) -> Optional[str]:
    if not job.qasm or len(job.qasm) < 10:
        return "Circuit QASM vide ou trop court"
    if job.shots <= 0 or job.shots > config2.MAX_SHOTS:
        return f"Nombre de shots invalide : {job.shots} (max {config2.MAX_SHOTS})"
    if int(job.amount_drops) < config2.MIN_ESCROW_DROPS:
        return f"Montant insuffisant : {job.amount_drops} drops"
    return None


# ─── Traitement d'un job ──────────────────────────────────────────────────────

async def process_job(
    client:  AsyncWebsocketClient,
    wallet:  Wallet,
    job:     EscrowJob,
) -> None:
 
    log.info("job_received",
             job_id=job.job_id,
             amount_xrp=str(int(job.amount_drops) / 1_000_000),
             shots=job.shots,
             owner=job.owner)

    # 1. Validation
    error = validate_job(job)
    if error:
        log.warning("job_invalid", job_id=job.job_id, reason=error)
        return

    log.info("job_executing", job_id=job.job_id)

    # 3. Exécution quantique
    result: QuantumResult = execute_job(
        qasm   = job.qasm,
        shots  = job.shots,
        job_id = job.job_id,
    )

    if not result.success:
        log.error("job_failed",
                  job_id=job.job_id,
                  error=result.error)
        return

    log.info("job_executed",
             job_id       = job.job_id,
             backend      = result.backend,
             elapsed_s    = f"{result.execution_time:.2f}",
             result_hash  = result.result_hash[:16])

    # 4. Préparer le memo de résultat (publié on-chain)
    result_summary = {
        "job_id":       job.job_id,
        "backend":      result.backend,
        "shots":        result.shots,
        "counts":       result.counts,       
        "result_hash":  result.result_hash, 
        "circuit_hash": result.circuit_hash,
        "elapsed_s":    round(result.execution_time, 3),
    }

    # 5. EscrowFinish — révèle le fulfillment, libère les XRP vers l'oracle
    fulfillment = JOB_STORE.get_fulfillment(job.job_id)
    if not fulfillment:
        log.error("fulfillment_not_found", job_id=job.job_id)
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

    except Exception as e:
        log.error("escrow_finish_failed", job_id=job.job_id, error=str(e))


# ─── Job Store (à remplacer par Redis/Postgres en production) ─────────────────

class InMemoryJobStore:

    def __init__(self):
        self._store: dict[str, dict] = {}

    def create_quote(self, job_id: str) -> JobCryptoKeys:
        keys = JobCryptoKeys()
        self._store[job_id] = {
            "keys": keys,
            "status": "quoted",
        }
        log.debug("quote_created", job_id=job_id, condition=keys.condition[:32])
        return keys

    def get_fulfillment(self, job_id: str) -> Optional[str]:
        entry = self._store.get(job_id)
        if entry:
            return entry["keys"].fulfillment
        return None

    def get_condition(self, job_id: str) -> Optional[str]:
        entry = self._store.get(job_id)
        if entry:
            return entry["keys"].condition
        return None

    def mark_done(self, job_id: str):
        if job_id in self._store:
            self._store[job_id]["status"] = "done"


JOB_STORE = InMemoryJobStore()


# ─── API Quote (pré-escrow) ───────────────────────────────────────────────────

async def handle_quote_request(job_id: Optional[str] = None) -> dict:

    jid  = job_id or str(uuid.uuid4())[:16]
    keys = JOB_STORE.create_quote(jid)

    return {
        "job_id":    jid,
        "condition": keys.condition,
        "oracle":    config2.ORACLE_ADDRESS,
        "dest_tag":  config2.QUANTUMGRID_TAG,
    }


# ─── Boucle principale ────────────────────────────────────────────────────────

async def run_oracle():

    if not config2.ORACLE_WALLET_SEED:
        log.error("ORACLE_WALLET_SEED manquant dans .env")
        sys.exit(1)

    wallet = Wallet.from_seed(config2.ORACLE_WALLET_SEED)
    log.info("oracle_started",
             address   = wallet.address,
             network   = config2.XRPL_WS_URL,
             simulator = config2.USE_SIMULATOR)

    async with AsyncWebsocketClient(config2.XRPL_WS_URL) as client:
        async with XRPLOracleWatcher(wallet.address, config2.XRPL_WS_URL) as watcher:
            async for job in watcher.escrow_jobs():
                # Traitement concurrent — ne bloque pas la surveillance
                asyncio.create_task(
                    process_job(client, wallet, job)
                )


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        asyncio.run(run_oracle())
    except KeyboardInterrupt:
        log.info("oracle_stopped")
