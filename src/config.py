import xrpl
from xrpl.clients import JsonRpcClient

JSON_RPC_URL = "https://s.altnet.rippletest.net:51234/"
client = JsonRpcClient(JSON_RPC_URL)

if __name__ == "__main__":
    from xrpl.models.requests import ServerInfo
    response = client.request(ServerInfo())
    print("Connexion testnet OK :", response.status)