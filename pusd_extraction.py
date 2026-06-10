'''
Only certain chains and tokens are supported. See /supported-assets for details
'''
import os
import time
import sys
import requests
from dotenv import load_dotenv
from web3 import Web3
from py_builder_relayer_client.client import RelayClient
from py_builder_relayer_client.models import DepositWalletCall, TransactionType
from py_builder_signing_sdk.config import BuilderApiKeyCreds, BuilderConfig

load_dotenv()

DEPOSIT_WALLET = os.getenv("DEPOSIT_WALLET")
BUILDER_CODE = os.getenv("BUILDER_CODE")

if not DEPOSIT_WALLET:
    raise SystemExit("DEPOSIT_WALLET is not set in your .env file.")

PUSD_TOKEN_ADDRESS = Web3.to_checksum_address("0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB")
NATIVE_USDC_ADDRESS = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
DW = Web3.to_checksum_address(DEPOSIT_WALLET)
RECIPIENT = Web3.to_checksum_address("0xba2175aa786cF9cDdD46461EDDa708e620aB279A")

POLYGON_RPC_URL = "http://127.0.0.1:8545"
w3 = Web3(Web3.HTTPProvider(POLYGON_RPC_URL))

print(f"Your Polymarket Wallet: {DW}")
print("-" * 50)

# Helper functions to build and execute the relayer batch from your reference code
def make_relayer() -> RelayClient:
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
    nonce_payload = relayer.get_nonce(
        relayer.signer.address(),
        TransactionType.WALLET.value,
    )
    nonce    = str(nonce_payload["nonce"])
    deadline = str(int(time.time()) + 3600)

    response = relayer.execute_deposit_wallet_batch(
        calls=calls,
        wallet_address=deposit_wallet,
        nonce=nonce,
        deadline=deadline,
    )
    return response.wait()

# ===============================================================
# Step 1: Request your withdrawal address from the Bridge API
# ===============================================================
print("Requesting tracking deposit address from Polymarket Bridge...")
bridge_url = "https://bridge.polymarket.com/withdraw"

payload = {"address": DW,
           "toChainId": "137",
           "toTokenAddress": NATIVE_USDC_ADDRESS,
           "recipientAddr": RECIPIENT
}
headers = {"Content-Type": "application/json"}

# Inject your builder code if available to clear the API warning
if BUILDER_CODE:
    headers["X-Builder-Code"] = BUILDER_CODE

try:
    response = requests.post(bridge_url, json=payload, headers=headers)
    response.raise_for_status()
    data = response.json()
    print(data)
    
    # FIX: The API key is 'address' singular, not 'addresses'
    evm_deposit_address = data.get("address", {}).get("evm")
    svm_deposit_address = data.get("address", {}).get("svm")
    tron_deposit_address = data.get("address", {}).get("tron")
    btc_deposit_address = data.get("address", {}).get("btc")
    
    if not evm_deposit_address or not svm_deposit_address or not tron_deposit_address or not btc_deposit_address:
        print(f"Unexpected API response structure: {data}")
        sys.exit(1)
        
    print(f"  SUCCESS! OBTAINED WITHDRAWAL ADDRESSES")
    print(f"  Target EVM Address : {evm_deposit_address}")
    print(f"  Target SVM Address : {svm_deposit_address}")
    print(f"  Target TRON Address: {tron_deposit_address}")
    print(f"  Target BTC Address : {btc_deposit_address}")
    print("-" * 50)
    
except Exception as e:
    print(f"✕ Failed to fetch withdrawal address from Bridge API: {e}")
    if hasattr(e, 'response') and e.response is not None:
        print(f"Status Code: {e.response.status_code} | Response: {e.response.text}")
    sys.exit(1)

# =====================================================================
# Step 2: Queue the pUSD transfer using the Relayer Client format
# =====================================================================
AMOUNT_TO_WITHDRAW = 10.0  # Amount of pUSD to extract
amount_atoms = int(AMOUNT_TO_WITHDRAW * 10**6)

print(f"Queuing transfer of {AMOUNT_TO_WITHDRAW} pUSD to the bridge...")

# Minimal ABI for transfer
PUSD_TRANSFER_ABI = [
    {"name": "transfer", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "recipient", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]}
]

pusd_contract = w3.eth.contract(address=PUSD_TOKEN_ADDRESS, abi=PUSD_TRANSFER_ABI)

# FIX: Force the dynamic bridge destination address to be strictly checksummed (Mixed-Case)
clean_bridge_address = Web3.to_checksum_address(evm_deposit_address)

# Encode calldata using the properly checksummed address
transfer_data = pusd_contract.encode_abi("transfer", args=[clean_bridge_address, amount_atoms])

# Build the execution call pointing directly to the pUSD contract
calls = [DepositWalletCall(target=PUSD_TOKEN_ADDRESS, value="0", data=transfer_data)]

print(f"Submitting WALLET batch to release funds...")
relayer = make_relayer()
wallet_batch(relayer, DW, calls)
print("✓ pUSD successfully extracted from the deposit wallet via the bridge!")