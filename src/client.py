"""
QuantumGrid — Launcher

Usage :
  python3 client.py quantum    --seed sXXX --provider rYYY --amount 1.0
  python3 client.py telescope  --seed sXXX --provider rYYY --amount 1.0
"""

import argparse
import asyncio
from src.bridge import run_demo
from src.bridge_tele import run_telescope_demo

def main():
    parser = argparse.ArgumentParser(description="QuantumGrid client")
    parser.add_argument("service",   choices=["quantum", "telescope"])
    parser.add_argument("--seed",     required=True,  help="Seed du chercheur")
    parser.add_argument("--provider", required=True,  help="Adresse du fournisseur")
    parser.add_argument("--amount",   type=float, default=1.0)
    args = parser.parse_args()

    print(f"\nService     : {args.service}")
    print(f"Fournisseur : {args.provider}")
    print(f"Montant     : {args.amount} XRP")

    if args.service == "quantum":
        asyncio.run(run_demo(
            provider_address = args.provider,
            researcher_seed  = args.seed,
            amount_xrp       = args.amount,
        ))
    elif args.service == "telescope":
        asyncio.run(run_telescope_demo(
            provider_address = args.provider,
            researcher_seed  = args.seed,
            amount_xrp       = args.amount,
        ))

if __name__ == "__main__":
    main()