import streamlit as st
import time
import os
import hashlib
from datetime import datetime, timedelta
from xrpl.clients import JsonRpcClient
from xrpl.wallet import generate_faucet_wallet
from xrpl.models.transactions import EscrowCreate, EscrowFinish
from xrpl.transaction import submit_and_wait
from xrpl.utils import datetime_to_ripple_time

# --- CONFIGURATION VISUELLE DE LA PAGE ---
st.set_page_config(page_title="QuantumGrid", page_icon="🌌", layout="centered")

st.title("🌌 QuantumGrid")
st.subheader("La Marketplace DePIN pour le Calcul Quantique")
st.write("Louez du temps de calcul (Qubits) sans intermédiaire grâce aux Smart Escrows de l'XRP Ledger.")
st.divider()

# --- BOUTON PRINCIPAL ---
if st.button("🚀 Louer un Processeur Quantique (Prix : 10 XRP)", use_container_width=True, type="primary"):
    
    st.write("### Journal d'exécution :")
    
    # 1. SETUP DES COMPTES
    with st.spinner('Création des identités sur la blockchain (Testnet)...'):
        client = JsonRpcClient("https://s.altnet.rippletest.net:51234")
        student_wallet = generate_faucet_wallet(client)
        oracle_wallet = generate_faucet_wallet(client)
        st.success(f"🧑‍🎓 Compte Étudiant : `{student_wallet.classic_address}`")
        st.success(f"🔬 Compte Labo Quantique : `{oracle_wallet.classic_address}`")

    # 2. SERRURE CRYPTO (AVEC LA CORRECTION)
    ORACLE_SECRET = os.urandom(32)
    hash_hex = hashlib.sha256(ORACLE_SECRET).hexdigest().upper()
    CONDITION = f"A0258020{hash_hex}810120"
    FULFILLMENT = f"A0228020{ORACLE_SECRET.hex().upper()}" # La bonne clé !
    
    # 3. CRÉATION DE L'ESCROW
    with st.spinner('L\'étudiant verrouille les fonds dans le Smart Escrow...'):
        demain = datetime.now() + timedelta(days=1)
        escrow_tx = EscrowCreate(
            account=student_wallet.classic_address,
            amount="10000000", # 10 XRP
            destination=oracle_wallet.classic_address,
            condition=CONDITION,
            cancel_after=datetime_to_ripple_time(demain)
        )
        response_create = submit_and_wait(escrow_tx, client, student_wallet)
        sequence_number = response_create.result["tx_json"]["Sequence"]
        st.info(f"🔒 **Fonds Sécurisés !** 10 XRP bloqués (Séquence du contrat : {sequence_number})")

    # 4. SIMULATION QUANTIQUE (L'Oracle travaille)
    st.write("⚙️ **Calcul Quantique en cours...** (Algorithme de Shor)")
    progress_bar = st.progress(0)
    for percent_complete in range(100):
        time.sleep(0.03) # On simule le temps de calcul
        progress_bar.progress(percent_complete + 1)
    st.success("🎯 **Résultat Quantique généré avec succès !**")

    # 5. DÉBLOCAGE DES FONDS
    with st.spinner('L\'Oracle soumet la preuve cryptographique pour récupérer le paiement...'):
        finish_tx = EscrowFinish(
            account=oracle_wallet.classic_address,
            owner=student_wallet.classic_address,
            offer_sequence=sequence_number,
            condition=CONDITION,
            fulfillment=FULFILLMENT
        )
        response_finish = submit_and_wait(finish_tx, client, oracle_wallet)

    if response_finish.is_successful():
        st.balloons() # L'animation de victoire sur l'écran !
        st.success(f"🎉 **BINGO ! PAIEMENT DÉBLOQUÉ.**")
        st.write(f"💰 Le Labo Quantique a reçu ses 10 XRP en échange de la preuve de calcul.")
    else:
        st.error("❌ Échec de la transaction lors du déblocage.")

st.divider()
st.caption("Projet Hackathon - Track: Programmability (XRPL)")