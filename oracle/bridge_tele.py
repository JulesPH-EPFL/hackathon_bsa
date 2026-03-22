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

from src.wallets import add_wallet, get_wallet
from src.nft import mint_slot, create_sell_offer, buy_slot

import config
from crypto_condition import JobCryptoKeys
from xrpl_client import client_create_escrow, escrow_finish, EscrowJob, pay_provider

COMMISSION = 0.10

#  Objets célèbres du ciel 

SKY_OBJECTS = [
    {"name": "Nébuleuse d'Orion",     "ra": 83.82,  "dec": -5.39},
    {"name": "Galaxie d'Andromède",   "ra": 10.68,  "dec": 41.27},
    {"name": "Amas des Pléiades",     "ra": 56.87,  "dec": 24.12},
    {"name": "Nébuleuse du Crabe",    "ra": 83.63,  "dec": 22.01},
    {"name": "Sirius",                "ra": 101.29, "dec": -16.72},
    {"name": "Nébuleuse de la Lyre",  "ra": 283.40, "dec": 33.02},
    {"name": "Betelgeuse",            "ra": 88.79,  "dec": 7.41},
    {"name": "Galaxie du Tourbillon", "ra": 202.47, "dec": 47.20},
    {"name": "Cluster Hercule",       "ra": 250.42, "dec": 36.46},
    {"name": "Alpha Centauri",        "ra": 219.90, "dec": -60.83},
]

# Étoiles de fond fixes (positions relatives 0-1)
BG_STARS = [
    (0.05,0.12),(0.12,0.45),(0.20,0.08),(0.28,0.62),(0.35,0.25),
    (0.42,0.78),(0.50,0.15),(0.58,0.55),(0.65,0.88),(0.72,0.33),
    (0.80,0.70),(0.88,0.18),(0.93,0.50),(0.15,0.82),(0.38,0.42),
    (0.62,0.05),(0.75,0.92),(0.08,0.68),(0.45,0.95),(0.90,0.38),
    (0.25,0.30),(0.55,0.72),(0.70,0.48),(0.32,0.58),(0.82,0.22),
]


#  Contrôleur télescope (curses) 

class TelescopeController:

    SKY_W = 62
    SKY_H = 18

    def __init__(self, stdscr):
        self.stdscr   = stdscr
        self.ra       = 120.0
        self.dec      = 15.0
        self.captures = []
        self.step     = 2.0
        self.done     = False
        self.message  = "Pointez une cible et appuyez sur ESPACE pour capturer (3/3)"

        # Initialiser les couleurs
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN,  -1)  
        curses.init_pair(2, curses.COLOR_YELLOW, -1) 
        curses.init_pair(3, curses.COLOR_CYAN,   -1)  
        curses.init_pair(4, curses.COLOR_WHITE,  -1) 
        curses.init_pair(5, curses.COLOR_RED,    -1)  

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
        return f"{sign}{d:02d}d {m:02d}'"

    def nearest_object(self):
        best, best_d = None, 999
        for obj in SKY_OBJECTS:
            d = ((obj["ra"] - self.ra)**2 + (obj["dec"] - self.dec)**2) ** 0.5
            if d < best_d:
                best_d, best = d, obj
        return best, best_d

    def sky_to_screen(self, ra, dec):
        """Convertit RA/Dec en position écran dans la carte du ciel."""
        x = int((ra / 360) * self.SKY_W)
        y = int((90 - dec) / 180 * self.SKY_H)
        return max(0, min(self.SKY_W - 1, x)), max(0, min(self.SKY_H - 1, y))

    def draw(self):
        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()

        sky_ox = 2   # offset x de la carte
        sky_oy = 4   # offset y de la carte

        # ── Titre ────────────────────────────────────────────────────────────
        title = " CERN-T1  |  TelescopeGrid "
        self.stdscr.addstr(1, 2, title, curses.color_pair(3) | curses.A_BOLD)
        self.stdscr.addstr(2, 2, "─" * (self.SKY_W + 2), curses.color_pair(4))

        # ── Fond étoilé ───────────────────────────────────────────────────────
        for sx, sy in BG_STARS:
            bx = int(sx * self.SKY_W)
            by = int(sy * self.SKY_H)
            try:
                self.stdscr.addstr(sky_oy + by, sky_ox + bx, "·", curses.color_pair(4))
            except curses.error:
                pass

        # ── Objets célèbres ───────────────────────────────────────────────────
        symbols = {"Nébuleuse": "◎", "Galaxie": "⊕", "Amas": "✦",
                   "Cluster": "✦", "Sirius": "★", "Betelgeuse": "★",
                   "Alpha": "★"}
        for obj in SKY_OBJECTS:
            ox, oy = self.sky_to_screen(obj["ra"], obj["dec"])
            sym = "✦"
            for k, v in symbols.items():
                if k in obj["name"]:
                    sym = v
                    break
            try:
                self.stdscr.addstr(sky_oy + oy, sky_ox + ox, sym, curses.color_pair(2))
            except curses.error:
                pass

        # ── Marques des captures ──────────────────────────────────────────────
        for cap in self.captures:
            cx, cy = self.sky_to_screen(cap["ra"], cap["dec"])
            try:
                self.stdscr.addstr(sky_oy + cy, sky_ox + cx, "✓", curses.color_pair(1) | curses.A_BOLD)
            except curses.error:
                pass

        # ── Réticule ──────────────────────────────────────────────────────────
        tx, ty = self.sky_to_screen(self.ra, self.dec)
        try:
            if ty > 0:
                self.stdscr.addstr(sky_oy + ty - 1, sky_ox + tx, "│", curses.color_pair(1))
            if ty < self.SKY_H - 1:
                self.stdscr.addstr(sky_oy + ty + 1, sky_ox + tx, "│", curses.color_pair(1))
            if tx > 0:
                self.stdscr.addstr(sky_oy + ty, sky_ox + tx - 1, "─", curses.color_pair(1))
            if tx < self.SKY_W - 1:
                self.stdscr.addstr(sky_oy + ty, sky_ox + tx + 1, "─", curses.color_pair(1))
            self.stdscr.addstr(sky_oy + ty, sky_ox + tx, "◆", curses.color_pair(1) | curses.A_BOLD)
        except curses.error:
            pass

        # ── Bordure carte ─────────────────────────────────────────────────────
        border_y = sky_oy + self.SKY_H
        try:
            self.stdscr.addstr(sky_oy - 1, sky_ox - 1, "┌" + "─" * self.SKY_W + "┐", curses.color_pair(4))
            for row in range(self.SKY_H):
                self.stdscr.addstr(sky_oy + row, sky_ox - 1, "│", curses.color_pair(4))
                self.stdscr.addstr(sky_oy + row, sky_ox + self.SKY_W, "│", curses.color_pair(4))
            self.stdscr.addstr(border_y, sky_ox - 1, "└" + "─" * self.SKY_W + "┘", curses.color_pair(4))
        except curses.error:
            pass

        # ── Panel droit : infos ───────────────────────────────────────────────
        px = sky_ox + self.SKY_W + 3
        obj, dist = self.nearest_object()

        try:
            self.stdscr.addstr(sky_oy,     px, "┌─ Pointage ──────────┐", curses.color_pair(4))
            self.stdscr.addstr(sky_oy + 1, px, f"│ RA : {self.ra_to_hms(self.ra)[:14]}  │", curses.color_pair(3))
            self.stdscr.addstr(sky_oy + 2, px, f"│ Dec: {self.dec_to_dms(self.dec)[:14]}  │", curses.color_pair(3))
            self.stdscr.addstr(sky_oy + 3, px, "├─ Cible ─────────────┤", curses.color_pair(4))
            target = obj["name"][:18] if dist < 12 else "espace vide"
            self.stdscr.addstr(sky_oy + 4, px, f"│ {target[:20]:<20} │", curses.color_pair(2))
            self.stdscr.addstr(sky_oy + 5, px, "├─ Captures ──────────┤", curses.color_pair(4))
            for i in range(3):
                if i < len(self.captures):
                    cap_name = self.captures[i]["name"][:16]
                    self.stdscr.addstr(sky_oy + 6 + i, px, f"│ ✓ {cap_name:<18} │", curses.color_pair(1))
                else:
                    self.stdscr.addstr(sky_oy + 6 + i, px, "│ ○ en attente          │", curses.color_pair(4))
            self.stdscr.addstr(sky_oy + 9, px, "└─────────────────────┘", curses.color_pair(4))
        except curses.error:
            pass

        # ── Message bas ───────────────────────────────────────────────────────
        msg_y = border_y + 1
        try:
            if len(self.captures) >= 3:
                msg = ">>> 3 captures OK — appuyez sur ENTRÉE pour envoyer et payer <<<"
                self.stdscr.addstr(msg_y, 2, msg, curses.color_pair(1) | curses.A_BOLD)
            else:
                remaining = 3 - len(self.captures)
                msg = f"Flèches: pointer  │  Espace: capturer ({remaining} restante{'s' if remaining > 1 else ''})  │  Q: quitter"
                self.stdscr.addstr(msg_y, 2, msg, curses.color_pair(3))
            self.stdscr.addstr(msg_y + 1, 2, self.message, curses.color_pair(4))
        except curses.error:
            pass

        self.stdscr.refresh()

    def run(self):
        curses.curs_set(0)
        self.stdscr.timeout(40)

        while not self.done:
            self.draw()
            key = self.stdscr.getch()

            if key == curses.KEY_LEFT:
                self.ra  = (self.ra - self.step) % 360
                self.message = f"RA  → {self.ra_to_hms(self.ra)}"
            elif key == curses.KEY_RIGHT:
                self.ra  = (self.ra + self.step) % 360
                self.message = f"RA  → {self.ra_to_hms(self.ra)}"
            elif key == curses.KEY_UP:
                self.dec = min(90, self.dec + self.step)
                self.message = f"Dec → {self.dec_to_dms(self.dec)}"
            elif key == curses.KEY_DOWN:
                self.dec = max(-90, self.dec - self.step)
                self.message = f"Dec → {self.dec_to_dms(self.dec)}"
            elif key == ord(' ') and len(self.captures) < 3:
                self.do_capture()
            elif key in (ord('\n'), ord('\r'), 10, 13) and len(self.captures) >= 3:
                self.done = True
            elif key in (ord('q'), ord('Q')):
                self.captures = []
                self.done = True

        return self.captures

    def do_capture(self):
        obj, dist = self.nearest_object()
        name = obj["name"] if dist < 12 else f"RA {self.ra:.1f}° Dec {self.dec:.1f}°"
        cap = {
            "id":      str(uuid.uuid4())[:8],
            "ra":      round(self.ra, 4),
            "dec":     round(self.dec, 4),
            "name":    name,
            "filters": ["R", "G", "B"],
            "url":     f"https://telescope.cern.ch/{str(uuid.uuid4())[:8]}.fits",
            "hash":    hashlib.sha256(f"{self.ra}{self.dec}{time.time()}".encode()).hexdigest()[:16],
        }
        self.captures.append(cap)
        self.message = f"✓ Capture #{len(self.captures)} : {name}"


def run_controller():
    return curses.wrapper(lambda s: TelescopeController(s).run())


# ─── Flux XRPL + paiement ────────────────────────────────────────────────────

async def run_telescope_demo(provider_id, researcher_id, captures):
    print("\n" + "═" * 56)
    print("  TelescopeGrid — Traitement XRPL")
    print("═" * 56)

    loop = asyncio.get_event_loop()

    # Wallets
    researcher_wallet = get_wallet(researcher_id)
    oracle_wallet     = Wallet.from_seed(config.ORACLE_WALLET_SEED)
    print(f"\n  Chercheur : {researcher_wallet.address}")
    print(f"  Oracle    : {oracle_wallet.address}")

    # NFT slot
    print("\n[1] CERN mint un slot d'observation (NFT)...")
    nftoken_id = await loop.run_in_executor(
        None, partial(mint_slot, provider_id, {
            "taxon": 1, "transfer_fee": 5,
            "uri": "telescopegrid://slot/cern-t1/3captures",
        })
    )
    print(f"    NFT slot : {nftoken_id[:28]}...")

    print("[2] Arnaud achète le slot...")
    offer_id = await loop.run_in_executor(
        None, partial(create_sell_offer, provider_id, nftoken_id, 0)
    )
    await loop.run_in_executor(None, partial(buy_slot, researcher_id, offer_id))
    print("    Slot acheté ✓")

    # Condition + Escrow
    print("\n[3] Oracle génère la condition...")
    job_id = str(uuid.uuid4())[:16]
    keys   = JobCryptoKeys()
    obs_hash = hashlib.sha256(json.dumps(captures, sort_keys=True).encode()).hexdigest()
    obs_payload = json.dumps({"captures": captures, "obs_hash": obs_hash}, separators=(",", ":"))

    print(f"[4] Arnaud crée l'escrow (1 XRP)...")
    async with AsyncWebsocketClient(config.XRPL_WS_URL) as client:
        escrow_response = await client_create_escrow(
            client         = client,
            client_wallet  = researcher_wallet,
            oracle_address = oracle_wallet.address,
            condition      = keys.condition,
            xrp_amount     = 1.0,
            qasm           = obs_payload,
            shots          = len(captures),
            job_id         = job_id,
            ttl_seconds    = 300,
        )
        escrow_tx = escrow_response.result
        tx_result = escrow_tx.get("meta", {}).get("TransactionResult")
        print(f"    EscrowCreate → {tx_result}")
        if tx_result != "tesSUCCESS":
            print(f"    Escrow échoué : {tx_result}")
            return

        sequence = escrow_tx.get("Sequence") or escrow_tx.get("tx_json", {}).get("Sequence")
        if not sequence:
            resp = await client.request(AccountTx(account=researcher_wallet.address, limit=5))
            for tx_entry in resp.result.get("transactions", []):
                tx_inner = tx_entry.get("tx", tx_entry.get("tx_json", {}))
                if tx_inner.get("TransactionType") == "EscrowCreate":
                    sequence = tx_inner.get("Sequence")
                    break

        job = EscrowJob(
            tx_hash=escrow_tx.get("hash", ""), sequence=sequence,
            owner=researcher_wallet.address, destination=oracle_wallet.address,
            amount_drops=str(1_000_000), condition=keys.condition,
            cancel_after=None, qasm=obs_payload, shots=len(captures), job_id=job_id,
        )

        # Livraison des images
        print(f"\n[5] Opérateur CERN photographie les cibles...")
        for i, cap in enumerate(captures):
            time.sleep(0.6)
            print(f"    [{i+1}] {cap['name']:28s} → {cap['url']}")

        # Vérification
        print(f"\n[6] Oracle vérifie les {len(captures)} images...")
        for cap in captures:
            assert cap.get("hash"), f"Hash manquant pour {cap['name']}"
        print(f"    ✓ Toutes les images vérifiées")

        # EscrowFinish
        print(f"\n[7] Oracle libère le paiement...")
        finish = await escrow_finish(
            client=client, wallet=oracle_wallet, job=job,
            fulfillment=keys.fulfillment,
            result_memo={"job_id": job_id, "captures": len(captures),
                         "obs_hash": obs_hash, "images": [c["url"] for c in captures]},
        )
        finish_result = finish.result.get("meta", {}).get("TransactionResult")
        print(f"    EscrowFinish → {finish_result}")

        # Paiement CERN
        print(f"\n[8] Oracle reverse 90% au CERN...")
        provider_wallet = get_wallet(provider_id)
        await pay_provider(client=client, oracle_wallet=oracle_wallet,
                           provider_address=provider_wallet.address,
                           total_drops=1_000_000, commission_pct=COMMISSION)
        print(f"    0.90 XRP → CERN   ({provider_wallet.address[:20]}...)")
        print(f"    0.10 XRP → Oracle (commission)")

        # NFT résultat
        print(f"\n[9] Mint NFT de preuve on-chain...")
        nft_result = await loop.run_in_executor(
            None, partial(mint_slot, provider_id, {
                "taxon": 2, "transfer_fee": 0,
                "uri": f"telescopegrid://result/{job_id}/{obs_hash[:12]}",
            })
        )
        print(f"    NFT résultat : {nft_result[:28]}...")

    print("\n" + "═" * 56)
    print("  ✓ Mission accomplie !")
    print(f"  {len(captures)} images livrées à Arnaud")
    print(f"  CERN payé · Oracle commissionné · Preuve on-chain")
    print("═" * 56 + "\n")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _, provider_id   = add_wallet("CERN",   "fournisseur")
    _, researcher_id = add_wallet("Arnaud", "chercheur")
    print(f"CERN   : {get_wallet(provider_id).address}")
    print(f"Arnaud : {get_wallet(researcher_id).address}")
    print("\nContrôles : Flèches = pointer  |  Espace = capturer  |  Entrée = envoyer  |  Q = quitter")
    input("\nAppuyez sur ENTRÉE pour ouvrir le télescope...")

    captures = run_controller()

    if not captures:
        print("Aucune capture — démo annulée.")
    else:
        asyncio.run(run_telescope_demo(provider_id, researcher_id, captures))