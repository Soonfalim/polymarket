import os
from dotenv import load_dotenv

# Load the variables from .env into the environment
load_dotenv()

# ======================================
# Polling API Method
# ======================================
'''
import time
import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs

# --- CONFIGURATION ---
TARGET_WALLET = "0x004d9b64e8bac1cb0ad8b6c7a97a4969d83b2b95".lower()
COPY_RATIO = 0.1  # If they buy $100, you buy $10
POLL_INTERVAL = 2 # Seconds to wait between checks

# Your API Credentials (generated from the previous step)
host = "https://clob.polymarket.com"
key = "YOUR_PRIVATE_KEY" # CREATE ACC FIRST
creds = {
    "api_key": "YOUR_KEY",
    "api_secret": "YOUR_SECRET",
    "api_passphrase": "YOUR_PASSPHRASE"
}

# Initialize your trading client
client = ClobClient(host, key=key, chain_id=137)
client.set_api_creds(creds)

def get_target_activity():
    url = f"https://data-api.polymarket.com/activity?user={TARGET_WALLET}&type=TRADE&limit=5"
    response = requests.get(url).json()
    return response

def execute_copy_trade(trade):
    # Extract details from the target's trade
    market_id = trade['marketId']
    side = trade['side'] # 'BUY' or 'SELL'
    outcome = trade['outcome'] # 'Yes' or 'No'
    target_size = float(trade['size'])
    
    my_size = target_size * COPY_RATIO
    
    print(f"Target just {side} {outcome} on {market_id}. Copying with size: {my_size}")
    
    # Place a Market Order (FOK - Fill or Kill is safest for copy trading)
    try:
        # Note: You need the token_id for the specific outcome
        # You can fetch this using client.get_market(market_id)
        # For brevity, this assumes you have the token_id
        resp = client.create_order(OrderArgs(
            price=0.99 if side == 'BUY' else 0.01, # Use a limit price or market order logic
            size=my_size,
            side=side,
            token_id=trade['tokenId']
        ))
        print("Trade Executed:", resp)
    except Exception as e:
        print("Failed to execute copy trade:", e)

# --- MAIN LOOP ---
last_trade_id = None

while True:
    try:
        activity = get_target_activity()
        if activity:
            latest_trade = activity[0]
            current_id = latest_trade['id']
            
            if last_trade_id is None:
                last_trade_id = current_id
                print(f"Monitoring {TARGET_WALLET}...")
            
            if current_id != last_trade_id:
                execute_copy_trade(latest_trade)
                last_trade_id = current_id
                
    except Exception as e:
        print("Error in loop:", e)
    
    time.sleep(POLL_INTERVAL)
'''


# ======================================
# Websocket Method
# ======================================
import asyncio
import json
import os
import websockets
from py_clob_client_v2 import ClobClient, SignatureTypeV2
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import OrderArgs, OrderType
from py_clob_client_v2.order_builder.constants import BUY, SELL

# --- CONFIGURATION ---
TARGET_WALLET = "0xdc5cb48aa552995edb952bf2b0434df01e20808a".lower()
COPY_RATIO = 0.1
MAX_SLIPPAGE = 0.01
MY_WALLET_ADDRESS = os.getenv("DEPOSIT_WALLET") # REQUIRED for Type 3 wallets

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
PRIVATE_KEY = os.getenv("EVM_PRIVATE")

# 1. Initialize the client
# If using a standard EOA/MetaMask private key for a new account, use POLY_1271
client = ClobClient(
    HOST, 
    key=PRIVATE_KEY, 
    chain_id=CHAIN_ID,
    signature_type=SignatureTypeV2.POLY_1271, 
    funder=MY_WALLET_ADDRESS
)

# 2. Corrected method name for API credentials
api_creds = client.create_or_derive_api_key()
client.set_api_creds(api_creds)

async def execute_copy_trade(payload):
    try:
        token_id = payload.get("asset") 
        side = payload.get("side").upper() 
        target_price = float(payload.get("price"))
        target_size = float(payload.get("size"))
        
        my_size = round(target_size * COPY_RATIO, 2)
        
        if side == "BUY":
            limit_price = round(target_price * (1 + MAX_SLIPPAGE), 2)
        else:
            limit_price = round(target_price * (1 - MAX_SLIPPAGE), 2)

        print(f"🎯 Whale move detected! Attempting {side} for {token_id}")

        # The V2 client method for one-step trading
        resp = client.create_and_post_order(
            OrderArgs(
                token_id=token_id,
                price=limit_price,
                size=my_size,
                side=side,
            ),
            order_type=OrderType.FOK 
        )

        print(f"✅ Order Response: {resp}")

    except Exception as e:
        print(f"❌ Execution Error: {e}")

async def listen_to_whale():
    ws_url = "wss://ws-live-data.polymarket.com"
    
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({
            "action": "subscribe",
            "subscriptions": [{"topic": "activity", "type": "trades"}]
        }))
        
        print(f"📡 Bot Live. Monitoring: {TARGET_WALLET}")

        async for message in ws:
            if not message: continue
            try:
                data = json.loads(message)
                # The activity stream often returns a dictionary with 'payload'
                payload = data.get("payload", {})
                
                # Check proxyWallet or maker/taker addresses
                if payload.get("proxyWallet", "").lower() == TARGET_WALLET:
                    await execute_copy_trade(payload)

            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"❌ Processing Error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(listen_to_whale())
    except KeyboardInterrupt:
        print("Bot stopped.")