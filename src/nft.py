from xrpl.models.transactions import Payment
from xrpl.utils import xrp_to_drops
from xrpl.transaction import submit_and_wait
from xrpl.models.transactions.nftoken_mint import NFTokenMintFlag, NFTokenMint
from xrpl.models.transactions import NFTokenCreateOffer, NFTokenAcceptOffer
from xrpl.models.transactions.nftoken_create_offer import NFTokenCreateOfferFlag
from xrpl.models.requests import AccountNFTs
from xrpl.utils import str_to_hex, hex_to_str
from src.config import client
from src.wallets import get_wallet

def buy_and_certify(
    buyer_seed: str,
    observatory_address: str,
    units: int,
    currency: str,
    date: str,
    price_xrp_per_unit: float,
    observatory_id: str
) -> dict:
    buyer_wallet = get_wallet(buyer_seed)
    total_xrp = units * price_xrp_per_unit

    payment_tx = Payment(
        account=buyer_wallet.address,
        destination=observatory_address,
        amount=xrp_to_drops(total_xrp)
    )
    payment_response = submit_and_wait(payment_tx, client, buyer_wallet)
    tx_hash = payment_response.result["hash"]

    uri = f"observatory={observatory_id}&units={units}{currency}&price={price_xrp_per_unit}&total_xrp={total_xrp}&date={date}&tx_hash={tx_hash}"
    
    mint_tx = NFTokenMint(
        account=buyer_wallet.address,
        nftoken_taxon=1,
        transfer_fee=0,
        uri=str_to_hex(uri),
        flags=NFTokenMintFlag.TF_TRANSFERABLE
    )
    mint_response = submit_and_wait(mint_tx, client, buyer_wallet)
    nftoken_id = mint_response.result["meta"]["nftoken_id"]

    return {
        "tx_hash": tx_hash,
        "nftoken_id": nftoken_id,
        "units": units,
        "total_xrp": total_xrp,
        "observatory": observatory_id
    }
    
def get_nfts(address: str) -> list:
    response = client.request(AccountNFTs(account=address))
    nfts = response.result.get("account_nfts", [])
    for nft in nfts:
        if "URI" in nft:
            nft["URI"] = hex_to_str(nft["URI"])
    return nfts

def mint_slot(seed: str, metadata: dict) -> str:
    wallet = get_wallet(seed)
    mint_tx = NFTokenMint(
        account=wallet.address,
        nftoken_taxon=metadata["taxon"],
        transfer_fee=metadata["transfer_fee"],
        uri=str_to_hex(metadata["uri"]),
        flags=NFTokenMintFlag.TF_TRANSFERABLE
    )
    response = submit_and_wait(mint_tx, client, wallet)
    return response.result["meta"]["nftoken_id"]

def create_sell_offer(seed: str, nftoken_id: str, price_xrp: float) -> str:
    wallet = get_wallet(seed)
    from xrpl.utils import xrp_to_drops
    tx = NFTokenCreateOffer(
        account=wallet.address,
        nftoken_id=nftoken_id,
        amount=str(int(xrp_to_drops(price_xrp))) if price_xrp > 0 else "0",
        flags=NFTokenCreateOfferFlag.TF_SELL_NFTOKEN
    )
    response = submit_and_wait(tx, client, wallet)
    return response.result["meta"]["offer_id"]

def buy_slot(seed: str, offer_id: str) -> str:
    wallet = get_wallet(seed)
    tx = NFTokenAcceptOffer(
        account=wallet.address,
        nftoken_sell_offer=offer_id
    )
    response = submit_and_wait(tx, client, wallet)
    return response.result["meta"]["nftoken_id"]