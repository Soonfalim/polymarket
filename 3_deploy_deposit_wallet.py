import os
from dotenv import load_dotenv

from py_builder_relayer_client.client import RelayClient
from py_builder_relayer_client.models import TransactionType
from py_builder_signing_sdk.config import BuilderApiKeyCreds, BuilderConfig

RELAYER_URL = os.environ.get("RELAYER_URL", "https://relayer-v2.polymarket.com/")
CHAIN_ID    = int(os.environ.get("CHAIN_ID", "137"))

# Load the variables from .env into the environment
load_dotenv()

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

# Deterministically derive the deposit wallet address before deploying
deposit_wallet = relayer.get_expected_deposit_wallet()
print(f"Chain          : {CHAIN_ID}")
print(f"Owner (EOA)    : {relayer.signer.address()}")
print(f"Deposit wallet : {deposit_wallet}  (deterministic — store as DEPOSIT_WALLET in .env)\n")

print("Submitting WALLET-CREATE to relayer…")
response  = relayer.deploy_deposit_wallet()
confirmed = response.wait()

print(f"\n✓ Deposit wallet deployed: {deposit_wallet}")
print(f"  Add to .env:  DEPOSIT_WALLET={deposit_wallet}")
print("\nNext: fund the wallet — send USDC.e to your EOA then run 3_wrap.py")