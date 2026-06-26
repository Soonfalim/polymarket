import os
import time

from py_builder_relayer_client.client import RelayClient
from py_builder_relayer_client.models import TransactionType
from py_builder_signing_sdk.config import BuilderApiKeyCreds, BuilderConfig

from dotenv import load_dotenv
load_dotenv()

RELAYER_URL = "https://relayer-v2.polymarket.com/"
CHAIN_ID    = 137


def make_relayer() -> RelayClient:
    """Build a RelayClient from env vars. Call after load_dotenv()."""
    config = BuilderConfig(
        local_builder_creds=BuilderApiKeyCreds(
            key=os.getenv("BUILDER_API_KEY"),
            secret=os.getenv("BUILDER_SECRET"),
            passphrase=os.getenv("BUILDER_PASS_PHRASE"),
        )
    )
    return RelayClient(
        RELAYER_URL,
        CHAIN_ID,
        os.getenv("EVM_PRIVATE"),
        config,
    )

def wallet_batch(relayer: RelayClient, deposit_wallet: str, calls: list) -> object:
    """
    Fetch WALLET nonce, sign, and submit a batch of on-chain calls
    from the deposit wallet. Returns the confirmed receipt object.

    calls: list of DepositWalletCall(target, value, data)
    """
    nonce_payload = relayer.get_nonce(
        relayer.signer.address(),
        TransactionType.WALLET.value,
    )
    nonce    = str(nonce_payload["nonce"])
    deadline = str(int(time.time()) + 240)

    response = relayer.execute_deposit_wallet_batch(
        calls=calls,
        wallet_address=deposit_wallet,
        nonce=nonce,
        deadline=deadline,
    )
    return response.wait()