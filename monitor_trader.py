#pip install websockets
import asyncio
import json
import websockets
from datetime import datetime

# ===================
# CONFIGURATION
# ===================
WALLETS_TO_TRACK = [
    "0xce25e214d5cfe4f459cf67f08df581885aae7fdc",
    #"0xba016b05c84c9f073e5c9059d247d37cea4b8535",
]

WSS_URL = "wss://ws-live-data.polymarket.com"

async def send_heartbeat(websocket):
    """Sends required ping to keep the websocket stream alive."""
    while True:
        try:
            await websocket.send(json.dumps({"action": "ping"}))
            await asyncio.sleep(10)
        except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
            break

async def monitor_target_wallets():
    while True:  # Outer loop handles reconnection automatically
        try:
            logging_info = f"Connected! Sifting through trades for {len(WALLETS_TO_TRACK)} target wallets..."
            
            async with websockets.connect(WSS_URL) as websocket:
                # Spawn background heartbeat task
                heartbeat_task = asyncio.create_task(send_heartbeat(websocket))
                
                # Subscribe to global activity/trades stream
                subscribe_msg = {
                    "action": "subscribe",
                    "subscriptions": [{"topic": "activity", "type": "trades"}]
                }
                await websocket.send(json.dumps(subscribe_msg))
                print(logging_info)

                try:
                    while True:
                        message = await websocket.recv()
                        if not message.strip().startswith('{'):
                            continue
                        
                        data = json.loads(message)
                        p = data.get("payload", {})
                        
                        # Extract the wallet address committing the trade
                        # Polymarket trades explicitly expose the proxy wallet address here
                        wallet = p.get("proxyWallet")
                        if not wallet:
                            continue
                            
                        wallet_lower = wallet.lower()

                        # Wallet Filtering
                        if wallet_lower in WALLETS_TO_TRACK:
                            user = p.get("pseudonym") or "Anonymous"
                            market = p.get("title", "Unknown Market")
                            side = p.get("side")
                            outcome = p.get("outcome")
                            price = float(p.get("price", 0))
                            size = float(p.get("size", 0))
                            total_value = price * size
                            timestamp = p.get("timestamp")

                            print("\n" + "=" * 50)
                            print(f"OCTO WALLET ACTIVITY DETECTED!")
                            print("=" * 50)
                            print(f"User: {user}")
                            print(f"Wallet: {wallet}")
                            print(f"Market: {market}")
                            print(f"Action: {side} {outcome} | Price: ${price:.2f}")
                            #print(f"Size: {size}")
                            #print(f"Total Bet Value: ${total_value:.2f}")
                            print(f"Tx Hash: https://polygonscan.com/tx/{p.get('transactionHash')}")
                            print(f"Timestamp: {datetime.fromtimestamp(timestamp)}")
                            print(f"Slug: {p.get('eventSlug')}")
                            print("-" * 50)

                except websockets.exceptions.ConnectionClosed:
                    print("⚠️ Connection closed by server. Attempting to reconnect...")
                finally:
                    # Make sure background heartbeat is cancelled upon disconnection
                    heartbeat_task.cancel()

        except Exception as e:
            print(f"❌ Connection Error: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        WALLETS_TO_TRACK = [addr.lower() for addr in WALLETS_TO_TRACK]
        asyncio.run(monitor_target_wallets())
    except KeyboardInterrupt:
        print("\nStopped by user.")