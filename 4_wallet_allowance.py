import os
import sys
import time
from dotenv import load_dotenv
from web3 import Web3
from py_builder_relayer_client.models import DepositWalletCall

from py_builder_relayer_client.client import RelayClient
from py_builder_relayer_client.models import DepositWalletCall, TransactionType
from py_builder_signing_sdk.config import BuilderApiKeyCreds, BuilderConfig

# Load the variables from .env into the environment
load_dotenv()

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



PRIVATE_KEY    = os.getenv("EVM_PRIVATE")
DEPOSIT_WALLET = os.getenv("DEPOSIT_WALLET")
RPC_URL        = os.environ.get("POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com")

DW = Web3.to_checksum_address(DEPOSIT_WALLET)

PUSD        = Web3.to_checksum_address("0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB")
CTF         = Web3.to_checksum_address("0x4D97DCd97eC945f40cF65F87097ACe5EA0476045")
CTF_EX      = Web3.to_checksum_address("0xE111180000d2663C0091e4f400237545B87B996B")
NR_EX       = Web3.to_checksum_address("0xe2222d279d744050d28e00520010520000310F59")
NR_ADPT     = Web3.to_checksum_address("0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296")
# Both adapter contracts are NOT on the relayer's approve allowlist:
#   CTF_ADPT    = 0xADa100874d00e3331D00F2007a9c336a65009718 (CtfCollateralAdapter)
#   NR_CTF_ADPT = 0xAdA200001000ef00D07553cEE7006808F895c6F1 (NegRiskCtfCollateralAdapter)
OFFRAMP     = Web3.to_checksum_address("0x2957922Eb93258b93368531d39fAcCA3B4dC5854")

MAX_UINT256 = 2**256 - 1

ERC20_ABI = [
    {"name": "allowance", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "approve",   "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]},
]

ERC1155_ABI = [
    {"name": "isApprovedForAll", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "account", "type": "address"}, {"name": "operator", "type": "address"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"name": "setApprovalForAll", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "operator", "type": "address"}, {"name": "approved", "type": "bool"}],
     "outputs": []},
]

w3     = Web3(Web3.HTTPProvider(RPC_URL))
pusd_c = w3.eth.contract(address=PUSD, abi=ERC20_ABI)
ctf_c  = w3.eth.contract(address=CTF,  abi=ERC1155_ABI)

erc20_targets = [
    ("CTF",             CTF),
    ("CTF Exchange V2", CTF_EX),
    ("NR Exchange V2",  NR_EX),
    ("NR Adapter",      NR_ADPT),
    ("CollateralOfframp", OFFRAMP),
]
erc1155_targets = [
    ("CTF Exchange V2", CTF_EX),
    ("NR Exchange V2",  NR_EX),
    ("NR Adapter",      NR_ADPT),
]

print(f"Deposit wallet : {DW}\n")
print("Current allowances (from deposit wallet):")
for label, addr in erc20_targets:
    val = pusd_c.functions.allowance(DW, addr).call()
    print(f"  pUSD → {label:<28}: {'✓' if val >= MAX_UINT256 else '✗'}")
for label, addr in erc1155_targets:
    ok = ctf_c.functions.isApprovedForAll(DW, addr).call()
    print(f"  CTF  → {label:<28}: {'✓' if ok else '✗'}")

# Build the batch — only include calls that aren't already approved
calls = []

for label, addr in erc20_targets:
    val = pusd_c.functions.allowance(DW, addr).call()
    if val < MAX_UINT256:
        data = pusd_c.encode_abi("approve", args=[addr, MAX_UINT256])
        calls.append(DepositWalletCall(target=PUSD, value="0", data=data))
        print(f"  → queuing pUSD approve → {label}")

for label, addr in erc1155_targets:
    ok = ctf_c.functions.isApprovedForAll(DW, addr).call()
    if not ok:
        data = ctf_c.encode_abi("setApprovalForAll", args=[addr, True])
        calls.append(DepositWalletCall(target=CTF, value="0", data=data))
        print(f"  → queuing CTF setApprovalForAll → {label}")

if not calls:
    print("\nAll allowances already set ✓")
    exit(0)

print(f"\nSubmitting WALLET batch with {len(calls)} approval(s)…")
relayer = make_relayer()
wallet_batch(relayer, DW, calls)
print(f"✓ {len(calls)} approval(s) confirmed from deposit wallet")
print("\nNext: run 5_init_clob.py to initialise the CLOB client")