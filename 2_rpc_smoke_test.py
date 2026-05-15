"""
1_rpc.py — RPC smoke test: EOA USDC.e balance + deposit wallet pUSD balance.

Run:
    python 1_rpc.py

Requires: PRIVATE_KEY in .env. Set DEPOSIT_WALLET after running 2_deploy_wallet.py.
The deposit wallet holds pUSD. EOA holds USDC.e for funding. No MATIC needed —
the relayer pays all gas.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
from web3 import Web3

# Load the variables from .env into the environment
load_dotenv()


PRIVATE_KEY    = os.getenv("EVM_PRIVATE")
DEPOSIT_WALLET = os.getenv("DEPOSIT_WALLET", "")
RPC_URL        = os.getenv("POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com")
CLOB_HOST      = os.getenv("CLOB_V2_BASE_URL", "https://clob.polymarket.com")
CHAIN_ID    = int(os.environ.get("CHAIN_ID", "137"))

PUSD   = Web3.to_checksum_address("0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB")
USDC_E = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")

ERC20_ABI = [
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "account", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
]

pk  = PRIVATE_KEY if PRIVATE_KEY.startswith("0x") else "0x" + PRIVATE_KEY
w3  = Web3(Web3.HTTPProvider(RPC_URL))
EOA = w3.eth.account.from_key(pk).address

pusd_c = w3.eth.contract(address=PUSD,   abi=ERC20_ABI)
usdc_c = w3.eth.contract(address=USDC_E, abi=ERC20_ABI)

print(f"EOA  : {EOA}")
print(f"CLOB : {CLOB_HOST}")
print(f"Chain: {CHAIN_ID}  {'(Polygon ✓)' if CHAIN_ID == 137 else '⚠ expected 137'}\n")

matic    = w3.eth.get_balance(EOA)
usdc_eoa = usdc_c.functions.balanceOf(EOA).call()
pusd_eoa = pusd_c.functions.balanceOf(EOA).call()

print(f"MATIC  (EOA) : {matic    / 1e18:.6f}  (relayer pays gas — not required for trading)")
print(f"USDC.e (EOA) : {usdc_eoa / 1e6:.6f}  {'← fund for 3_wrap.py' if usdc_eoa > 0 else '⚠ deposit USDC.e to EOA for funding'}")
print(f"pUSD   (EOA) : {pusd_eoa / 1e6:.6f}")

if DEPOSIT_WALLET:
    DW      = Web3.to_checksum_address(DEPOSIT_WALLET)
    pusd_dw = pusd_c.functions.balanceOf(DW).call()
    print(f"\nDeposit Wallet : {DW}")
    print(f"pUSD (wallet)  : {pusd_dw / 1e6:.6f}  {'✓' if pusd_dw > 0 else '⚠ run 3_wrap.py to fund'}")
else:
    print("\nDEPOSIT_WALLET not set in .env — run 2_deploy_wallet.py first")

print("\nRPC smoke test complete ✓")