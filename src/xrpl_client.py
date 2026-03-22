import asyncio
import json
import logging
import time
from typing import AsyncIterator, Optional

import xrpl
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models.transactions import (
    EscrowCreate,
    EscrowFinish,
    EscrowCancel,
    Payment
)
try:
    from xrpl.models.transactions.transaction import Memo, MemoWrapper
except ImportError:
    from xrpl.models.transactions import Memo
    MemoWrapper = None
from xrpl.models.requests import Subscribe, AccountTx, Ledger
from xrpl.wallet import Wallet
from xrpl.utils import xrp_to_drops, drops_to_xrp
from xrpl.asyncio.transaction import submit_and_wait
from xrpl.models.response import Response

import src.config2 as config2

logger = logging.getLogger(__name__)

# ─── Memo helpers ─────────────────────────────────────────────────────────────

def hex_encode(s: str) -> str:
    return s.encode("utf-8").hex().upper()


def hex_decode(h: str) -> str:
    return bytes.fromhex(h).decode("utf-8", errors="replace")


def build_memo(memo_type: str, memo_data: str):
    """Construit un memo XRPL typé (xrpl-py attend des objets Memo, pas des dicts)."""
    memo = Memo(
        memo_type=hex_encode(memo_type),
        memo_data=hex_encode(memo_data),
    )
    if MemoWrapper is not None:
        return MemoWrapper(memo=memo)
    return memo


def parse_memos(tx: dict) -> dict[str, str]:
    """Extrait tous les memos d'une transaction en dict {type: data}."""
    result = {}
    for memo_wrapper in tx.get("Memos", []):
        memo = memo_wrapper.get("Memo", {})
        try:
            mtype = hex_decode(memo.get("MemoType", ""))
            mdata = hex_decode(memo.get("MemoData", ""))
            result[mtype] = mdata
        except Exception:
            pass
    return result


# ─── Structures de données ────────────────────────────────────────────────────

from dataclasses import dataclass, field


@dataclass
class EscrowJob:
    """Représente un escrow QuantumGrid détecté on-chain."""
    tx_hash:       str
    sequence:      int          # sequence du EscrowCreate (nécessaire pour EscrowFinish)
    owner:         str          # adresse du client (créateur de l'escrow)
    destination:   str          # adresse de l'oracle
    amount_drops:  str
    condition:     str          # hex condition fournie par le client
    cancel_after:  Optional[int]  # timestamp ripple epoch
    # Champs extraits des memos
    qasm:          str  = ""
    shots:         int  = 1024
    job_id:        str  = ""
    client_pubkey: str  = ""    # pour retourner les résultats chiffrés (optionnel)


# ─── Surveillance des EscrowCreate ───────────────────────────────────────────

class XRPLOracleWatcher:
    """
    Se connecte au ledger via WebSocket et émet les EscrowCreate
    destinés à l'oracle (filtrés par destination + DestinationTag).
    """

    def __init__(self, oracle_address: str, ws_url: str = config2.XRPL_WS_URL):
        self.oracle_address = oracle_address
        self.ws_url         = ws_url
        self._client: Optional[AsyncWebsocketClient] = None

    async def __aenter__(self):
        self._client = AsyncWebsocketClient(self.ws_url)
        await self._client.__aenter__()
        # S'abonner au compte oracle
        await self._client.send(Subscribe(accounts=[self.oracle_address]))
        logger.info(f"Connecté à {self.ws_url} — surveillance de {self.oracle_address}")
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.__aexit__(*args)

    async def escrow_jobs(self) -> AsyncIterator[EscrowJob]:
        """Générateur asynchrone des nouveaux EscrowCreate."""
        async for message in self._client:
            try:
                job = self._parse_message(message)
                if job:
                    yield job
            except Exception as e:
                logger.warning(f"Erreur parsing message : {e}")

    def _parse_message(self, message) -> Optional[EscrowJob]:
        if not isinstance(message, dict):
            return None

        # Les messages de type 'transaction' arrivent dans message["transaction"]
        tx_envelope = message.get("transaction") or message.get("tx_json")
        if not tx_envelope:
            return None

        tx = tx_envelope if "TransactionType" in tx_envelope else message

        # Filtre : EscrowCreate destiné à notre oracle
        if tx.get("TransactionType") != "EscrowCreate":
            return None
        if tx.get("Destination") != self.oracle_address:
            return None

        # Filtre sur le DestinationTag QuantumGrid
        dest_tag = tx.get("DestinationTag")
        if dest_tag != config2.QUANTUMGRID_TAG:
            logger.debug(f"EscrowCreate ignoré — DestinationTag={dest_tag}")
            return None

        # Montant minimum
        amount_drops = str(tx.get("Amount", "0"))
        if int(amount_drops) < config2.MIN_ESCROW_DROPS:
            logger.warning(
                f"Escrow trop petit : {drops_to_xrp(amount_drops)} XRP < minimum"
            )
            return None

        condition = tx.get("Condition", "")
        if not condition:
            logger.warning("EscrowCreate sans Condition — ignoré")
            return None

        memos = parse_memos(tx)

        # Le QASM du circuit est encodé dans le memo "qasm"
        qasm = memos.get("qasm", "")
        if not qasm:
            logger.warning(f"EscrowCreate sans memo 'qasm' — ignoré")
            return None

        shots  = int(memos.get("shots", "1024"))
        job_id = memos.get("job_id", tx.get("hash", "")[:16])

        return EscrowJob(
            tx_hash      = tx.get("hash", ""),
            sequence     = tx.get("Sequence", 0),
            owner        = tx.get("Account", ""),
            destination  = self.oracle_address,
            amount_drops = amount_drops,
            condition    = condition,
            cancel_after = tx.get("CancelAfter"),
            qasm         = qasm,
            shots        = shots,
            job_id       = job_id,
        )


# ─── Opérations de transaction ───────────────────────────────────────────────

async def escrow_finish(
    client: AsyncWebsocketClient,
    wallet: Wallet,
    job: EscrowJob,
    fulfillment: str,
    result_memo: dict,
) -> Response:
    """
    Soumet un EscrowFinish pour libérer les fonds vers l'oracle.

    Args:
        fulfillment : hex du preimage ASN.1 (révélé après livraison)
        result_memo : dict JSON avec les résultats quantiques (ajouté en memo)
    """
    tx = EscrowFinish(
        account      = wallet.address,
        owner        = job.owner,
        offer_sequence = job.sequence,
        condition    = job.condition,
        fulfillment  = fulfillment,
        memos        = [build_memo("result", json.dumps(result_memo, separators=(",", ":")))],
    )
    logger.info(f"[{job.job_id}] Soumission EscrowFinish...")
    response = await submit_and_wait(tx, client, wallet)
    logger.info(f"[{job.job_id}] EscrowFinish — {response.result.get('meta', {}).get('TransactionResult')}")
    return response


async def escrow_cancel(
    client: AsyncWebsocketClient,
    wallet: Wallet,
    job: EscrowJob,
    reason: str = "job_failed",
) -> Response:
    """
    Annule un escrow (si le job a échoué ou expiré).
    Seul l'owner peut annuler après CancelAfter.
    """
    tx = EscrowCancel(
        account        = wallet.address,
        owner          = job.owner,
        offer_sequence = job.sequence,
        memos          = [build_memo("cancel_reason", reason)],
    )
    logger.info(f"[{job.job_id}] Soumission EscrowCancel — raison: {reason}")
    response = await submit_and_wait(tx, client, wallet)
    logger.info(f"[{job.job_id}] EscrowCancel — {response.result.get('meta', {}).get('TransactionResult')}")
    return response


# ─── Helper côté client (pour les tests / SDK) ───────────────────────────────

async def client_create_escrow(
    client: AsyncWebsocketClient,
    client_wallet: Wallet,
    oracle_address: str,
    condition: str,        # hex — généré par l'oracle au moment du quote
    xrp_amount: float,
    qasm: str,
    shots: int,
    job_id: str,
    ttl_seconds: int = 300,
) -> Response:
    """
    Crée un EscrowCreate côté client.
    Utilisé dans les tests ou dans le SDK QuantumGrid client.
    """
    # CancelAfter = epoch XRPL = Unix - 946684800
    xrpl_epoch_offset = 946684800
    cancel_after = int(time.time()) - xrpl_epoch_offset + ttl_seconds

    # Récupérer le ledger courant pour fixer LastLedgerSequence manuellement
    # xrpl-py met une fenêtre de ~4 ledgers par défaut (~16s), trop court sur testnet.
    # On passe lastLedgerSequence=None pour que submit_and_wait le gère avec sa
    # propre logique, ou on utilise un autofill avec une fenêtre plus large.
    # Fenêtre large pour le testnet qui peut être lent
    ledger_resp = await client.request(Ledger(ledger_index="validated"))
    current_ledger = ledger_resp.result["ledger_index"]

    tx = EscrowCreate(
        account              = client_wallet.address,
        amount               = xrp_to_drops(xrp_amount),
        destination          = oracle_address,
        destination_tag      = config2.QUANTUMGRID_TAG,
        condition            = condition,
        cancel_after         = cancel_after,
        last_ledger_sequence = current_ledger + 20,
        memos                = [
            build_memo("qasm",   qasm),
            build_memo("shots",  str(shots)),
            build_memo("job_id", job_id),
        ],
    )
    return await submit_and_wait(tx, client, client_wallet)

async def pay_provider(
    client: AsyncWebsocketClient,
    oracle_wallet: Wallet,
    provider_address: str,
    total_drops: int,
    commission_pct: float,
    job_id: str,
) -> Response:
    commission    = int(total_drops * commission_pct)
    provider_cut  = total_drops - commission
    tx = Payment(
        account     = oracle_wallet.address,
        destination = provider_address,
        amount      = str(provider_cut),
        memos       = [build_memo("job_id", job_id)],
    )
    logger.info(f"[{job_id}] Paiement fournisseur {provider_cut} drops → {provider_address}")
    response = await submit_and_wait(tx, client, oracle_wallet)
    logger.info(f"[{job_id}] Payment → {response.result.get('meta', {}).get('TransactionResult')}")
    return response