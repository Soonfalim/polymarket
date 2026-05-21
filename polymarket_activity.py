import requests
import pandas as pd
from datetime import datetime
import time
from collections import deque

import asyncio
import websockets
import json

# ====================
# Test case 1 (Slow Update API)
# ====================
'''
API_URL = "https://data-api.polymarket.com/trades"

# Maximum number of transaction hashes to remember
WINDOW_SIZE = 5000

# Poll interval in seconds
POLL_INTERVAL = 5

# Sliding window storage
seen_hashes = set()
hash_queue = deque()

def add_hash(tx_hash):
    """
    Add transaction hash to sliding window.
    Remove oldest if window exceeds limit.
    """

    if tx_hash in seen_hashes:
        return False

    seen_hashes.add(tx_hash)
    hash_queue.append(tx_hash)

    # Remove oldest hashes if limit exceeded
    while len(hash_queue) > WINDOW_SIZE:
        old_hash = hash_queue.popleft()
        seen_hashes.remove(old_hash)

    return True

def fetch_trades():
    try:
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()

        return response.json()

    except Exception as e:
        print(f"[ERROR] {e}")
        return []

print("Listening for new Polymarket trades...\n")

while True:
    trades = fetch_trades()

    # Optional:
    # Reverse if API returns newest first
    # so older trades print before newer ones
    trades.reverse()

    for trade in trades:
        tx_hash = trade.get("transactionHash")

        if not tx_hash:
            continue

        # Only process unseen transactions
        if add_hash(tx_hash):

            print("=" * 50)
            print("NEW TRADE DETECTED")
            print("=" * 50)

            print(f"Market: {trade.get('title')}")
            print(f"Price: {trade.get('price')}")
            print(f"Side: {trade.get('side')}")
            print(f"Size: {trade.get('size')}")
            print(f"Timestamp: {trade.get('timestamp')}")
            print(f"Tx Hash: {tx_hash}")

            print()

    time.sleep(POLL_INTERVAL)
'''

# ====================
# Test case 2 (WSS but fast)
# ====================
import asyncio
import websockets
import json
import httpx  # Recommended for async requests: pip install httpx
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