import os
from dotenv import load_dotenv
from py_clob_client_v2.client import ClobClient
from py_builder_relayer_client.client import RelayClient
from py_builder_signing_sdk.config import BuilderConfig
from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds
from poly_web3 import PolyWeb3Service

load_dotenv()

PRIVATE_KEY = os.environ.get("EVM_PRIVATE")
FUNDER_ADDRESS = os.environ.get("DEPOSIT_WALLET")

# 1. Initialize the official Polymarket CLOB Client
client = ClobClient(
    host="https://clob.polymarket.com",
    key=PRIVATE_KEY,
    chain_id=137,
    signature_type=3,          # 1 = Proxy/Funder wallet, 0 = direct EOA
    funder=FUNDER_ADDRESS      # Your deposit wallet
)

chain_id = 137

RELAYER_URL = os.environ.get("RELAYER_URL", "https://relayer-v2.polymarket.com/")
CHAIN_ID    = int(os.environ.get("CHAIN_ID", "137"))

def make_relayer() -> RelayClient:
    """Build a RelayClient from env vars. Call after load_dotenv()."""
    config = BuilderConfig(
        local_builder_creds = BuilderApiKeyCreds(
            key = os.getenv("BUILDER_API_KEY"),
            secret = os.getenv("BUILDER_SECRET"),
            passphrase = os.getenv("BUILDER_PASS_PHRASE"),
        )
    )
    return RelayClient(
        "https://relayer-v2.polymarket.com/",
        137,
        os.getenv("EVM_PRIVATE"),
        config,
    )

relayer = make_relayer()

# 2. Initialize the PolyWeb3 service
service = PolyWeb3Service(
    clob_client=client,
    relayer_client=relayer,
    rpc_url="https://polygon-bor.publicnode.com",  # Swap with your preferred RPC if needed
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