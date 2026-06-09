'''
Only certain chains and tokens are supported. See /supported-assets for details
'''
import os
import sys
import requests
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

DEPOSIT_WALLET = os.getenv("DEPOSIT_WALLET")
BUILDER_CODE = os.getenv("BUILDER_CODE")

if not DEPOSIT_WALLET:
    raise SystemExit("DEPOSIT_WALLET is not set in your .env file.")

DW = Web3.to_checksum_address(DEPOSIT_WALLET)

print(f"Your Polymarket Wallet: {DW}")
print("-" * 50)

# Step 1: Request your withdrawal address from the Bridge API
print("Requesting tracking deposit address from Polymarket Bridge...")
bridge_url = "https://bridge.polymarket.com/withdraw"

payload = {"address": DW,
           "toChainId": "137",
           "toTokenAddress": Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"),
           "recipientAddr": "0xba2175aa786cF9cDdD46461EDDa708e620aB279A"
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
        
    print(f"  SUCCESS!")
    print(f"  Target EVM Address : {evm_deposit_address}")
    print(f"  Target SVM Address : {svm_deposit_address}")
    print(f"  Target TRON Address: {tron_deposit_address}")
    print(f"  Target BTC Address : {btc_deposit_address}")
    print("-" * 50)
    
except Exception as e:
    print(f"✕ Failed to fetch deposit address from Bridge API: {e}")
    if hasattr(e, 'response') and e.response is not None:
        print(f"Status Code: {e.response.status_code} | Response: {e.response.text}")
    sys.exit(1)