import os
from dotenv import load_dotenv

load_dotenv()

XRPL_WS_URL      = os.getenv("XRPL_WS_URL", "wss://s.altnet.rippletest.net:51233")  
ORACLE_WALLET_SEED = os.getenv("ORACLE_WALLET_SEED")        
ORACLE_ADDRESS     = os.getenv("ORACLE_ADDRESS")       

QUANTUMGRID_TAG  = int(os.getenv("QUANTUMGRID_TAG", "42000"))

MIN_ESCROW_DROPS = int(os.getenv("MIN_ESCROW_DROPS", "1000000")) 

ESCROW_TTL_LEDGERS = int(os.getenv("ESCROW_TTL_LEDGERS", "100"))

IBM_TOKEN          = os.getenv("IBM_QUANTUM_TOKEN", "")
IBM_INSTANCE       = os.getenv("IBM_QUANTUM_INSTANCE", "ibm-q/open/main")
IBM_BACKEND        = os.getenv("IBM_BACKEND", "ibm_nairobi")  
USE_SIMULATOR      = os.getenv("USE_SIMULATOR", "true").lower() == "true"

LOG_LEVEL          = os.getenv("LOG_LEVEL", "INFO")
POLL_INTERVAL_S    = float(os.getenv("POLL_INTERVAL_S", "3.0"))
MAX_SHOTS          = int(os.getenv("MAX_SHOTS", "8192"))
