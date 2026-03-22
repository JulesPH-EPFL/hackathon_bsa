# QuantumGrid

A decentralized marketplace for renting scientific instruments — telescopes, quantum computers, synchrotrons — from research institutions around the world.

Researchers pay directly on the XRPL blockchain. A trustless oracle verifies delivery before releasing payment. Every transaction is public and verifiable on-chain.

🌐 **Live demo:** https://bsa-website-five.vercel.app

---

## Architecture

Three independent services working together:

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   Frontend          │     │   Backend (Node.js) │     │   XRPL Layer        │
│   Vercel            │────▶│   Render            │────▶│   Render            │
│   HTML/CSS/JS       │     │   Express + Prisma  │     │   Flask + xrpl-py   │
│   bsa-website       │     │   PostgreSQL        │     │   bsa-xrpl          │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
```

### Three actors

- **Researcher** — browses instruments, pays in XRP, receives NFT proof
- **Provider (e.g. CERN)** — delivers the service (quantum compute or telescope observation)
- **Oracle** — cryptographic judge: verifies delivery and releases payment trustlessly

### Payment flow

```
Researcher pays Provider in XRP
        ↓
Researcher mints NFT receipt (proof of payment, on-chain)
        ↓
[If oracle job] Researcher creates cryptographic escrow
        ↓
[If oracle job] Oracle executes the job (quantum circuit or telescope)
        ↓
[If oracle job] EscrowFinish → 90% to Provider + 10% Oracle commission
        ↓
Researcher mints NFT result (proof of delivery, on-chain)
```

### Cryptographic mechanism

Each job uses a **PREIMAGE-SHA-256** condition (ASN.1 XRPL format). The oracle generates a random secret (preimage), computes the public condition and embeds it in the escrow. The preimage is only revealed after delivery is verified — this is the trustless guarantee. Neither party can cheat.

---

## Services

### Direct booking (`job_type: "direct"`)

Simple XRP payment + NFT receipt. Used for telescopes, weather stations, microscopes, and any resource that doesn't require oracle validation.

### Quantum computing (`job_type: "quantum"`)

The researcher submits a QASM circuit. The oracle executes it on Qiskit Aer (simulator) or IBM Quantum (real hardware). Results are published on-chain in the EscrowFinish memos with the IBM verification URL.

- Bell State circuit by default (2 qubits, quantum entanglement)
- Compatible with IBM Quantum via qiskit-ibm-runtime 0.43+
- Verification: IBM DONE status + counts consistency check

### Telescope observation (`job_type: "telescope"`)

The researcher uses an interactive terminal interface (curses) to point a telescope at 3 targets using arrow keys. The operator photographs and delivers FITS images. The oracle verifies each image via integrity hash.

- Terminal interface with star map
- 10 famous sky objects: Orion Nebula, Andromeda Galaxy, Pleiades...
- Timeout protection: if delivery fails, escrow is cancelled automatically

Note: on the website, only JamesWebb and IBM are valid for a demo.

---

## Repository structure

```
hackathon_bsa/
├── frontend/               # Vanilla HTML/CSS/JS — hosted on Vercel
│   ├── index.html
│   ├── css/
│   └── js/
│       ├── auth.js         # Authentication
│       ├── config.js       # API URLs and constants
│       ├── instruments.js  # Instrument catalogue
│       ├── wallet.js       # Wallet management
│       └── ...
│
├── backend/                # Node.js + Express — hosted on Render
│   └── db/
│       ├── prisma/         # Database schema
│       ├── src/            # API routes
│       ├── package.json
│       └── tsconfig.json
│
└── xrpl/                   # Python Flask + xrpl-py — hosted on Render
    ├── src/
    │   ├── api.py              # Flask server — HTTP endpoints
    │   ├── config.py           # XRPL testnet connection
    │   ├── nft.py              # NFT transactions + payments
    │   ├── wallets.py          # Wallet creation and reconstruction
    │   ├── bridge2.py          # Full quantum oracle flow
    │   ├── bridge_tele.py      # Full telescope oracle flow
    │   ├── client.py           # CLI launcher
    │   ├── config2.py          # Oracle config (env variables)
    │   ├── crypto_condition.py # XRPL cryptographic conditions
    │   ├── oracle.py           # Main oracle loop
    │   ├── quantum_executor.py # Qiskit circuit execution
    │   └── xrpl_client.py      # Escrow XRPL transactions
    ├── requirements.txt
    ├── Procfile
    └── .env
```

---

## Frontend

Vanilla HTML/CSS/JS single-page app hosted on Vercel.

Researchers can create an account, browse available instruments, and book sessions directly from the platform. Each instrument has defined time slots, a location, and a price in XRP per session. Once booked, the session is visible in the user's dashboard.

**Running locally:** open `frontend/index.html` in a browser — no build step required.

---

## Backend

Node.js + Express API hosted on Render, connected to a PostgreSQL database managed through Prisma.

The database stores users, instruments, and sessions. Users have an email, a hashed password, and an XRPL wallet address generated at signup. Instruments belong to providers and carry metadata like type, location, agenda, and pricing. Sessions link a user to an instrument and track the status, cost, and transaction hash.

**Running locally:**

```bash
cd backend/db
cp .env.example .env   # add your DATABASE_URL
npm install
npx prisma migrate dev
npm run dev
```

---

## XRPL Layer

Python Flask API hosted on Render. Handles all blockchain logic — wallet creation, NFT minting, payments, and oracle flows.

### Installation

```bash
cd xrpl
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Environment variables

Create a `.env` file in the `xrpl/` directory:

```
ORACLE_WALLET_SEED=sXXXXXXXXXXXXXXXX
ORACLE_ADDRESS=rXXXXXXXXXXXXXXXX
XRPL_WS_URL=wss://s.altnet.rippletest.net:51233
USE_SIMULATOR=true
QUANTUMGRID_TAG=42000
MIN_ESCROW_DROPS=1000000
MAX_SHOTS=8192
LOG_LEVEL=INFO
```

| Variable | Description |
|---|---|
| `ORACLE_WALLET_SEED` | Oracle wallet seed **(required)** |
| `ORACLE_ADDRESS` | Oracle public address |
| `XRPL_WS_URL` | XRPL WebSocket URL |
| `USE_SIMULATOR` | `true` = local Qiskit, `false` = real IBM |
| `IBM_QUANTUM_TOKEN` | IBM Cloud Quantum API key |
| `IBM_BACKEND` | IBM backend (e.g. `ibm_fez`) |

### Start the API

```bash
python3 -m src.api
```

API runs on `http://localhost:5001`.

### Endpoints

#### `GET /new_wallet`

Creates a new XRPL wallet on testnet.

**Response:**
```json
{
  "address": "rXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
  "seed": "sXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
}
```

⚠️ The seed is returned only once — store it immediately in the database.

---

#### `GET /users_infos/<address>`

Returns public information about a wallet.

**Response:**
```json
{
  "address": "rXXX",
  "balance_xrp": 84.99978,
  "nfts": [
    {
      "NFTokenID": "000800001575E...",
      "URI": "observatory=Geneva&units=30&tx_hash=...",
      "NFTokenTaxon": 1
    }
  ]
}
```

---

#### `POST /payment`

Full payment flow. Behavior depends on `job_type`.

**Direct booking:**
```json
{
  "job_type": "direct",
  "buyer_seed": "sXXX",
  "observatory_address": "rXXX",
  "observatory_id": "observatory_geneva",
  "units": 30,
  "currency": "MIN",
  "date": "2026-03-22",
  "price_xrp_per_unit": 0.1
}
```

**Quantum oracle:**
```json
{
  "job_type": "quantum",
  "buyer_seed": "sXXX",
  "observatory_address": "rXXX",
  "amount_xrp": 1.0
}
```

**Telescope oracle:**
```json
{
  "job_type": "telescope",
  "buyer_seed": "sXXX",
  "observatory_address": "rXXX",
  "amount_xrp": 1.0,
  "captures": [
    {
      "id": "a1b2c3d4",
      "ra": 83.82,
      "dec": -5.39,
      "name": "Orion Nebula",
      "filters": ["R", "G", "B"],
      "url": "https://telescope.cern.ch/abc.fits",
      "hash": "a3f9b2c1d4e5f6a7"
    }
  ]
}
```

### CLI launcher

Test oracle flows directly without the API:

```bash
# Quantum circuit
python3 -m src.client quantum \
  --seed sXXXXXXXXXXXXXXXX \
  --provider rXXXXXXXXXXXXXXXX \
  --amount 1.0

# Interactive telescope
python3 -m src.client telescope \
  --seed sXXXXXXXXXXXXXXXX \
  --provider rXXXXXXXXXXXXXXXX \
  --amount 1.0
```

---

## On-chain verification

All transactions are public on the XRPL testnet. EscrowFinish memos contain the full result: quantum counts, result hash, IBM job ID, and IBM verification URL.

- XRPL testnet explorer: https://testnet.xrpl.org
- IBM Quantum verification: `https://quantum.ibm.com/jobs/{ibm_job_id}`

**Example on-chain flow:**
1. `EscrowCreate` — Researcher locks 1 XRP
2. `EscrowFinish` — Oracle reveals the fulfillment
3. `Payment` — Oracle sends 0.90 XRP to provider

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | HTML / CSS / JavaScript — Vercel |
| Backend | Node.js, Express, Prisma, PostgreSQL — Render |
| Blockchain | xrpl-py ≥ 2.4.0, XRPL testnet |
| Oracle | Python asyncio, PREIMAGE-SHA-256 ASN.1 |
| Quantum | Qiskit ≥ 1.0, Qiskit Aer, qiskit-ibm-runtime 0.43+ |
| NFTs | XRPL NFTokenMint — receipt + result proofs |
