import xrpl
from xrpl.models.transactions import NFTokenMint
from xrpl.models.transactions.nftoken_mint import NFTokenMintFlag
from xrpl.models.transactions import NFTokenCreateOffer
from xrpl.models.transactions.nftoken_create_offer import NFTokenCreateOfferFlag
from xrpl.models.transactions import NFTokenAcceptOffer
from xrpl.utils import xrp_to_drops
from xrpl.transaction import submit_and_wait
from xrpl.utils import str_to_hex
from src.config import client
from src.wallets import get_wallet

def mint_slot(id: str, metadata: dict) -> str:
    wallet = get_wallet(id)
    mint_tx = NFTokenMint(
        account=wallet.address,
        nftoken_taxon=metadata["taxon"],
        transfer_fee=metadata["transfer_fee"],
        uri=str_to_hex(metadata["uri"]),
        flags=NFTokenMintFlag.TF_TRANSFERABLE
    )
    reply=""
    try:
        response=submit_and_wait(mint_tx,client,wallet)
        reply=response.result["meta"]["nftoken_id"]
    except xrpl.transaction.XRPLReliableSubmissionException as e:
        reply=f"Submit failed: {e}"
    return reply

def create_sell_offer(id: str, nftoken_id: str, price_xrp: float) -> str:
    wallet = get_wallet(id)
    tx = NFTokenCreateOffer(
        account=wallet.address,      
        nftoken_id=nftoken_id,        
        amount=xrp_to_drops(price_xrp), 
        flags=NFTokenCreateOfferFlag.TF_SELL_NFTOKEN  
    )
    response = submit_and_wait(tx, client, wallet)
    return response.result["meta"]["offer_id"]

def buy_slot(buyer_id: str, offer_id: str) -> str:
    wallet = get_wallet(buyer_id)
    tx = NFTokenAcceptOffer(
        account=wallet.address,
        nftoken_sell_offer=offer_id
    )
    response = submit_and_wait(tx, client, wallet)
    return response.result["meta"]["nftoken_id"]