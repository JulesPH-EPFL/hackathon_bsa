from xrpl.models.transactions import TrustSet, Payment
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import AccountLines
from xrpl.transaction import submit_and_wait
from xrpl.utils import xrp_to_drops
from src.config import client
from src.wallets import get_wallet
from src.nft import mint_slot, create_sell_offer, buy_slot

def create_trustline(buyer_id: str, issuer_address: str, currency: str, limit: int) -> str:
    wallet = get_wallet(buyer_id)
    tx = TrustSet(
        account=wallet.address,
        limit_amount=IssuedCurrencyAmount(
            currency=currency,
            issuer=issuer_address,
            value=str(limit)
        )
    )
    response = submit_and_wait(tx, client, wallet)
    return response.result["meta"]["TransactionResult"]

def send_minutes(observatory_id: str, buyer_address: str, currency: str, minutes: int) -> str:
    wallet = get_wallet(observatory_id)
    tx = Payment(
        account=wallet.address,
        destination=buyer_address,
        amount=IssuedCurrencyAmount(
            currency=currency,
            issuer=wallet.address,
            value=str(minutes)
        )
    )
    response = submit_and_wait(tx, client, wallet)
    return response.result["meta"]["TransactionResult"]

def buy_minutes(buyer_id: str, observatory_id: str, currency: str, minutes: int, price_xrp_per_minute: float, lim: int) -> dict:
    buyer_wallet = get_wallet(buyer_id)
    observatory_wallet = get_wallet(observatory_id)
    
    create_trustline(buyer_id,observatory_wallet.address,currency,lim)
    
    total_xrp = minutes * price_xrp_per_minute
    payment_tx = Payment(
        account=buyer_wallet.address,
        destination=observatory_wallet.address,
        amount=xrp_to_drops(total_xrp)
    )
    submit_and_wait(payment_tx, client, buyer_wallet)
    
    send_minutes(observatory_id, buyer_wallet.address, currency, minutes)
    
    return {
        "buyer": buyer_wallet.address,
        "minutes": minutes,
        "currency": currency,
        "total_xrp": total_xrp
    }
    
def redeem_minutes(buyer_id: str, observatory_id: str, currency: str, minutes: int) -> str:
    buyer_wallet = get_wallet(buyer_id)
    observatory_wallet = get_wallet(observatory_id)
    
    tx = Payment(
        account=buyer_wallet.address,
        destination=observatory_wallet.address,
        amount=IssuedCurrencyAmount(
            currency=currency,
            issuer=observatory_wallet.address,
            value=str(minutes)
            )
    )
    submit_and_wait(tx, client, buyer_wallet)
    
    metadata = {
        "taxon": 1,
        "transfer_fee": 0,
        "uri": f"{observatory_id}: {minutes} {currency} to: {buyer_id}"
    }
    
    nftoken_id = mint_slot(observatory_id, metadata)
    
    offer_id = create_sell_offer(observatory_id, nftoken_id, 0)
    
    buy_slot(buyer_id, offer_id)
    return nftoken_id

def get_minutes_balance(address: str, currency: str, issuer_address: str) -> float:
    response = client.request(AccountLines(account=address))
    for line in response.result.get("lines", []):
        if line["currency"] == currency and line["account"] == issuer_address:
            return float(line["balance"])
    return 0.0