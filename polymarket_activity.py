import asyncio
import websockets
import json
import httpx
from datetime import datetime

WSS_URL = "wss://ws-live-data.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com/events?slug="

# Set your filter here (e.g., "Weather")
FILTER_TAG = "Sports"

# Cache to store slug -> tags mapping to avoid redundant API calls
slug_cache = {}

async def get_event_tags(client, slug):
    """Fetch tags for a specific event slug with local caching."""
    if slug in slug_cache:
        return slug_cache[slug]
    
    try:
        response = await client.get(f"{GAMMA_API_URL}{slug}", timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            # The API returns a list; we want the tags from the first match
            if data and isinstance(data, list):
                tags = [tag.get("label") for tag in data[0].get("tags", [])]
                slug_cache[slug] = tags
                return tags
    except Exception as e:
        print(f"⚠️ API Error fetching slug {slug}: {e}")
    
    return []

async def send_heartbeat(websocket):
    while True:
        try:
            await websocket.send(json.dumps({"action": "ping"}))
            await asyncio.sleep(10)
        except:
            break

async def monitor_global_bets():
    # Use httpx.AsyncClient for efficient async HTTP calls
    async with websockets.connect(WSS_URL) as websocket, httpx.AsyncClient() as client:
        asyncio.create_task(send_heartbeat(websocket))

        subscribe_msg = {
            "action": "subscribe",
            "subscriptions": [{"topic": "activity", "type": "trades"}]
        }
        
        await websocket.send(json.dumps(subscribe_msg))
        print(f"🚀 Connected! Filtering for: {FILTER_TAG if FILTER_TAG else 'All Trades'}")

        while True:
            try:
                message = await websocket.recv()
                if not message.strip().startswith('{'):
                    continue
                
                data = json.loads(message)
                p = data.get("payload", {})
                event_slug = p.get("eventSlug")

                # --- Logic for Filtering ---
                if FILTER_TAG != "":
                    if not event_slug:
                        continue
                    
                    tags = await get_event_tags(client, event_slug)
                    if FILTER_TAG not in tags:
                        continue # Skip this trade if the tag doesn't match

                # --- Formatting and Printing ---
                user = p.get("pseudonym") or "Anonymous"
                wallet = p.get("proxyWallet", "Unknown")
                market = p.get("title", "Unknown Market")
                side = p.get("side")
                outcome = p.get("outcome")
                price = float(p.get("price", 0))
                size = float(p.get("size", 0))
                total_value = price * size
                timestamp = p.get("timestamp")

                print(f"💰 New {FILTER_TAG} Bet by {user}")
                print(f"📈 Market: {market}")
                print(f"✨ Action: {side} {outcome} | Amount: ${total_value:.2f}")
                print(f"Wallet: {wallet}")
                print(f"Timestamp: {datetime.fromtimestamp(timestamp)}")
                print(f"Tx: {p.get('transactionHash')}")
                print(f"Slug: {event_slug}")
                print("-" * 50)

            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"⚠️ Connection Lost: {e}")
                break

if __name__ == "__main__":
    try:
        asyncio.run(monitor_global_bets())
    except KeyboardInterrupt:
        print("\nStopped by user.")