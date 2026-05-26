import os
import sys
import time
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

# Step 1: Request your unique EVM deposit address from the Bridge API
print("[1/3] Requesting tracking deposit address from Polymarket Bridge...")
bridge_url = "https://bridge.polymarket.com/deposit"

payload = {"address": DW}
headers = {"Content-Type": "application/json"}

# Inject your builder code if available to clear the API warning
if BUILDER_CODE:
    headers["X-Builder-Code"] = BUILDER_CODE

try:
    response = requests.post(bridge_url, json=payload, headers=headers)
    response.raise_for_status()
    data = response.json()
    
    # FIX: The API key is 'address' singular, not 'addresses'
    evm_deposit_address = data.get("address", {}).get("evm")
    
    if not evm_deposit_address:
        print(f"Unexpected API response structure: {data}")
        sys.exit(1)
        
    print(f"  ✓ SUCCESS! Target EVM Address: {evm_deposit_address}")
    print("-" * 50)
    
except Exception as e:
    print(f"✕ Failed to fetch deposit address from Bridge API: {e}")
    if hasattr(e, 'response') and e.response is not None:
        print(f"Status Code: {e.response.status_code} | Response: {e.response.text}")
    sys.exit(1)

# Step 2: Inform the user to send the funds
print("[2/3] ACTION REQUIRED:")
print(f"  --> MANUALLY SEND YOUR 10 USDC TO: {evm_deposit_address}")
print("  --> Ensure you use a supported EVM chain like Polygon.")
print("-" * 50)

input("Press ENTER once you have sent the transaction to start tracking the status... ")

# Step 3: Monitor the tracking pipeline until it arrives
print("\n[3/3] Monitoring deposit status pipeline (Ctrl+C to exit and check manually later)...")
status_url = f"https://bridge.polymarket.com/status/{DW}"

while True:
    try:
        status_resp = requests.get(status_url, headers=headers)
        if status_resp.status_code == 200:
            status_data = status_resp.json()
            
            print(f"\rCurrent Bridge Status: {status_data.get('status', 'PENDING')}...", end="")
            
            if status_data.get("status") == "SUCCESS" or status_data.get("pUSD_credited"):
                print("\n\n✓ SUCCESS! Polymarket has wrapped your USDC. Check your balance script now!")
                break
        else:
            print(f"\r[Waiting for transaction to register on indexer...]", end="")
            
    except Exception:
        pass 
        
    time.sleep(10)