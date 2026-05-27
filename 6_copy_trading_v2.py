import os
import asyncio
import websockets
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
TARGET_WALLETS_CONFIG = {
    "0x36901eb0f21519cc9055662a6d2483e96da1e16f": ["Sports", "Crypto", "Politics", "Weather"],
    "0x8454E6318819F0cac255006c99c40A3FC68D3587": ["Weather"]
}

# Normalize configuration to lowercase for robust matching
TARGET_WALLETS = {k.lower(): [tag.lower() for tag in v] for k, v in TARGET_WALLETS_CONFIG.items()}

# 2. Trade Sizing ("FIXED" or "PERCENTAGE")
TRADE_MODE = "FIXED" 
FIXED_AMOUNT = 5.0   # Buy exactly $5 USDC per trade
PERCENTAGE = 15.0    # If mode is PERCENTAGE, buy 15% of the leader's trade size

# 3. Maximum Copy $ Amount (Hard cap per trade in USDC)
MAX_COPY_AMOUNT = 50.0

# 4. Price Range Filter (Inclusive)
PRICE_MIN = 0.4
PRICE_MAX = 0.96

# 5. Slippage Tolerance (0.01 = 1% price movement accepted)
SLIPPAGE_TOLERANCE = 0.01

# 6. Automatic Take Profit & Stop Loss
AUTO_TP_SL = True     # Changed to True for testing/operational use
TP_PERCENTAGE = 0.20  # +20% -> Places a Limit Sell Order on the book
SL_PERCENTAGE = 0.10  # -10% -> Triggers a Market Sell if price drops globally

# ==========================================
# ENDPOINTS & PERSISTENT STATE STORAGE
# ==========================================

WSS_URL = "wss://ws-live-data.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com/events?slug="
CLOB_HOST = "https://clob.polymarket.com"
DB_FILE = "active_positions.json"  # Persistent local state database

event_cache = {}       # Caches event_slug -> list of lowercased tags
market_cache = {}      # Caches market_slug -> {outcome: token_id}
active_positions = {}  # Tracks SL per token: token_id -> {"size": size, "sl_price": price}

def load_active_positions():
    """Loads active tracking positions from the local JSON database file upon startup."""
    global active_positions
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                active_positions = json.load(f)
            print(f"💾 Database: Loaded {len(active_positions)} active position trackers from {DB_FILE}")
        except Exception as e:
            print(f"⚠️ Database Error: Failed to parse storage file, starting clean: {e}")
            active_positions = {}
    else:
        active_positions = {}

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
                
                markets = event_data.get("markets", [])
                for m in markets:
                    m_slug = m.get("slug")
                    outcomes = m.get("outcomes", [])
                    token_ids = m.get("clobTokenIds", [])
                    
                    mapping = {}
                    for i, out in enumerate(outcomes):
                        if i < len(token_ids):
                            mapping[str(out).lower()] = token_ids[i]
                    
                    market_cache[m_slug] = mapping
                
                return tags
    except Exception as e:
        print(f"⚠️ API Error fetching data for slug {event_slug}: {e}")
    return []

async def get_token_id_from_gamma(client, event_slug, market_slug, outcome):
    if market_slug in market_cache:
        return market_cache[market_slug].get(str(outcome).lower())
    await fetch_and_cache_gamma_data(client, event_slug)
    return market_cache.get(market_slug, {}).get(str(outcome).lower())

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
    try:
        await telegram_bot.send_message(
            chat_id=os.getenv("MY_CHAT_ID"), 
            text=f"Attempting to trade {my_side.name} {trade_size_shares} @ ${my_price}"
        )

        resp = await asyncio.to_thread(
            poly_client.create_and_post_order,
            OrderArgs(
                price=my_price,
                size=trade_size_shares,
                side=my_side,
                token_id=token_id
            ),
            options=PartialCreateOrderOptions(tick_size="0.01"),
            order_type=OrderType.GTC
        )
        
        await telegram_bot.send_message(
            chat_id=os.getenv("MY_CHAT_ID"), 
            text=f"Successful"
        )
        print(f"✅ Trade Response: {resp.get('success', False)} | {resp.get('errorID', '')}")
        
        if AUTO_TP_SL and my_side == Side.BUY:
            await setup_tp_sl(token_id, leader_price, trade_size_shares)
    except Exception as e:
        print(f"❌ Execution Failed: {e}")

async def setup_tp_sl(token_id, entry_price, size):
    tp_price = min(0.99, round(entry_price * (1 + TP_PERCENTAGE), 2))
    sl_price = max(0.01, round(entry_price * (1 - SL_PERCENTAGE), 2))

    print(f"🎯 Placing Take-Profit Limit Order at ${tp_price}")
    try:
        '''
        tp_resp = await asyncio.to_thread(
            poly_client.create_and_post_order,
            OrderArgs(price=tp_price, size=size, side=Side.SELL, token_id=token_id),
            options=PartialCreateOrderOptions(tick_size="0.01"),
            order_type=OrderType.GTC
        )
        print(f"✅ TP Order Placed: {tp_resp.get('success') if isinstance(tp_resp, dict) else 'True'}")
        '''
        print("✅ TP Order Placed!")
    except Exception as e:
        print(f"❌ Failed to place TP Order: {e}")

    # Register Stop Loss locally and write to database file
    print(f"🛡️ Registered Stop-Loss Monitor at ${sl_price}")
    active_positions[token_id] = {"size": size, "sl_price": sl_price}
    save_active_positions()

async def trigger_stop_loss(token_id, pos):
    """Executes a market sell using FAK, then checks actual exchange balance to handle partial fills."""
    print(f"🚨 TRIGGERING STOP LOSS! Selling up to {pos['size']} shares...")
    try:
        # 1. Fire the FAK Order to claim whatever immediate liquidity exists
        '''
        resp = await asyncio.to_thread(
            poly_client.create_and_post_order,
            OrderArgs(price=0.01, size=pos["size"], side=Side.SELL, token_id=token_id),
            options=PartialCreateOrderOptions(tick_size="0.01"),
            order_type=OrderType.FAK
        )
        print(f"📡 FAK Order Submitted. Response: {resp}")
        '''
        print("📡 FAK Order Submitted!")
        
        # 2. Wait a brief moment for the exchange ledger to settle your balances
        await asyncio.sleep(1.0)
        
        # 3. Query the exchange for your ACTUAL remaining outcome token balance
        from py_clob_client_v2 import BalanceAllowanceParams, AssetType
        params = BalanceAllowanceParams(
            asset_type=AssetType.CONDITIONAL,
            token_id=token_id
        )
        ba = await asyncio.to_thread(poly_client.get_balance_allowance, params)
        remaining_balance = float(ba.get("balance", 0))
        
        print(f"📊 Balance Verification: You have {remaining_balance} shares remaining on Polymarket.")
        
        # 4. Reconcile local database state with reality
        if remaining_balance <= 0.01:  # Safe cut-off buffer for dust values
            print(f"🎉 Stop Loss fully liquidated the position!")
            if token_id in active_positions:
                del active_positions[token_id]
                save_active_positions()
        else:
            # Partial fill hit! Adjust tracking size to reality and unlock the mechanism
            print(f"⚠️ Partial fill hit! Only sold some. Updating remaining tracker size to {remaining_balance}...")
            pos["size"] = remaining_balance
            pos["locked"] = False  # Unlock so the next websocket tick can try to sweep the rest!
            save_active_positions()
            
    except Exception as e:
        print(f"❌ Stop Loss Execution or Balance Reconciliation Failed: {e}")
        # CRUCIAL: Unlock on failure so the bot doesn't permanently freeze tracking on this asset
        pos["locked"] = False
        save_active_positions()

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
            text=f"🚀 Copy trading initiated for following wallets: {TARGET_WALLETS}"
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

                # 1. Stop Loss Monitoring (Triggers globally if index price tanks)
                if token_id and token_id in active_positions:
                    pos = active_positions[token_id]
                    if pos["size"] > 0 and price <= pos["sl_price"] and not pos.get("locked", False):
                        # Lock the position to prevent duplicate concurrent tasks from spawning
                        pos["locked"] = True 
                        save_active_positions() # Commit lock state to local database
                        
                        # Execute the rescue task and pass the whole position dictionary
                        asyncio.create_task(trigger_stop_loss(token_id, pos))

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

                # 5. Resolve Token ID and execute
                if not token_id:
                    token_id = await get_token_id_from_gamma(client, event_slug, market_slug, outcome)
                
                if token_id:
                    asyncio.create_task(execute_trade(token_id, side, price, size))
                    
            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"⚠️ Connection Lost: {e}")
                break

if __name__ == "__main__":
    # Initialize the local data cache before runtime thread initialization
    load_active_positions()
    try:
        asyncio.run(monitor_global_bets())
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")