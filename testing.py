import os
import math
import asyncio
import websockets
import requests
import json
import httpx
import threading
import time
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv, set_key
import streamlit as st
import pandas as pd
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

# Set page configuration
st.set_page_config(page_title="Polymarket Copy Trader", page_icon="🤖", layout="wide")

# ==========================================
# GLOBAL STATE MANAGER (Cross-Thread Safe)
# ==========================================
class BotState:
    def __init__(self):
        self.is_running = False
        self.loop = None
        self.thread = None
        self.logs = []
        self.active_positions = {}
        self.event_cache = {}
        # Dynamic Configurations
        self.config = {
            "TRADE_MODE": "FIXED",
            "FIXED_AMOUNT": 2.0,
            "PERCENTAGE": 15.0,
            "MAX_COPY_AMOUNT": 8.0,
            "PRICE_MIN": 0.50,
            "PRICE_MAX": 0.95,
            "SLIPPAGE_TOLERANCE": 0.01,
            "ENABLE_TAKE_PROFIT": False,
            "ENABLE_STOP_LOSS": True,
            "TP_PERCENTAGE": 0.90,
            "SL_PERCENTAGE": 0.40,
            "PAPER_TRADE": False,
        }

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.logs.append(log_entry)
        if len(self.logs) > 100:  # Keep last 100 logs
            self.logs.pop(0)
        print(log_entry) # Also keep stdout logging

if "bot" not in st.shared_state if hasattr(st, "shared_state") else st.session_state:
    # Workaround for persistent global state across Streamlit reruns
    if "_global_bot_state" not in globals():
        globals()["_global_bot_state"] = BotState()
    bot_state = globals()["_global_bot_state"]
else:
    if "bot" not in st.session_state:
        st.session_state.bot = BotState()
    bot_state = st.session_state.bot

# Load static environment configurations
load_dotenv()
try:
    telegram_bot = Bot(token=os.getenv("BOT_TOKEN", "")) if os.getenv("BOT_TOKEN") else None
except Exception:
    telegram_bot = None

# Constants
WSS_URL = "wss://ws-live-data.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com/events?slug="
POSITIONS_URL = "https://data-api.polymarket.com/positions"
CLOB_HOST = "https://clob.polymarket.com"
DB_FILE = "active_positions.json"
EXCLUDED_SLUGS = [
    "btc-updown-5m", "eth-updown-5m", "sol-updown-5m", "xrp-updown-5m", "doge-updown-5m", "hype-updown-5m", "bnb-updown-5m",
    "btc-updown-15m", "eth-updown-15m", "sol-updown-15m", "xrp-updown-15m", "doge-updown-15m", "hype-updown-15m", "bnb-updown-15m"
]

# Wallet generation engine
def generate_wallet_config(categories):
    target_wallets_config = {}
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
            pass
    return target_wallets_config

TARGET_WALLETS_CONFIG = generate_wallet_config(["crypto", "weather"])
TARGET_WALLETS = {k.lower(): [tag.lower() for tag in v] for k, v in TARGET_WALLETS_CONFIG.items()}


# ==========================================
# REFACTORED TRADING UTILITIES & LOGIC
# ==========================================
def calculate_clean_shares(price, target_usdc=None, max_available_shares=None):
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
    step = 10000 // math.gcd(price_cents, 10000)
    S = (S_max // step) * step
    return float(Decimal(S) / 10000)

def save_active_positions():
    try:
        with open(DB_FILE, "w") as f:
            json.dump(bot_state.active_positions, f, indent=4)
    except Exception as e:
        bot_state.log(f"⚠️ Database Error: Could not save positions: {e}")

async def load_active_positions():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                bot_state.active_positions = json.load(f)
            bot_state.log(f"💾 Database: Loaded {len(bot_state.active_positions)} active position trackers.")
        except Exception as e:
            bot_state.log(f"⚠️ Database Error: Failed to parse storage file: {e}")

async def fetch_and_cache_gamma_data(client, event_slug):
    if event_slug in bot_state.event_cache:
        return bot_state.event_cache[event_slug]
    try:
        response = await client.get(f"{GAMMA_API_URL}{event_slug}", timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            if data and isinstance(data, list):
                tags = [tag.get("label", "").lower() for tag in data[0].get("tags", [])]
                bot_state.event_cache[event_slug] = tags
                return tags
    except Exception as e:
        bot_state.log(f"⚠️ API Error fetching data for slug {event_slug}: {e}")
    return []

# Dynamic initialized client wrapper
def get_poly_client():
    try:
        creds = ApiCreds(
            api_key=os.getenv("POLY_API_KEY", ""),
            api_secret=os.getenv("POLY_API_SECRET", ""),
            api_passphrase=os.getenv("POLY_API_PASSPHRASE", "")
        )
        return ClobClient(
            host=CLOB_HOST,
            key=os.getenv("EVM_PRIVATE", ""),
            chain_id=137,
            signature_type=3,
            funder=os.getenv("DEPOSIT_WALLET", ""),
            creds=creds
        )
    except Exception as e:
        bot_state.log(f"⚠️ Failed to init CLOB Client. Verify credentials: {e}")
        return None

async def execute_trade(token_id, leader_side, leader_price, leader_size):
    poly_client = get_poly_client()
    cfg = bot_state.config
    
    leader_value_usdc = leader_price * leader_size
    trade_amount_usdc = cfg["FIXED_AMOUNT"] if cfg["TRADE_MODE"] == "FIXED" else leader_value_usdc * (cfg["PERCENTAGE"] / 100.0)
    trade_amount_usdc = min(trade_amount_usdc, cfg["MAX_COPY_AMOUNT"])

    if leader_side == "BUY":
        my_side = Side.BUY
        my_price = min(0.99, round(leader_price * (1 + cfg["SLIPPAGE_TOLERANCE"]), 2))
    else:
        my_side = Side.SELL
        my_price = max(0.01, round(leader_price * (1 - cfg["SLIPPAGE_TOLERANCE"]), 2))

    trade_size_shares = calculate_clean_shares(price=my_price, target_usdc=trade_amount_usdc)
    bot_state.log(f"🤖 EXECUTING: {my_side.name} {trade_size_shares} shares @ ${my_price}")
    
    current_total = bot_state.active_positions.get(token_id, {}).get("total", 0.0)

    if current_total < 9:
        try:
            if not cfg["PAPER_TRADE"] and poly_client:
                resp = await asyncio.to_thread(
                    poly_client.create_and_post_order,
                    OrderArgs(price=my_price, size=trade_size_shares, side=my_side, token_id=token_id),
                    options=PartialCreateOrderOptions(tick_size="0.01"),
                    order_type=OrderType.FOK
                )
                bot_state.log(f"✅ Trade Response: {resp.get('success', False)} | {resp.get('errorID', '')}")
            else:
                bot_state.log(f"✅ [PAPER] Trade Mocked Successfully!")
            
            if telegram_bot:
                await telegram_bot.send_message(
                    chat_id=os.getenv("MY_CHAT_ID"), 
                    text=f"Traded {my_side.name} {trade_size_shares} @ ${my_price}"
                )

            # Update Positions mapping logic
            if token_id not in bot_state.active_positions:
                bot_state.active_positions[token_id] = {
                    "cur_price": leader_price, "size": trade_size_shares, "entry_price": my_price,
                    "total": trade_size_shares * my_price,
                    "tp_price": min(0.99, round(my_price * (1 + cfg["TP_PERCENTAGE"]), 2)),
                    "sl_price": max(0.01, round(my_price * (1 - cfg["SL_PERCENTAGE"]), 2)),
                }
            else:
                pos = bot_state.active_positions[token_id]
                new_size = pos["size"] + trade_size_shares
                new_entry = ((pos["size"] * pos["entry_price"]) + (trade_size_shares * my_price)) / new_size
                pos.update({
                    "cur_price": leader_price, "size": new_size, "entry_price": round(new_entry, 4), "total": new_size * new_entry,
                    "tp_price": min(0.99, round(new_entry * (1 + cfg["TP_PERCENTAGE"]), 2)),
                    "sl_price": max(0.01, round(new_entry * (1 - cfg["SL_PERCENTAGE"]), 2))
                })

            save_active_positions()
            if cfg["ENABLE_TAKE_PROFIT"] and my_side.name == "BUY" and poly_client:
                await setup_tp(poly_client, token_id, bot_state.active_positions[token_id]["tp_price"], trade_size_shares)

        except Exception as e:
            bot_state.log(f"❌ Execution Failed: {e}")
    else:
        bot_state.log("Cancelling trade order, limit for market reached!")

async def setup_tp(poly_client, token_id, tp_price, size):
    if not bot_state.config["PAPER_TRADE"]:
        try:
            await asyncio.to_thread(
                poly_client.create_and_post_order,
                OrderArgs(price=tp_price, size=size, side=Side.SELL, token_id=token_id),
                options=PartialCreateOrderOptions(tick_size="0.01"),
                order_type=OrderType.GTC
            )
            bot_state.log(f"✅ TP order placed at {tp_price}")
        except Exception as e:
            bot_state.log(f"❌ Failed to place TP order: {e}")

async def execute_stop_loss(token_id, size, current_price):
    poly_client = get_poly_client()
    bot_state.log(f"🚨 EXECUTING STOP LOSS: Selling {size:.2f} shares of {token_id}")
    sell_price = max(0.01, round(current_price * (1 - bot_state.config["SLIPPAGE_TOLERANCE"]), 2))
    clean_size = calculate_clean_shares(price=sell_price, max_available_shares=size)

    if not bot_state.config["PAPER_TRADE"] and poly_client:
        try:
            resp = await asyncio.to_thread(
                poly_client.create_and_post_order,
                OrderArgs(price=sell_price, size=clean_size, side=Side.SELL, token_id=token_id),
                options=PartialCreateOrderOptions(tick_size="0.01"),
                order_type=OrderType.FOK
            )
            if resp.get('success') and telegram_bot:
                await telegram_bot.send_message(
                    chat_id=os.getenv("MY_CHAT_ID"),
                    text=f"🚨 <b>STOP-LOSS TRIGGERED</b>\n\nSold {clean_size:.4f} shares @ ~${sell_price:.2f}",
                    parse_mode="HTML"
                )
        except Exception as e:
            bot_state.log(f"❌ Stop Loss Execution Failed: {e}")
    else:
        bot_state.log(f"✅ [PAPER] Stop Loss executed for {token_id}!")

async def update_positions_loop():
    async with httpx.AsyncClient() as client:
        while bot_state.is_running:
            wallet = os.getenv("DEPOSIT_WALLET")
            if not wallet:
                await asyncio.sleep(5)
                continue
            params = {"user": wallet, "sizeThreshold": 0.1, "limit": 500, "sortBy": "TOKENS", "sortDirection": "DESC"}
            try:
                response = await client.get(POSITIONS_URL, params=params)
                if response.status_code == 200:
                    positions = response.json()
                    for pos in positions:
                        size, avg_price, cur_price, asset = float(pos.get("size", 0)), float(pos.get("avgPrice", 0)), float(pos.get("curPrice", 0)), pos.get("asset")
                        if size <= 0 or cur_price <= 0: continue
                        
                        price_drop_pct = ((avg_price - cur_price) / avg_price) * 100 if avg_price > 0 else 0
                        
                        bot_state.active_positions[asset] = {
                            "cur_price": cur_price, "size": size, "entry_price": avg_price, "total": size * avg_price,
                            "tp_price": min(0.99, round(avg_price * (1 + bot_state.config["TP_PERCENTAGE"]), 2)),
                            "sl_price": max(0.01, round(avg_price * (1 - bot_state.config["SL_PERCENTAGE"]), 2)),
                        }
                        if bot_state.config["ENABLE_STOP_LOSS"] and price_drop_pct >= (bot_state.config["SL_PERCENTAGE"] * 100):
                            await execute_stop_loss(asset, size, cur_price)
                    
                    for asset in list(bot_state.active_positions.keys()):
                        if not any(p.get("asset") == asset for p in positions):
                            bot_state.active_positions.pop(asset, None)
                    save_active_positions()
            except Exception as e:
                bot_state.log(f"⚠️ Error updating loop positions: {e}")
            await asyncio.sleep(15)

async def monitor_global_bets_loop():
    if not TARGET_WALLETS:
        bot_state.log("⚠️ No targeting configuration found. Check JSON files.")
        return
    while bot_state.is_running:
        try:
            async with websockets.connect(WSS_URL) as websocket, httpx.AsyncClient() as client:
                await websocket.send(json.dumps({"action": "subscribe", "subscriptions": [{"topic": "activity", "type": "trades"}]}))
                bot_state.log("🚀 Realtime Websocket Listening...")
                while bot_state.is_running:
                    message = await websocket.recv()
                    data = json.loads(message)
                    p = data.get("payload", {})
                    if not p: continue
                    
                    wallet, pseudonym = p.get("proxyWallet", "").lower(), p.get("pseudonym", "").lower()
                    event_slug, market_slug, token_id = p.get("eventSlug"), p.get("slug"), p.get("asset")
                    price, size, side = float(p.get("price", 0)), float(p.get("size", 0)), p.get("side", "").upper()
                    
                    combined_slug = f"{event_slug or ''} {market_slug or ''}".lower()
                    if any(b in combined_slug for b in EXCLUDED_SLUGS): continue
                    
                    assigned_categories = TARGET_WALLETS.get(wallet) or TARGET_WALLETS.get(pseudonym)
                    if assigned_categories is None or not event_slug: continue
                    
                    event_tags = await fetch_and_cache_gamma_data(client, event_slug)
                    if not any(tag in assigned_categories for tag in event_tags): continue
                    if bot_state.config["PRICE_MIN"] and price < bot_state.config["PRICE_MIN"]: continue
                    if bot_state.config["PRICE_MAX"] and price > bot_state.config["PRICE_MAX"]: continue
                    
                    bot_state.log(f"🎯 MATCHED: {wallet or pseudonym} -> {side} {price}")
                    asyncio.create_task(execute_trade(token_id, side, price, size))
        except Exception as e:
            bot_state.log(f"⚠️ Socket broken, reconnecting: {e}")
            await asyncio.sleep(5)

# Thread execution orchestration
def start_async_loop():
    loop = asyncio.new_event_loop()
    bot_state.loop = loop
    asyncio.set_event_loop(loop)
    loop.run_until_complete(load_active_positions())
    loop.gather(monitor_global_bets_loop(), update_positions_loop())
    loop.run_forever()

def start_bot():
    if not bot_state.is_running:
        bot_state.is_running = True
        bot_state.thread = threading.Thread(target=start_async_loop, daemon=True)
        bot_state.thread.start()
        bot_state.log("⚡ Copy Trader Engine Activated.")

def stop_bot():
    if bot_state.is_running:
        bot_state.is_running = False
        if bot_state.loop:
            bot_state.loop.call_soon_threadsafe(bot_state.loop.stop)
        bot_state.log("🛑 Copy Trader Engine Deactivated Safely.")


# ==========================================
# STREAMLIT USER INTERFACE LAYOUT
# ==========================================
st.title("🤖 Polymarket Copy-Trading Center")
st.markdown("Monitor and control your wallet mirror replication algorithms instantly.")

# --- SIDEBAR CONTROL PANEL ---
with st.sidebar:
    st.header("🎛️ Engine Controller")
    
    # Start/Stop Buttons
    if bot_state.is_running:
        st.error("Bot Status: ACTIVE")
        if st.button("Stop Trading Engine", use_container_width=True):
            stop_bot()
            st.rerun()
    else:
        st.warning("Bot Status: OFFLINE")
        if st.button("Start Trading Engine", use_container_width=True, type="primary"):
            start_bot()
            st.rerun()

    st.markdown("---")
    st.header("🔑 Environment Setup")
    
    # Allow safe runtime configuration editing of .env values
    with st.expander("Edit API/Wallet Credentials"):
        pk = st.text_input("EVM Private Key", value=os.getenv("EVM_PRIVATE", ""), type="password")
        dw = st.text_input("Deposit Wallet Address", value=os.getenv("DEPOSIT_WALLET", ""))
        tk = st.text_input("Telegram Bot Token", value=os.getenv("BOT_TOKEN", ""), type="password")
        cid = st.text_input("Telegram Chat ID", value=os.getenv("MY_CHAT_ID", ""))
        
        if st.button("Save Credentials", use_container_width=True):
            set_key(".env", "EVM_PRIVATE", pk)
            set_key(".env", "DEPOSIT_WALLET", dw)
            set_key(".env", "BOT_TOKEN", tk)
            set_key(".env", "MY_CHAT_ID", cid)
            st.success("Saved! Restart bot to apply changes.")

# --- MAIN DASHBOARD INTERFACE ---
tab1, tab2, tab3 = st.tabs(["📊 Live Status Hub", "⚙️ Dynamic Configs", "📋 Target Database"])

with tab1:
    # Stat Cards
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Monitored Wallets Connected", len(TARGET_WALLETS))
    m2.metric("Active Tracked Positions", len(bot_state.active_positions))
    m3.metric("Execution Mode", bot_state.config["TRADE_MODE"])
    m4.metric("Risk Guarding", "Simulated (Paper)" if bot_state.config["PAPER_TRADE"] else "Production Live")

    st.subheader("📈 Live Open Positions Tracker")
    if bot_state.active_positions:
        # Format dictionary matrix into pandas display
        df = pd.DataFrame.from_dict(bot_state.active_positions, orient='index')
        df.index.name = 'Token Asset Contract Address'
        df = df.reset_index()
        # Prettify display metrics
        df['PnL %'] = ((df['cur_price'] - df['entry_price']) / df['entry_price'] * 100).round(2)
        st.dataframe(df.style.map(
            lambda v: 'color: #00cc66;' if v > 0 else 'color: #ff3333;', subset=['PnL %']
        ), use_container_width=True)
    else:
        st.info("No active open positions currently found on smart contract tracking ledger.")

    # Live Logger Feed
    st.subheader("📜 Real-Time Console Feed")
    log_text = "\n".join(bot_state.logs[::-1])  # Show newest on top
    st.text_area("Console logs", value=log_text, height=250, label_visibility="collapsed")
    
    # Auto-refresh helper button
    if st.button("🔄 Force Interface Redraw"):
        st.rerun()

with tab2:
    st.subheader("🛡️ Algorithmic Target Parameters")
    st.markdown("Modify execution parameters dynamically. Changes apply to the next trade instantly.")
    
    c1, c2 = st.columns(2)
    with c1:
        bot_state.config["PAPER_TRADE"] = st.checkbox("Enable Paper Trading (Mock Fills)", value=bot_state.config["PAPER_TRADE"])
        bot_state.config["TRADE_MODE"] = st.radio("Sizing Model Strategy", ["FIXED", "PERCENTAGE"], index=0 if bot_state.config["TRADE_MODE"] == "FIXED" else 1)
        bot_state.config["FIXED_AMOUNT"] = st.number_input("Fixed Order Allocation Size ($ USDC)", min_value=1.0, value=float(bot_state.config["FIXED_AMOUNT"]))
        bot_state.config["PERCENTAGE"] = st.slider("Percentage Mirror Scale Factor (%)", 1.0, 100.0, float(bot_state.config["PERCENTAGE"]))
        bot_state.config["MAX_COPY_AMOUNT"] = st.number_input("Absolute Capital Cap Limit Per Trade ($ USDC)", min_value=1.0, value=float(bot_state.config["MAX_COPY_AMOUNT"]))
    
    with c2:
        bot_state.config["PRICE_MIN"] = st.slider("Minimum Floor Execution Price ($)", 0.01, 0.99, float(bot_state.config["PRICE_MIN"]))
        bot_state.config["PRICE_MAX"] = st.slider("Maximum Ceiling Execution Price ($)", 0.01, 0.99, float(bot_state.config["PRICE_MAX"]))
        bot_state.config["SLIPPAGE_TOLERANCE"] = st.slider("Slippage Execution Buffer (%)", 0.005, 0.05, float(bot_state.config["SLIPPAGE_TOLERANCE"]), step=0.005)
        
        st.markdown("---")
        bot_state.config["ENABLE_TAKE_PROFIT"] = st.checkbox("Automate Limit Take-Profit Offers", value=bot_state.config["ENABLE_TAKE_PROFIT"])
        bot_state.config["TP_PERCENTAGE"] = st.slider("Take Profit Capture Target (%)", 0.1, 3.0, float(bot_state.config["TP_PERCENTAGE"]))
        bot_state.config["ENABLE_STOP_LOSS"] = st.checkbox("Automate Monitoring Loop Stop-Loss Orders", value=bot_state.config["ENABLE_STOP_LOSS"])
        bot_state.config["SL_PERCENTAGE"] = st.slider("Stop Loss Max Threshold Breach (%)", 0.05, 0.95, float(bot_state.config["SL_PERCENTAGE"]))

with tab3:
    st.subheader("📋 Targeted Smart Contract Identity Ledger")
    st.markdown("These identities are mapped based on target settings configured inside local `.json` category structures.")
    
    if TARGET_WALLETS:
        wallet_display_data = [{"Address/Identity": wallet, "Subscribed Channels": ", ".join(tags).upper()} for wallet, tags in TARGET_WALLETS.items()]
        st.table(pd.DataFrame(wallet_display_data))
    else:
        st.error("No tracked categories parsed successfully. Check that `crypto_wallets.json` or `weather_wallets.json` files are present in the directory execution root.")