import os
import asyncio
import websockets
import requests
import json
import httpx
from datetime import datetime
from dotenv import load_dotenv
from telegram import Bot

# Polymarket CLOB Client v2
from py_clob_client_v2 import (
    ClobClient,
    OrderArgs,
    OrderType,
    PartialCreateOrderOptions,
    Side,
    ApiCreds
)

load_dotenv()
telegram_bot = Bot(token=os.getenv("BOT_TOKEN"))

# ==========================================
# COPY TRADER CONFIGURATION
# ==========================================

# 1. Target Wallets & Categories Mapping
# Custom wallets config
"""TARGET_WALLETS_CONFIG = {
    "0x36901eb0f21519cc9055662a6d2483e96da1e16f": ["Sports", "Crypto", "Politics"],
    "0x81f80ba4769f17d270f0585ea546f2ed942e8ba9": ["Weather"],
    "0xba016b05c84c9f073e5c9059d247d37cea4b8535": ["Crypto"],
}"""

# Leaderboard wallets config
def generate_wallet_config(categories):
    target_wallets_config = {}

    print(f"Generating config dictionary for categories: {categories}\n")

    for category in categories:
        # Standardize the label case (e.g., 'crypto' -> 'Crypto')
        label = category.capitalize()
        json_source = f"{category}_wallets.json"

        try:
            with open(json_source, "r") as f:
                wallets = json.load(f)

            for wallet in wallets:
                # Lowercase the address to ensure standard consistency
                wallet_clean = wallet.lower()

                # If the wallet somehow exists in an already loaded category, append the new label
                if wallet_clean in target_wallets_config:
                    if label not in target_wallets_config[wallet_clean]:
                        target_wallets_config[wallet_clean].append(label)
                else:
                    target_wallets_config[wallet_clean] = [label]

        except FileNotFoundError:
            print(
                f"Warning: Local data file '{json_source}' not found. Skipping {label}..."
            )

    return target_wallets_config

TARGET_WALLETS_CONFIG = generate_wallet_config(["CRYPTO", "WEATHER", "SPORTS"])

# Normalize configuration to lowercase for robust matching
TARGET_WALLETS = {k.lower(): [tag.lower() for tag in v] for k, v in TARGET_WALLETS_CONFIG.items()}

# 2. Trade Sizing ("FIXED" or "PERCENTAGE")
TRADE_MODE = "FIXED" 
FIXED_AMOUNT = 4.0   # Buy exactly 4 USD per trade
PERCENTAGE = 15.0    # If mode is PERCENTAGE, buy 15% of the leader's trade size

# 3. Maximum Copy $ Amount (Hard cap per trade in pUSD)
MAX_COPY_AMOUNT = 13.0

# 4. Price Range Filter (Inclusive)
PRICE_MIN = 0.45
PRICE_MAX = 0.96

# 5. Slippage Tolerance (0.01 = 1% price movement accepted)
SLIPPAGE_TOLERANCE = 0.01

# 6. Automatic Take Profit & Stop Loss
ENABLE_TAKE_PROFIT = False
ENABLE_STOP_LOSS = False

TP_PERCENTAGE = 0.90     # 20% gain
SL_PERCENTAGE = 0.50     # 10% loss

PAPER_TRADE = True

# ==========================================
# ENDPOINTS & PERSISTENT STATE STORAGE
# ==========================================

WSS_URL = "wss://ws-live-data.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com/events?slug="
POSITIONS_URL = "https://data-api.polymarket.com/positions"
CLOB_HOST = "https://clob.polymarket.com"
DB_FILE = "active_positions.json"  # Persistent local state database

event_cache = {}       # Caches event_slug -> list of lowercased tags
active_positions = {}  # Tracks SL per token: token_id -> {"size": size, "sl_price": price}

async def load_active_positions():
    """Loads active tracking positions from the local JSON database file upon startup."""
    global active_positions
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                active_positions = json.load(f)
            print(f"💾 Database: Loaded {len(active_positions)} active position trackers from {DB_FILE}")
        except Exception as e:
            print(f"⚠️ Database Error: Failed to parse storage file, starting clean: {e}")
    
    async with httpx.AsyncClient() as client:
        while True:
            # Query parameters based on the API specification
            params = {
                "user": os.getenv("DEPOSIT_WALLET"),
                "sizeThreshold": 1,       # Only show positions with a meaningful size
                "limit": 500,             # Number of positions to return per request (max 500)
                "sortBy": "TOKENS",
                "sortDirection": "DESC"
            }
            
            try:
                response = await client.get(POSITIONS_URL, params=params)
                response.raise_for_status()
                positions = response.json()
                
                if not positions:
                    print(f"No current active positions found for wallet: {os.getenv('DEPOSIT_WALLET')}")
                    continue
                
                for pos in positions:
                    #title = pos.get("title", "Unknown Market")
                    #outcome = pos.get("outcome", "N/A")
                    size = pos.get("size", 0)
                    avg_price = pos.get("avgPrice", 0)
                    cur_price = pos.get("curPrice", 0)
                    #current_value = pos.get("currentValue", 0)
                    #pnl = pos.get("cashPnl", 0)
                    #pnl_percent = pos.get("percentPnl", 0)
                    asset = pos.get("asset")

                    tp_price = min(0.99, round(avg_price * (1 + TP_PERCENTAGE), 2))
                    sl_price = max(0.01, round(avg_price * (1 - SL_PERCENTAGE), 2))

                    position_data = {
                        "cur_price": cur_price,
                        "size": size,
                        "entry_price": avg_price,
                        "total": size * avg_price,
                        "tp_price": tp_price,
                        "sl_price": sl_price,
                    }

                    active_positions[asset] = position_data
                
                for asset, data in list(active_positions.items()):
                    cur_price = data.get("cur_price", 0)
                    
                    # If both current price and entry price are 0 or less, remove the asset tracker
                    if cur_price <= 0 or size <= 0:
                        active_positions.pop(asset, None)
                
                save_active_positions()

            except requests.exceptions.RequestException as e:
                print(f"Error fetching positions: {e}")
            
            await asyncio.sleep(15)
        

def save_active_positions():
    """Commits current tracking configuration safely to disk."""
    try:
        with open(DB_FILE, "w") as f:
            json.dump(active_positions, f, indent=4)
    except Exception as e:
        print(f"⚠️ Database Error: Could not save positions to disk: {e}")

# Initialize CLOB Client
try:
    creds = ApiCreds(
        api_key=os.getenv("POLY_API_KEY", ""),
        api_secret=os.getenv("POLY_API_SECRET", ""),
        api_passphrase=os.getenv("POLY_API_PASSPHRASE", "")
    )
    poly_client = ClobClient(
        host=CLOB_HOST,
        key=os.getenv("EVM_PRIVATE", ""),
        chain_id=137, 
        signature_type=3, 
        funder=os.getenv("DEPOSIT_WALLET", ""),
        creds=creds
    )
    print("✅ Polymarket CLOB Client Initialized.")
except Exception as e:
    print(f"⚠️ Failed to init CLOB Client. Check your .env keys: {e}")
    poly_client = None

# ==========================================
# CORE FUNCTIONS
# ==========================================

async def fetch_and_cache_gamma_data(client, event_slug):
    """Single API call to fetch tags and token mappings for an event slug."""
    if event_slug in event_cache:
        return event_cache[event_slug]

    try:
        response = await client.get(f"{GAMMA_API_URL}{event_slug}", timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            if data and isinstance(data, list):
                event_data = data[0]
                
                tags = [tag.get("label", "").lower() for tag in event_data.get("tags", [])]
                event_cache[event_slug] = tags
                
                return tags
    except Exception as e:
        print(f"⚠️ API Error fetching data for slug {event_slug}: {e}")
    return []

async def execute_trade(token_id, leader_side, leader_price, leader_size):
    if not poly_client:
        return

    leader_value_usdc = leader_price * leader_size
    trade_amount_usdc = FIXED_AMOUNT if TRADE_MODE == "FIXED" else leader_value_usdc * (PERCENTAGE / 100.0)
    trade_amount_usdc = min(trade_amount_usdc, MAX_COPY_AMOUNT)

    if leader_side == "BUY":
        my_side = Side.BUY
        my_price = min(0.99, round(leader_price * (1 + SLIPPAGE_TOLERANCE), 2))
    else:
        my_side = Side.SELL
        my_price = max(0.01, round(leader_price * (1 - SLIPPAGE_TOLERANCE), 2))

    trade_size_shares = round(trade_amount_usdc / my_price, 2)
    if trade_size_shares <= 0:
        return

    print(f"🤖 EXECUTING: {my_side.name} {trade_size_shares} shares @ ${my_price}")

    await telegram_bot.send_message(
            chat_id=os.getenv("MY_CHAT_ID"), 
            text=f"Attempting to trade {my_side.name} {trade_size_shares} @ ${my_price}"
        )
    
    current_total = active_positions.get(token_id, {}).get("total", 0.0)

    if current_total < 9:
        try:
            if not PAPER_TRADE:
                resp = await asyncio.to_thread(
                    poly_client.create_and_post_order,
                    OrderArgs(
                        price=my_price,
                        size=trade_size_shares,
                        side=my_side,
                        token_id=token_id
                    ),
                    options=PartialCreateOrderOptions(tick_size="0.01"),
                    order_type=OrderType.FOK  # Changed from OrderType.GTC
                )

                print(f"✅ Trade Response: {resp.get('success', False)} | {resp.get('errorID', '')}")
            else:
                print(f"✅ Trade Response: Successful!")
            
            await telegram_bot.send_message(
                chat_id=os.getenv("MY_CHAT_ID"), 
                text=f"Successful"
            )

            if token_id not in active_positions:
                tp_price = min(0.99, round(my_price * (1 + TP_PERCENTAGE), 2))
                sl_price = max(0.01, round(my_price * (1 - SL_PERCENTAGE), 2))

                active_positions[token_id] = {
                    "cur_price": leader_price,
                    "size": trade_size_shares,
                    "entry_price": my_price,
                    "total": trade_size_shares * my_price,
                    "tp_price": tp_price,
                    "sl_price": sl_price,
                }
            else:
                old_size = active_positions[token_id]["size"]
                old_entry = active_positions[token_id]["entry_price"]
                
                new_size = old_size + trade_size_shares
                new_entry_price = ((old_size * old_entry) + (trade_size_shares * my_price)) / new_size

                active_positions[token_id]["cur_price"] = leader_price
                active_positions[token_id]["size"] = new_size
                active_positions[token_id]["entry_price"] = round(new_entry_price, 4)
                active_positions[token_id]["total"] = new_size * new_entry_price
                active_positions[token_id]["tp_price"] = min(0.99, round(new_entry_price * (1 + TP_PERCENTAGE), 2))
                active_positions[token_id]["sl_price"] = max(0.01, round(new_entry_price * (1 - SL_PERCENTAGE), 2))

            save_active_positions()
            
            if ENABLE_TAKE_PROFIT and my_side.name == "BUY":
                await setup_tp(token_id, active_positions[token_id]["tp_price"], trade_size_shares)
            if ENABLE_STOP_LOSS and my_side.name == "BUY":
                await setup_sl(token_id, active_positions[token_id]["sl_price"], trade_size_shares)

        except Exception as e:
            print(f"❌ Execution Failed: {e}")
    else:
        print("Cancelling trade order, limit for market reached!")

async def setup_tp(token_id, tp_price, size):
    # ==========================================
    # TAKE PROFIT
    # ==========================================
    if not PAPER_TRADE:
        try:
            tp_resp = await asyncio.to_thread(
                poly_client.create_and_post_order,
                OrderArgs(
                    price=tp_price,
                    size=size,
                    side=Side.SELL,
                    token_id=token_id
                ),
                options=PartialCreateOrderOptions(tick_size="0.01"),
                order_type=OrderType.GTC
            )

            print(f"✅ TP order placed at {tp_price}: {tp_resp.get('success', False)}")

        except Exception as e:
            print(f"❌ Failed to place TP order: {e}")
    else:
        print(f"✅ TP order placed at {tp_price}")

async def setup_sl(token_id, sl_price, size):
    # ==========================================
    # STOP LOSS REGISTRATION
    # ==========================================
    print(f"🛡️ Stop loss armed")


async def send_heartbeat(websocket):
    while True:
        try:
            await websocket.send(json.dumps({"action": "ping"}))
            await asyncio.sleep(10)
        except:
            break

# ==========================================
# WEBSOCKET LISTENER LOOP
# ==========================================

async def monitor_global_bets():
    if not TARGET_WALLETS:
        print("⚠️ No TARGET_WALLETS configured!")
        return

    async with websockets.connect(WSS_URL) as websocket, httpx.AsyncClient() as client:
        asyncio.create_task(send_heartbeat(websocket))

        subscribe_msg = {
            "action": "subscribe",
            "subscriptions": [{"topic": "activity", "type": "trades"}]
        }
        await websocket.send(json.dumps(subscribe_msg))
        print(f"🚀 Connected! Monitoring customized specialized wallets. (DB active updates armed)")

        await telegram_bot.send_message(
            chat_id=os.getenv("MY_CHAT_ID"), 
            text=f"🚀 Copy trading initiated for configurated wallets!"
        )

        while True:
            try:
                message = await websocket.recv()
                if not message.strip().startswith('{'):
                    continue
                
                data = json.loads(message)
                p = data.get("payload", {})
                if not p:
                    continue

                wallet = p.get("proxyWallet", "Unknown").lower()
                pseudonym = p.get("pseudonym", "").lower()
                event_slug = p.get("eventSlug")
                market_slug = p.get("slug")
                outcome = p.get("outcome")
                price = float(p.get("price", 0))
                size = float(p.get("size", 0))
                side = p.get("side", "").upper()
                token_id = p.get("asset")

                # 2. Target Wallet Filter Verification
                assigned_categories = None
                matched_identity = None

                if wallet in TARGET_WALLETS:
                    assigned_categories = TARGET_WALLETS[wallet]
                    matched_identity = wallet
                elif pseudonym in TARGET_WALLETS:
                    assigned_categories = TARGET_WALLETS[pseudonym]
                    matched_identity = pseudonym

                if assigned_categories is None:
                    continue

                # 3. Category/Tag Matching Check
                if not event_slug:
                    continue
                
                event_tags = await fetch_and_cache_gamma_data(client, event_slug)
                has_matching_category = any(tag in assigned_categories for tag in event_tags)
                if not has_matching_category:
                    continue

                # 4. Price Filter Check
                if PRICE_MIN is not None and price < PRICE_MIN:
                    continue
                if PRICE_MAX is not None and price > PRICE_MAX:
                    continue

                print("-" * 50)
                print(f"🎯 TARGET TRADE DETECTED: {matched_identity}")
                print(f"📈 Market: {p.get('title', market_slug)}")
                print(f"⚡ Action: {side} {outcome} @ ${price} (Size: {size})")

                asyncio.create_task(execute_trade(token_id, side, price, size))
                    
            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"⚠️ Connection Lost: {e}")
                continue

async def main():
    # Run both your websocket listener and background tracker concurrently!
    await asyncio.gather(
        monitor_global_bets(),
        load_active_positions()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")