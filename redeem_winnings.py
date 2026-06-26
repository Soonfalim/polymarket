import os
from dotenv import load_dotenv
from py_clob_client_v2.client import ClobClient
from poly_web3 import PolyWeb3Service
from _func import make_relayer

load_dotenv()

PRIVATE_KEY = os.getenv("EVM_PRIVATE")
FUNDER_ADDRESS = os.getenv("DEPOSIT_WALLET")

# 1. Initialize the official Polymarket CLOB Client
client = ClobClient(
    host="https://clob.polymarket.com",
    key=PRIVATE_KEY,
    chain_id=137,
    signature_type=3,          # 1 = Proxy/Funder wallet, 0 = direct EOA
    funder=FUNDER_ADDRESS      # Your deposit wallet
)

relayer = make_relayer()

# 2. Initialize the PolyWeb3 service
service = PolyWeb3Service(
    clob_client=client,
    relayer_client=relayer,
    rpc_url="https://polygon-bor.publicnode.com",
)

print(f"Scanning funder address {FUNDER_ADDRESS} for unredeemed winnings...")

# 3. Redeem ALL resolved markets in batches
result = service.redeem_all(batch_size=10)

if result.success_list:
    print(f"✅ Successfully redeemed positions!")
    for success in result.success_list:
        print(success)
else:
    print("🤷 No unredeemed winning positions found.")

if result.error_list:
    print(f"⚠️ Errors encountered:")
    for error in result.error_list:
        print(error)