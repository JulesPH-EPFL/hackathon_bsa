import asyncio
import logging
import time
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.wallet import Wallet
from xrpl_client import EscrowJob, escrow_cancel

log = logging.getLogger(__name__)

ACTIVE_ESCROWS: dict[str, EscrowJob] = {}

def register_escrow(job: EscrowJob):
    if job.cancel_after:
        ACTIVE_ESCROWS[job.job_id] = job
        log.debug(f"Escrow enregistré pour surveillance : {job.job_id}")

def unregister_escrow(job_id: str):
    ACTIVE_ESCROWS.pop(job_id, None)

async def monitor_escrows(
    client:   AsyncWebsocketClient,
    wallet:   Wallet,
    interval: int = 30,
):

    log.info(f"Escrow monitor démarré — vérification toutes les {interval}s")

    while True:
        await asyncio.sleep(interval)

        try:
            xrpl_now = int(time.time()) - 946684800
            expired  = [
                job for job in ACTIVE_ESCROWS.values()
                if job.cancel_after and job.cancel_after < xrpl_now
            ]

            if expired:
                log.info(f"{len(expired)} escrow(s) expiré(s) à annuler")

            for job in expired:
                log.warning(f"Escrow expiré: {job.job_id} — annulation...")
                try:
                    await escrow_cancel(
                        client = client,
                        wallet = wallet,
                        job    = job,
                        reason = "ttl_expired",
                    )
                    unregister_escrow(job.job_id)
                    log.info(f"Escrow {job.job_id} annulé — XRP retournés à {job.owner[:12]}...")
                except Exception as e:
                    log.error(f"Erreur annulation {job.job_id}: {e}")

        except Exception as e:
            log.error(f"Erreur monitor: {e}")