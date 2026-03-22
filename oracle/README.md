# QuantumGrid / TelescopeGrid

**DePIN Oracle — XRPL + Qiskit + IBM Quantum**

Hackathon 2026 · EPFL · Brieuc Jubert

---

## Vision

OpenGate est un marketplace décentralisé (DePIN) qui permet à un chercheur de payer un fournisseur de ressources (calcul quantique ou temps de télescope) de façon totalement trustless sur le ledger XRPL.

L'oracle joue le rôle de juge cryptographique : il ne libère le paiement qu'après avoir vérifié que la prestation a bien été livrée. Ni le fournisseur ne peut partir avec l'argent sans livrer, ni le chercheur ne peut refuser de payer après livraison.

---

## Architecture

### 3 acteurs

- **Chercheur (client)** — soumet une requête et verrouille le paiement dans un escrow XRPL
- **Fournisseur (CERN)** — exécute la prestation (calcul quantique ou observation télescope)
- **Oracle** — vérifie la livraison et révèle le fulfillment pour libérer le paiement

### Flux de paiement

```
Chercheur → EscrowCreate (XRP verrouillés)
Oracle    → détecte l'escrow → exécute → vérifie
Oracle    → EscrowFinish (fulfillment révélé) → XRP libérés
Oracle    → Payment → 90% au fournisseur, 10% commission
```

### Mécanisme cryptographique

Chaque job utilise une condition **PREIMAGE-SHA-256** (format ASN.1 XRPL). L'oracle génère un secret aléatoire (preimage), calcule la condition publique et la met dans l'escrow. Le preimage n'est révélé qu'après vérification de la livraison — c'est la garantie trustless.

---

## Services disponibles

### Quantum (`bridge.py`)

Le chercheur soumet un circuit QASM. L'oracle l'exécute sur Qiskit Aer (simulateur) ou IBM Quantum (hardware réel). Le résultat est publié on-chain dans les memos de l'EscrowFinish avec l'URL de vérification IBM.

- Circuit Bell State par défaut (2 qubits, intrication quantique)
- Compatible IBM Quantum via qiskit-ibm-runtime 0.43+
- Vérification IBM : statut DONE + cohérence des counts

### Télescope (`bridge_tele.py`)

Le chercheur contrôle un télescope interactif dans le terminal (curses), pointe 3 cibles avec les flèches du clavier, et valide. Les coordonnées RA/Dec sont envoyées à l'opérateur qui photographie et livre les images FITS.

- Interface terminale avec carte du ciel étoilée
- 10 objets célèbres : Nébuleuse d'Orion, Galaxie d'Andromède, Pléiades...
- Vérification : hash d'intégrité de chaque image

---

## Lancement

### Prérequis

```bash
pip install -r requirements.txt
cp .env.example .env  
```

### Commandes

**Terminal — Soumettre une demande quantique :**
```bash
python3 client.py quantum \
  --client   r9tHfqy8mFm3VsG341jJNFBk1W8JgHkDJR \
  --provider rBDc2z234zgDSqHPf9z8Ayw6ufpauDhWpx \
  --amount   1.0
```

**Terminal — Soumettre une observation télescope :**
```bash
python3 client.py telescope \
  --client   r9tHfqy8mFm3VsG341jJNFBk1W8JgHkDJR \
  --provider rBDc2z234zgDSqHPf9z8Ayw6ufpauDhWpx \
  --amount   1.0
```
### Mode avec oracle2 et bridge2 (tout-en-un)

**Terminal 1 — Serveur oracle (laisser tourner) :**
```bash
python3 oracle2.py
```

**Terminal 2 — soumettre bridge2 :**
```bash
python3 .py
```


### Démo scénario timeout (protection anti-panne)

```bash
python3 demo_timeout.py
```

Simule IBM qui ne répond pas : escrow créé avec TTL 30s, monitor détecte l'expiration et annule automatiquement. L'argent est retourné au chercheur.

---

## Structure des fichiers

| Fichier | Rôle |
|---|---|
| `client.py` | Point d'entrée unifié — choisit quantum ou telescope, passe les adresses |
| `bridge.py` | Flux complet calcul quantique : NFT → escrow → Qiskit/IBM → paiement |
| `bridge_tele.py` | Flux complet télescope : contrôleur curses → NFT → escrow → images → paiement |
| `oracle.py` | Serveur autonome — écoute le ledger XRPL et traite les jobs |
| `oracle2.py` | Oracle amélioré avec pay_provider + NFT résultat intégrés |
| `xrpl_client.py` | EscrowCreate, EscrowFinish, EscrowCancel, Payment |
| `crypto_condition.py` | Génération PREIMAGE-SHA-256 ASN.1 — condition + fulfillment |
| `quantum_executor.py` | Exécution Qiskit Aer ou IBM Quantum + vérification IBM |
| `escrow_monitor.py` | Surveille les TTL — annule automatiquement les escrows expirés |
| `demo_timeout.py` | Démo scénario panne IBM — protection automatique |
| `test_e2e.py` | Test bout en bout du flux oracle complet |
| `src/nft.py` | mint_slot, buy_and_certify, buy_slot — NFTs XRPL (code binôme) |
| `src/wallets.py` | create_wallet, get_wallet — gestion des wallets (code binôme) |

---

## Configuration (.env)

| Variable | Description |
|---|---|
| `ORACLE_WALLET_SEED` | Seed du wallet oracle **(requis)** |
| `ORACLE_ADDRESS` | Adresse publique de l'oracle |
| `XRPL_WS_URL` | WebSocket XRPL testnet (défaut: altnet) |
| `USE_SIMULATOR` | `true` = Qiskit local, `false` = IBM réel |
| `IBM_QUANTUM_TOKEN` | Clé API IBM Cloud Quantum |
| `IBM_QUANTUM_INSTANCE` | CRN de l'instance IBM Cloud |
| `IBM_BACKEND` | Backend IBM (ex: `ibm_fez`, `ibm_torino`) |
| `QUANTUMGRID_TAG` | DestinationTag XRPL (défaut: `42000`) |

---

## Transactions XRPL vérifiables

Toutes les transactions sont publiques sur le testnet XRPL. Les memos de l'EscrowFinish contiennent le résultat complet : counts quantiques, result_hash, ibm_job_id, URL de vérification IBM.

- Explorer testnet : https://testnet.xrpl.org
- Vérification IBM : `https://quantum.ibm.com/jobs/{ibm_job_id}`

**Exemple de flux on-chain :**
- `SÉQUESTRE CRÉÉ` — Chercheur verrouille 1 XRP
- `SÉQUESTRE FINALISÉ` — Oracle révèle le fulfillment
- `PAIEMENT EFFECTUÉ` — Oracle envoie 0.90 XRP au fournisseur

---

## Stack technique

- **XRPL** — xrpl-py ≥ 2.4.0 (EscrowCreate, EscrowFinish, NFTokenMint, Payment)
- **Quantum** — Qiskit ≥ 1.0, Qiskit Aer, qiskit-ibm-runtime 0.43+
- **Async** — Python 3.9, asyncio, run_in_executor pour compatibilité
- **NFTs** — XRPL NFTokenMint, buy_and_certify (preuve d'achat on-chain)
- **Crypto** — PREIMAGE-SHA-256 ASN.1, format validé par selftest automatique
- **Monitoring** — escrow_monitor (TTL watchdog, annulation automatique)
