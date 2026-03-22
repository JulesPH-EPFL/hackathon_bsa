"""
TelescopeGrid — Démo interactive complète

Le chercheur contrôle le télescope avec les flèches,
fait 3 captures, les images sont livrées, et l'oracle
libère automatiquement le paiement au CERN.

Usage :
  python3 telescope_demo.py
"""

import asyncio
import curses
import hashlib
import json
import time
import uuid
from functools import partial

from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.wallet import Wallet
from xrpl.models.requests import AccountTx

import config
from crypto_condition import JobCryptoKeys
from xrpl_client import client_create_escrow, escrow_finish, EscrowJob, pay_provider
from src.wallets import add_wallet, get_wallet
from src.nft import mint_slot, create_sell_offer, buy_slot

COMMISSION = 0.10

# ─── Carte du ciel (objets célèbres) ─────────────────────────────────────────

SKY_OBJECTS = [
    {"name": "Nébuleuse d'Orion",    "ra": 83.82,  "dec": -5.39,  "sym": "*"},
    {"name": "Galaxie d'Andromède",  "ra": 10.68,  "dec": 41.27,  "sym": "G"},
    {"name": "Amas des Pléiades",    "ra": 56.87,  "dec": 24.12,  "sym": "."},
    {"name": "Nébuleuse du Crabe",   "ra": 83.63,  "dec": 22.01,  "sym": "+"},
    {"name": "Alpha Centauri",       "ra": 219.90, "dec": -60.83, "sym": "o"},
    {"name": "Sirius",               "ra": 101.29, "dec": -16.72, "sym": "*"},
    {"name": "Nébuleuse de la Lyre", "ra": 283.40, "dec": 33.02,  "sym": "O"},
    {"name": "Betelgeuse",           "ra": 88.79,  "dec": 7.41,   "sym": "*"},
    {"name": "Galaxie du Tourbillon","ra": 202.47, "dec": 47.20,  "sym": "G"},
    {"name": "Cluster Hercule",      "ra": 250.42, "dec": 36.46,  "sym": "."},
]

# ─── Contrôleur terminal ──────────────────────────────────────────────────────

class TelescopeController:
    def __init__(self, stdscr):
        self.stdscr   = stdscr
        self.ra       = 120.0   # position courante en degrés
        self.dec      = 0.0
        self.captures = []      # liste des captures effectuées
        self.step     = 2.0     # degrés par pression de touche
        self.done     = False

    def ra_to_hms(self, ra):
        ra = ra % 360
        h  = int(ra / 15)
        m  = int((ra / 15 - h) * 60)
        s  = int(((ra / 15 - h) * 60 - m) * 60)
        return f"{h:02d}h {m:02d}m {s:02d}s"

    def dec_to_dms(self, dec):
        dec  = max(-90, min(90, dec))
        sign = "+" if dec >= 0 else "-"
        d    = int(abs(dec))
        m    = int((abs(dec) - d) * 60)
        return f"{sign}{d:02d}° {m:02d}'"

    def nearest_object(self):
        best, best_d = None, 999
        for obj in SKY_OBJECTS:
            d = ((obj["ra"] - self.ra) ** 2 + (obj["dec"] - self.dec) ** 2) ** 0.5
            if d < best_d:
                best_d, best = d, obj
        return best, best_d

    def draw(self):
        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()

        # ── En-tête ──────────────────────────────────────────────────────────
        title = "  TelescopeGrid — Contrôle CERN-T1  "
        self.stdscr.addstr(0, 0, "─" * w)
        self.stdscr.addstr(1, max(0, (w - len(title)) // 2), title)
        self.stdscr.addstr(2, 0, "─" * w)

        # ── Carte du ciel (40x16) ─────────────────────────────────────────
        sky_w, sky_h = 60, 16
        sky_x, sky_y = 2, 4

        # Fond du ciel
        for row in range(sky_h):
            self.stdscr.addstr(sky_y + row, sky_x, " " * sky_w)

        # Étoiles de fond (fixes)
        bg_stars = [(3,2),(8,5),(15,1),(22,8),(30,3),(38,12),(45,6),(52,10),
                    (5,13),(12,9),(28,14),(40,2),(55,7),(18,11),(33,4)]
        for bx, by in bg_stars:
            if by < sky_h and bx < sky_w:
                self.stdscr.addstr(sky_y + by, sky_x + bx, "·")

        # Objets célèbres
        for obj in SKY_OBJECTS:
            ox = int((obj["ra"] / 360) * sky_w)
            oy = int((90 - obj["dec"]) / 180 * sky_h)
            if 0 <= oy < sky_h and 0 <= ox < sky_w:
                self.stdscr.addstr(sky_y + oy, sky_x + ox, obj["sym"])

        # Captures déjà effectuées
        for cap in self.captures:
            cx = int((cap["ra"] / 360) * sky_w)
            cy = int((90 - cap["dec"]) / 180 * sky_h)
            if 0 <= cy < sky_h and 0 <= cx < sky_w:
                self.stdscr.addstr(sky_y + cy, sky_x + cx, "X")

        # Réticule du télescope
        tx = int((self.ra / 360) * sky_w)
        ty = int((90 - self.dec) / 180 * sky_h)
        tx = max(1, min(sky_w - 1, tx))
        ty = max(1, min(sky_h - 2, ty))

        if 0 < ty < sky_h - 1:
            self.stdscr.addstr(sky_y + ty - 1, sky_x + tx, "|")
            self.stdscr.addstr(sky_y + ty + 1, sky_x + tx, "|")
        if 0 < tx < sky_w - 1:
            self.stdscr.addstr(sky_y + ty, sky_x + tx - 1, "—")
            self.stdscr.addstr(sky_y + ty, sky_x + tx + 1, "—")
        self.stdscr.addstr(sky_y + ty, sky_x + tx, "+")

        # Bordure du ciel
        self.stdscr.addstr(sky_y - 1, sky_x - 1, "┌" + "─" * sky_w + "┐")
        for row in range(sky_h):
            self.stdscr.addstr(sky_y + row, sky_x - 1, "│")
            self.stdscr.addstr(sky_y + row, sky_x + sky_w, "│")
        self.stdscr.addstr(sky_y + sky_h, sky_x - 1, "└" + "─" * sky_w + "┘")

        # ── Coordonnées ───────────────────────────────────────────────────
        info_x = sky_x + sky_w + 4
        self.stdscr.addstr(4,  info_x, "Coordonnées :")
        self.stdscr.addstr(5,  info_x, f"RA  : {self.ra_to_hms(self.ra)}")
        self.stdscr.addstr(6,  info_x, f"Dec : {self.dec_to_dms(self.dec)}")

        # Objet le plus proche
        obj, dist = self.nearest_object()
        if dist < 15:
            self.stdscr.addstr(8,  info_x, f"Cible : {obj['name']}")
        else:
            self.stdscr.addstr(8,  info_x, "Cible : espace vide")

        self.stdscr.addstr(10, info_x, f"Captures : {len(self.captures)}/3")

        for i, cap in enumerate(self.captures):
            self.stdscr.addstr(11 + i, info_x, f"  [{i+1}] {cap['name'][:18]}")

        # ── Contrôles ─────────────────────────────────────────────────────
        ctrl_y = sky_y + sky_h + 2
        self.stdscr.addstr(ctrl_y,     2, "Flèches : pointer   |   Espace : capturer   |   Q : quitter")
        if len(self.captures) >= 3:
            self.stdscr.addstr(ctrl_y + 1, 2, ">>> 3 captures effectuées — appuyez sur ENTRÉE pour envoyer et payer <<<")

        self.stdscr.refresh()

    def run(self):
        curses.curs_set(0)
        self.stdscr.timeout(50)

        while not self.done:
            self.draw()
            key = self.stdscr.getch()

            if key == curses.KEY_LEFT:
                self.ra  = (self.ra - self.step) % 360
            elif key == curses.KEY_RIGHT:
                self.ra  = (self.ra + self.step) % 360
            elif key == curses.KEY_UP:
                self.dec = min(90, self.dec + self.step)
            elif key == curses.KEY_DOWN:
                self.dec = max(-90, self.dec - self.step)
            elif key == ord(' ') and len(self.captures) < 3:
                self.do_capture()
            elif key in (ord('\n'), ord('\r')) and len(self.captures) >= 3:
                self.done = True
            elif key in (ord('q'), ord('Q')):
                self.captures = []
                self.done = True

        return self.captures

    def do_capture(self):
        obj, dist = self.nearest_object()
        name = obj["name"] if dist < 15 else f"RA={self.ra:.1f} Dec={self.dec:.1f}"
        cap = {
            "id":      str(uuid.uuid4())[:8],
            "ra":      round(self.ra, 4),
            "dec":     round(self.dec, 4),
            "name":    name,
            "filters": ["R", "G", "B"],
            "url":     f"https://telescope.cern.ch/{str(uuid.uuid4())[:8]}.fits",
            "hash":    hashlib.sha256(f"{self.ra}{self.dec}{time.time()}".encode()).hexdigest()[:16],
            "ts":      time.time(),
        }
        self.captures.append(cap)


def run_controller():
    """Lance le contrôleur en mode curses et retourne les captures."""
    return curses.wrapper(lambda s: TelescopeController(s).run())


# ─── Paiement XRPL ────────────────────────────────────────────────────────────

async def process_payment(captures, provider_id, researcher_id):
    print("\n" + "═" * 54)
    print("  TelescopeGrid — Traitement des observations")
    print("═" * 54)

    researcher_wallet = get_wallet(researcher_id)
    oracle_wallet     = Wallet.from_seed(config.ORACLE_WALLET_SEED)

    print(f"\n  Chercheur : {researcher_wallet.address}")
    print(f"  Oracle    : {oracle_wallet.address}")

    # Préparer le résumé des observations
    obs_summary = {
        "captures":    captures,
        "total":       len(captures),
        "obs_hash":    hashlib.sha256(json.dumps(captures, sort_keys=True).encode()).hexdigest(),
    }

    print(f"\n  {len(captures)} observations à livrer :")
    for i, cap in enumerate(captures):
        print(f"    [{i+1}] {cap['name']:25s}  RA={cap['ra']:.2f}  Dec={cap['dec']:.2f}")

    print("\n  Génération de la condition cryptographique...")
    job_id = str(uuid.uuid4())[:16]
    keys   = JobCryptoKeys()

    async with AsyncWebsocketClient(config.XRPL_WS_URL) as client:

        print(f"  Création de l'escrow (1 XRP)...")
        escrow_response = await client_create_escrow(
            client         = client,
            client_wallet  = researcher_wallet,
            oracle_address = oracle_wallet.address,
            condition      = keys.condition,
            xrp_amount     = 1.0,
            qasm           = json.dumps(obs_summary, separators=(",", ":")),
            shots          = len(captures),
            job_id         = job_id,
            ttl_seconds    = 300,
        )
        escrow_tx = escrow_response.result
        tx_result = escrow_tx.get("meta", {}).get("TransactionResult")
        print(f"  EscrowCreate → {tx_result}")
        if tx_result != "tesSUCCESS":
            print(f"  Escrow échoué : {tx_result}")
            return

        # Récupérer le sequence
        sequence = (
            escrow_tx.get("Sequence") or
            escrow_tx.get("tx_json", {}).get("Sequence")
        )
        if not sequence:
            resp = await client.request(AccountTx(account=researcher_wallet.address, limit=5))
            for tx_entry in resp.result.get("transactions", []):
                tx_inner = tx_entry.get("tx", tx_entry.get("tx_json", {}))
                if tx_inner.get("TransactionType") == "EscrowCreate":
                    sequence = tx_inner.get("Sequence")
                    break

        job = EscrowJob(
            tx_hash      = escrow_tx.get("hash", ""),
            sequence     = sequence,
            owner        = researcher_wallet.address,
            destination  = oracle_wallet.address,
            amount_drops = str(1_000_000),
            condition    = keys.condition,
            cancel_after = None,
            qasm         = json.dumps(obs_summary),
            shots        = len(captures),
            job_id       = job_id,
        )

        # Simuler la livraison des images
        print(f"\n  Télescope en train de photographier...")
        for i, cap in enumerate(captures):
            time.sleep(0.5)
            print(f"    [{i+1}] {cap['name']:25s} → {cap['url']}")

        # Vérification
        print(f"\n  Oracle vérifie les {len(captures)} images livrées...")
        for cap in captures:
            if not cap.get("hash"):
                print(f"  ✗ Image manquante : {cap['name']}")
                return
        print(f"  ✓ Toutes les images vérifiées")

        # EscrowFinish
        print(f"\n  Oracle libère le paiement (EscrowFinish)...")
        result_memo = {
            "job_id":   job_id,
            "captures": len(captures),
            "obs_hash": obs_summary["obs_hash"],
            "images":   [c["url"] for c in captures],
        }
        finish = await escrow_finish(
            client      = client,
            wallet      = oracle_wallet,
            job         = job,
            fulfillment = keys.fulfillment,
            result_memo = result_memo,
        )
        finish_result = finish.result.get("meta", {}).get("TransactionResult")
        print(f"  EscrowFinish → {finish_result}")

        # Paiement CERN
        print(f"\n  Oracle reverse 90% au CERN...")
        provider_wallet = get_wallet(provider_id)
        await pay_provider(
            client           = client,
            oracle_wallet    = oracle_wallet,
            provider_address = provider_wallet.address,
            total_drops      = 1_000_000,
            commission_pct   = COMMISSION,
        )
        print(f"  0.90 XRP → CERN  ({provider_wallet.address[:20]}...)")
        print(f"  0.10 XRP → Oracle (commission)")

        # NFT résultat
        print(f"\n  Mint NFT de preuve on-chain...")
        loop = asyncio.get_event_loop()
        nft = await loop.run_in_executor(
            None,
            partial(mint_slot, provider_id, {
                "taxon": 2, "transfer_fee": 0,
                "uri": f"telescopegrid://result/{job_id}/{obs_summary['obs_hash'][:12]}",
            })
        )
        print(f"  NFT résultat : {nft[:24]}...")

    print("\n" + "═" * 54)
    print("  ✓ Mission accomplie !")
    print(f"  {len(captures)} images livrées à {researcher_wallet.address[:16]}...")
    print(f"  CERN payé — Oracle commissionné")
    print(f"  Preuve on-chain : https://testnet.xrpl.org/accounts/{oracle_wallet.address}")
    print("═" * 54 + "\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Chargement des wallets...")
    _, provider_id   = add_wallet("CERN",   "fournisseur")
    _, researcher_id = add_wallet("Arnaud", "chercheur")
    print(f"CERN   : {get_wallet(provider_id).address}")
    print(f"Arnaud : {get_wallet(researcher_id).address}")
    print("\nLancement du contrôleur de télescope...")
    print("(Flèches = pointer  |  Espace = capturer  |  Entrée = envoyer  |  Q = quitter)\n")
    input("Appuyez sur ENTRÉE pour démarrer...")

    captures = run_controller()

    if not captures:
        print("Aucune capture — démo annulée.")
    else:
        print(f"\n{len(captures)} captures effectuées. Traitement du paiement...")
        asyncio.run(process_payment(captures, provider_id, researcher_id))
