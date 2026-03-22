from src.nft import mint_slot, create_sell_offer, get_sell_offers, buy_slot, get_nfts
from src.wallets import add_wallet, get_wallet

result_j, j_id = add_wallet('Arnaud','chercheur')
result_c, c_id = add_wallet('CERN','observatoire')
result_e, e_id = add_wallet('eliott','amateur')

metadata = {
    "taxon": 1,
    "transfer_fee": 5,
    "uri": "observation_cern_5h"
}

nftoken_id = mint_slot(c_id, metadata)
print("NFT minté :", nftoken_id)

offer_id = create_sell_offer(c_id, nftoken_id, 5.0)
print("Offre créée :", offer_id)

buy_id = buy_slot(j_id, offer_id)
print("Créneau acheté :", buy_id)

nfts = get_nfts(result_j["address"])
print("NFTs de Arnaud :", nfts)