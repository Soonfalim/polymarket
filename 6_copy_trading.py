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

# 1. Target Wallets (You can add multiple)
target_wallet_env = os.getenv("TARGET_WALLET", "").lower()
TARGET_WALLETS = [target_wallet_env] if target_wallet_env else []
# You can manually append more here: TARGET_WALLETS.append("0xAnotherWallet".lower())

# 2. Trade Sizing ("FIXED" or "PERCENTAGE")
TRADE_MODE = "FIXED" 
FIXED_AMOUNT = 5.0  # Buy exactly $10 USDC per trade
PERCENTAGE = 15.0    # If mode is PERCENTAGE, buy 50% of the leader's trade size

# 3. Maximum Copy $ Amount (Hard cap per trade in USDC)
MAX_COPY_AMOUNT = 50.0

# 4. Price Range Filter (Inclusive)
# Set to None to accept any price
PRICE_MIN = 0.4
PRICE_MAX = 0.96

# 5. Slippage Tolerance (0.05 = 5% price movement accepted)
SLIPPAGE_TOLERANCE = 0.01

# 6. Automatic Take Profit & Stop Loss
AUTO_TP_SL = False
TP_PERCENTAGE = 0.20  # +20% -> Places a Limit Sell Order on the book
SL_PERCENTAGE = 0.10  # -10% -> Triggers a Market Sell if price drops globally

# ==========================================
# ENDPOINTS & STATE
# ==========================================

WSS_URL = "wss://ws-live-data.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com/events?slug="
CLOB_HOST = "https://clob.polymarket.com"

market_cache = {}      # Caches Gamma API token IDs
active_positions = {}  # Tracks SL per token: token_id -> {"size": size, "sl_price": price}

# Initialize CLOB Client (Deposit Wallet Flow / Signature Type 3)
try:
    creds = ApiCreds(
        api_key=os.getenv("POLY_API_KEY", ""),
        api_secret=os.getenv("POLY_API_SECRET", ""),
        api_passphrase=os.getenv("POLY_API_PASSPHRASE", "")
    )
    poly_client = ClobClient(
        host=CLOB_HOST,
        key=os.getenv("EVM_PRIVATE", ""),
        chain_id=137, # Polygon Mainnet
        signature_type=3, # Deposit Wallet L1 Auth
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

async def get_token_id_from_gamma(client, event_slug, market_slug, outcome):
    """Fetches the exact token_id for 'Yes' or 'No' from the Gamma API."""
    if market_slug in market_cache:
        return market_cache[market_slug].get(str(outcome).lower())

    try:
        response = await client.get(f"{GAMMA_API_URL}{event_slug}", timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            if data and isinstance(data, list):
                markets = data[0].get("markets", [])
                for m in markets:
                    m_slug = m.get("slug")
                    outcomes = m.get("outcomes", [])
                    token_ids = m.get("clobTokenIds", [])
                    
                    mapping = {}
                    for i, out in enumerate(outcomes):
                        if i < len(token_ids):
                            mapping[str(out).lower()] = token_ids[i]
                    
                    market_cache[m_slug] = mapping
                
                if market_slug in market_cache:
                    return market_cache[market_slug].get(str(outcome).lower())
    except Exception as e:
        print(f"⚠️ API Error fetching slug {event_slug}: {e}")
    
    return None

async def execute_trade(token_id, leader_side, leader_price, leader_size):
    """Calculates sizes, applies slippage, and executes the copy trade."""
    if not poly_client:
        return

    # 1. Determine USDC trade size
    leader_value_usdc = leader_price * leader_size
    
    if TRADE_MODE == "FIXED":
        trade_amount_usdc = FIXED_AMOUNT
    else:
        trade_amount_usdc = leader_value_usdc * (PERCENTAGE / 100.0)
        
    trade_amount_usdc = min(trade_amount_usdc, MAX_COPY_AMOUNT)

    # 2. Apply Slippage Tolerance
    if leader_side == "BUY":
        my_side = Side.BUY
        my_price = min(0.99, round(leader_price * (1 + SLIPPAGE_TOLERANCE), 2))
    else:
        my_side = Side.SELL
        my_price = max(0.01, round(leader_price * (1 - SLIPPAGE_TOLERANCE), 2))

    # 3. Convert USDC amount to # of shares
    trade_size_shares = round(trade_amount_usdc / my_price, 2)
    
    if trade_size_shares <= 0:
        return

    print(f"🤖 EXECUTING: {my_side.name} {trade_size_shares} shares @ ${my_price}")
    await telegram_bot.send_message(
        chat_id=os.getenv("MY_CHAT_ID"), 
        text=f"Attempting to trade {my_side.name} {trade_size_shares} @ ${my_price}"
    )

    # 4. Place Order via CLOB (Running in thread to prevent blocking async loop)
    try:
        '''
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
        print(f"✅ Trade Response: {resp.get('success', False)} | {resp.get('errorID', '')}")
        '''
        await telegram_bot.send_message(
            chat_id=os.getenv("MY_CHAT_ID"), 
            text=f"Successful"
        )
        print(f"✅ Trade Response: SUCCESS!")
        
        # 5. Handle Take Profit / Stop Loss (Only on BUY)
        if AUTO_TP_SL and my_side == Side.BUY:# and resp.get("success"):
            await setup_tp_sl(token_id, leader_price, trade_size_shares)

    except Exception as e:
        print(f"❌ Execution Failed: {e}")

async def setup_tp_sl(token_id, entry_price, size):
    """Sets a Limit Sell for Take Profit, and tracks Stop Loss in memory."""
    tp_price = min(0.99, round(entry_price * (1 + TP_PERCENTAGE), 2))
    sl_price = max(0.01, round(entry_price * (1 - SL_PERCENTAGE), 2))

    print(f"🎯 Placing Take-Profit Limit Order at ${tp_price}")
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
        print(f"✅ TP Order Placed: {tp_resp.get('success')}")
    except Exception as e:
        print(f"❌ Failed to place TP Order: {e}")

    # Register Stop Loss for websocket monitoring
    print(f"🛡️ Registered Stop-Loss Monitor at ${sl_price}")
    active_positions[token_id] = {"size": size, "sl_price": sl_price}

async def trigger_stop_loss(token_id, size):
    """Executes a market sell if the global price dips below Stop Loss."""
    print(f"🚨 TRIGGERING STOP LOSS! Selling {size} shares...")
    try:
        # Selling at 1c essentially acts as a market FOK/FAK order
        resp = await asyncio.to_thread(
            poly_client.create_and_post_order,
            OrderArgs(
                price=0.01,
                size=size,
                side=Side.SELL,
                token_id=token_id
            ),
            options=PartialCreateOrderOptions(tick_size="0.01"),
            order_type=OrderType.FOK
        )
        print(f"✅ Stop Loss Executed: {resp.get('success')}")
    except Exception as e:
        print(f"❌ Stop Loss Failed: {e}")

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
        print("⚠️ No TARGET_WALLETS set! Please configure in .env")
        return

    async with websockets.connect(WSS_URL) as websocket, httpx.AsyncClient() as client:
        asyncio.create_task(send_heartbeat(websocket))

        subscribe_msg = {
            "action": "subscribe",
            "subscriptions": [{"topic": "activity", "type": "trades"}]
        }
        await websocket.send(json.dumps(subscribe_msg))
        print(f"🚀 Connected! Listening to trades for: {TARGET_WALLETS}")
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

                # 1. Stop Loss Monitoring (Triggers on ANY user's trade that drives price down)
                if token_id and token_id in active_positions:
                    pos = active_positions[token_id]
                    if pos["size"] > 0 and price <= pos["sl_price"]:
                        asyncio.create_task(trigger_stop_loss(token_id, pos["size"]))
                        pos["size"] = 0 # Mark as sold to prevent double trigger

                # 2. Target Wallet Filter
                if wallet not in TARGET_WALLETS and pseudonym not in TARGET_WALLETS:
                    continue

                # 3. Price Filter Check
                if PRICE_MIN is not None and price < PRICE_MIN:
                    continue
                if PRICE_MAX is not None and price > PRICE_MAX:
                    continue

                print("-" * 50)
                print(f"🎯 TARGET TRADE DETECTED: {wallet}")
                print(f"📈 Market: {p.get('title', market_slug)}")
                print(f"✨ Action: {side} {outcome} @ ${price} (Size: {size})")

                # 4. Resolve Token ID and execute
                if not token_id:
                    token_id = await get_token_id_from_gamma(client, event_slug, market_slug, outcome)
                
                if token_id:
                    asyncio.create_task(execute_trade(token_id, side, price, size))
                else:
                    print("⚠️ Could not resolve token_id for trade.")
                    
            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"⚠️ Connection Lost: {e}")
                break

if __name__ == "__main__":
    try:
        asyncio.run(monitor_global_bets())
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")