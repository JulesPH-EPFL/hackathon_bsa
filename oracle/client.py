import argparse
import asyncio
import importlib

def main():
    parser = argparse.ArgumentParser(description="OpenGate client")
    parser.add_argument("service",   choices=["quantum", "telescope"])
    parser.add_argument("--client",  required=True,  help="Adresse wallet chercheur")
    parser.add_argument("--provider",required=True,  help="Adresse wallet fournisseur")
    parser.add_argument("--amount",  type=float, default=1.0, help="Montant en XRP")
    args = parser.parse_args()

    print(f"\nService    : {args.service}")
    print(f"Client     : {args.client}")
    print(f"Fournisseur: {args.provider}")
    print(f"Montant    : {args.amount} XRP")

    if args.service == "quantum":
        bridge = importlib.import_module("bridge")
        asyncio.run(bridge.run_client(
            provider_address   = args.provider,
            researcher_address = args.client,
            amount_xrp         = args.amount,
        ))
    elif args.service == "telescope":
        bridge = importlib.import_module("bridge_tele")
        asyncio.run(bridge.run_telescope_client(
            provider_address   = args.provider,
            researcher_address = args.client,
            amount_xrp         = args.amount,
        ))

if __name__ == "__main__":
    main()