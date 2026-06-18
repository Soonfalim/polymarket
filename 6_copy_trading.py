import os
import math  # Added for GCD precision matching
import asyncio
import websockets
import requests
import json
import httpx
from datetime import datetime
from decimal import Decimal, ROUND_DOWN  # Added for exact decimal manipulation
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
# Leaderboard wallets config
def generate_wallet_config(categories):
    target_wallets_config = {}

    print(f"Generating config dictionary for categories: {categories}\n")

    for category in categories:
        label = category.capitalize()
        json_source = f"{category}_wallets.json"

        try:
            with open(json_source, "r") as f:
                wallets = json.load(f)

            for wallet in wallets:
                wallet_clean = wallet.lower()

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

TARGET_WALLETS_CONFIG = generate_wallet_config(["CRYPTO", "WEATHER"])

TARGET_WALLETS = {k.lower(): [tag.lower() for tag in v] for k, v in TARGET_WALLETS_CONFIG.items()}

TRADE_MODE = "FIXED" 
FIXED_AMOUNT = 2.0
PERCENTAGE = 15.0

MAX_COPY_AMOUNT = 8.0

PRICE_MIN = 0.50
PRICE_MAX = 0.95

SLIPPAGE_TOLERANCE = 0.01

ENABLE_TAKE_PROFIT = False
ENABLE_STOP_LOSS = True

TP_PERCENTAGE = 0.90
SL_PERCENTAGE = 0.40

PAPER_TRADE = False

EXCLUDED_SLUGS = [
    "btc-updown-5m", "eth-updown-5m", "sol-updown-5m", "xrp-updown-5m", "doge-updown-5m", "hype-updown-5m", "bnb-updown-5m",
    "btc-updown-15m", "eth-updown-15m", "sol-updown-15m", "xrp-updown-15m", "doge-updown-15m", "hype-updown-15m", "bnb-updown-15m"
]

# ==========================================
# ENDPOINTS & PERSISTENT STATE STORAGE
# ==========================================

WSS_URL = "wss://ws-live-data.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com/events?slug="
POSITIONS_URL = "https://data-api.polymarket.com/positions"
CLOB_HOST = "https://clob.polymarket.com"
DB_FILE = "active_positions.json"  

event_cache = {}       
active_positions = {}  

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


async def update_positions():
    async with httpx.AsyncClient() as client:
        while True:
            params = {
                "user": os.getenv("DEPOSIT_WALLET"),
                "sizeThreshold": 0.1,  
                "limit": 500,
                "sortBy": "TOKENS",
                "sortDirection": "DESC"
            }
            
            try:
                response = await client.get(POSITIONS_URL, params=params)
                response.raise_for_status()
                positions = response.json()
                
                if not positions:
                    print(f"No current active positions found for wallet: {os.getenv('DEPOSIT_WALLET')}")
                    await asyncio.sleep(15)
                    continue
                
                for pos in positions:
                    size = float(pos.get("size", 0))
                    avg_price = float(pos.get("avgPrice", 0))
                    cur_price = float(pos.get("curPrice", 0))
                    asset = pos.get("asset")

                    if size <= 0 or cur_price <= 0:
                        continue

                    tp_price = min(0.99, round(avg_price * (1 + TP_PERCENTAGE), 2))
                    sl_price = max(0.01, round(avg_price * (1 - SL_PERCENTAGE), 2))

                    price_drop_pct = ((avg_price - cur_price) / avg_price) * 100 if avg_price > 0 else 0

                    if price_drop_pct >= (SL_PERCENTAGE * 100):
                        status_indicator = "🛑 STOP-LOSS HIT!"
                    elif price_drop_pct > 0:
                        status_indicator = "📉 IN LOSS"
                    else:
                        status_indicator = "📈 IN PROFIT"

                    print(f"[{status_indicator}] Token: {asset[:8]}... | "
                          f"Entry: {avg_price:.4f} | "
                          f"Now: {cur_price:.4f} | "
                          f"P/L: {-price_drop_pct:.2f}%")

                    active_positions[asset] = {
                        "cur_price": cur_price,
                        "size": size,
                        "entry_price": avg_price,
                        "total": size * avg_price,
                        "tp_price": tp_price,
                        "sl_price": sl_price,
                    }

                    if ENABLE_STOP_LOSS and price_drop_pct >= (SL_PERCENTAGE * 100):
                        await execute_stop_loss(asset, size, cur_price)
                
                for asset, data in list(active_positions.items()):
                    if float(data.get("size", 0)) <= 0:
                        active_positions.pop(asset, None)
                
                save_active_positions()

            except httpx.HTTPError as e:
                print(f"⚠️ Network error fetching positions: {e}")
            except Exception as e:
                print(f"⚠️ Unexpected error in update_positions: {e}")
            
            await asyncio.sleep(15)
        

def save_active_positions():
    """Commits current tracking configuration safely to disk."""
    try:
        with open(DB_FILE, "w") as f:
            json.dump(active_positions, f, indent=4)
    except Exception as e:
        print(f"⚠️ Database Error: Could not save positions to disk: {e}")


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
# PRECISION UTILITY (FOK COMPLIANCE)
# ==========================================
def calculate_clean_shares(price, target_usdc=None, max_available_shares=None):
    """
    Calculates the maximum safe share size (max 4 decimals) for an FOK order
    ensuring that (shares * price) yields a product with <= 2 decimal places.
    """
    price_cents = int(round(price * 100))
    if price_cents <= 0:
        return 0.0
        
    price_dec = Decimal(price_cents) / 100
    
    if target_usdc is not None:
        max_shares = (Decimal(str(target_usdc)) / price_dec).quantize(Decimal('0.0001'), rounding=ROUND_DOWN)
    elif max_available_shares is not None:
        max_shares = Decimal(str(max_available_shares)).quantize(Decimal('0.0001'), rounding=ROUND_DOWN)
    else:
        return 0.0
        
    S_max = int(max_shares * 10000)
    
    # FOK mathematical invariant check via GCD
    step = 10000 // math.gcd(price_cents, 10000)
    S = (S_max // step) * step
    
    return float(Decimal(S) / 10000)


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

    # CHANGED: Replaced crude round() with clean math.gcd FOK precision calculation
    trade_size_shares = calculate_clean_shares(price=my_price, target_usdc=trade_amount_usdc)

    print(f"🤖 EXECUTING: {my_side.name} {trade_size_shares} shares @ ${my_price}")
    
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
                    order_type=OrderType.FOK  
                )

                print(f"✅ Trade Response: {resp.get('success', False)} | {resp.get('errorID', '')}")
            else:
                print(f"✅ Trade Response: Successful!")
            
            await telegram_bot.send_message(
                chat_id=os.getenv("MY_CHAT_ID"), 
                text=f"Traded {my_side.name} {trade_size_shares} @ ${my_price}"
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


async def execute_stop_loss(token_id, size, current_price):
    """Closes the position by selling shares when stop-loss threshold is hit."""
    if not poly_client:
        return

    print("=" * 60)
    print(f"🚨 EXECUTING STOP LOSS: Selling {size:.2f} shares of {token_id}")
    print("=" * 60)

    # Price slightly below current to ensure Fill-Or-Kill execution acts like a market sell
    sell_price = max(0.01, round(current_price * (1 - SLIPPAGE_TOLERANCE), 2))
    
    # CHANGED: Clean the stop loss share size so the FOK close order doesn't cause a bad decimal error
    clean_size = calculate_clean_shares(price=sell_price, max_available_shares=size)

    if not PAPER_TRADE:
        try:
            resp = await asyncio.to_thread(
                poly_client.create_and_post_order,
                OrderArgs(
                    price=sell_price,
                    size=clean_size,
                    side=Side.SELL,
                    token_id=token_id
                ),
                options=PartialCreateOrderOptions(tick_size="0.01"),
                order_type=OrderType.FOK 
            )

            print(f"✅ SL Trade Response: {resp.get('success', False)} | Error: {resp.get('errorID', 'None')}")
            
            if resp.get('success'):
                await telegram_bot.send_message(
                    chat_id=os.getenv("MY_CHAT_ID"), 
                    text=f"🚨 <b>STOP-LOSS TRIGGERED</b>\n\nToken: <code>{token_id}</code>\nSold {clean_size:.4f} shares @ ~${sell_price:.2f}",
                    parse_mode="HTML"
                )
                
        except Exception as e:
            print(f"❌ Stop Loss Execution Failed: {e}")
    else:
        print(f"✅ [PAPER TRADE] Stop Loss successfully executed for {token_id}!")


async def setup_sl(token_id, sl_price, size):
    print(f"🛡️ Stop loss armed for {token_id[:8]}... (Monitoring loop active)")


async def send_heartbeat(websocket):
    while True:
        try:
            await websocket.send("PING")
            await asyncio.sleep(5)
        except:
            break


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
        print(f"🚀 Connected! Monitoring customized specialized wallets.")

        await telegram_bot.send_message(
            chat_id=os.getenv("MY_CHAT_ID"), 
            text=f"🚀 Copy trading initiated for configurated wallets!"
        )

        while True:
            try:
                message = await websocket.recv()
                
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

                combined_slug_string = f"{event_slug or ''} {market_slug or ''}".lower()
                if any(blacklisted in combined_slug_string for blacklisted in EXCLUDED_SLUGS):
                    continue

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
    await load_active_positions()
    
    await asyncio.gather(
        monitor_global_bets(),
        update_positions()
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")