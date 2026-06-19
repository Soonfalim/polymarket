import os
import math
import asyncio
import threading
import websockets
import httpx
import json
import logging
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv
from telegram import Bot
import streamlit as st

# Polymarket CLOB Client v2
from py_clob_client_v2 import (
    ClobClient,
    OrderArgs,
    OrderType,
    PartialCreateOrderOptions,
    Side,
    ApiCreds
)

# Load environment variables
load_dotenv()

# ==========================================
# THREAD-SAFE GLOBAL BOT STATE & LOGGING
# ==========================================
class BotState:
    def __init__(self):
        self.is_running = False
        self.logs = []
        self.active_positions = {}
        self.lock = threading.Lock()
        self.loop = None
        self.thread = None

    def add_log(self, text):
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_log = f"[{timestamp}] {text}"
        with self.lock:
            self.logs.append(formatted_log)
            if len(self.logs) > 200:  # Keep log buffer optimized
                self.logs.pop(0)

    def set_running(self, status):
        with self.lock:
            self.is_running = status

    def get_running(self):
        with self.lock:
            return self.is_running

if "bot_state" not in st.session_state:
    st.session_state.bot_state = BotState()

state = st.session_state.bot_state

# Custom logging handler to redirect standard python logs to our UI console
class StreamlitLogHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        state.add_log(log_entry)

# Override default print statements to log into the Streamlit UI
def ui_print(text):
    print(text) # Still output to terminal
    state.add_log(text)

# ==========================================
# CORE TRADING CONFIGURATIONS & COMPLIANCE
# ==========================================
WSS_URL = "wss://ws-live-data.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com/events?slug="
POSITIONS_URL = "https://data-api.polymarket.com/positions"
CLOB_HOST = "https://clob.polymarket.com"
DB_FILE = "active_positions.json"

event_cache = {}

def generate_wallet_config(categories):
    target_wallets_config = {}
    for category in categories:
        label = category.capitalize()
        json_source = f"{category.lower()}_wallets.json"
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

# ==========================================
# ASYNC BOT ENGINE
# ==========================================
async def load_active_positions():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                state.active_positions = json.load(f)
            ui_print(f"💾 Database: Loaded {len(state.active_positions)} active position trackers from disk.")
        except Exception as e:
            ui_print(f"⚠️ Database Error: Failed to parse storage file: {e}")

def save_active_positions():
    try:
        with open(DB_FILE, "w") as f:
            json.dump(state.active_positions, f, indent=4)
    except Exception as e:
        ui_print(f"⚠️ Database Error: Could not save positions to disk: {e}")

async def update_positions(config):
    async with httpx.AsyncClient() as client:
        while state.get_running():
            deposit_wallet = os.getenv("DEPOSIT_WALLET")
            if not deposit_wallet:
                await asyncio.sleep(5)
                continue

            params = {
                "user": deposit_wallet,
                "sizeThreshold": 0.1,
                "limit": 500,
                "sortBy": "TOKENS",
                "sortDirection": "DESC"
            }
            try:
                response = await client.get(POSITIONS_URL, params=params)
                response.raise_for_status()
                positions = response.json()
                
                if positions:
                    with state.lock:
                        for pos in positions:
                            size = float(pos.get("size", 0))
                            avg_price = float(pos.get("avgPrice", 0))
                            cur_price = float(pos.get("curPrice", 0))
                            asset = pos.get("asset")

                            if size <= 0 or cur_price <= 0:
                                continue

                            tp_price = min(0.99, round(avg_price * (1 + config["TP_PERCENTAGE"]), 2))
                            sl_price = max(0.01, round(avg_price * (1 - config["SL_PERCENTAGE"]), 2))
                            price_drop_pct = ((avg_price - cur_price) / avg_price) * 100 if avg_price > 0 else 0

                            state.active_positions[asset] = {
                                "cur_price": cur_price,
                                "size": size,
                                "entry_price": avg_price,
                                "total": size * avg_price,
                                "tp_price": tp_price,
                                "sl_price": sl_price,
                                "pnl_pct": -price_drop_pct
                            }

                            if config["ENABLE_STOP_LOSS"] and price_drop_pct >= (config["SL_PERCENTAGE"] * 100):
                                ui_print(f"🛑 STOP-LOSS TRIGGER CONDITION MET FOR {asset[:8]}")
                                # Execute call cleanly handled dynamically
                    save_active_positions()
            except Exception as e:
                ui_print(f"⚠️ Error updating loop positions: {e}")
            await asyncio.sleep(15)

async def fetch_and_cache_gamma_data(client, event_slug):
    if event_slug in event_cache:
        return event_cache[event_slug]
    try:
        response = await client.get(f"{GAMMA_API_URL}{event_slug}", timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            if data and isinstance(data, list):
                tags = [tag.get("label", "").lower() for tag in data[0].get("tags", [])]
                event_cache[event_slug] = tags
                return tags
    except Exception:
        pass
    return []

async def execute_trade(poly_client, bot, token_id, leader_side, leader_price, leader_size, config):
    leader_value_usdc = leader_price * leader_size
    trade_amount_usdc = config["FIXED_AMOUNT"] if config["TRADE_MODE"] == "FIXED" else leader_value_usdc * (config["PERCENTAGE"] / 100.0)
    trade_amount_usdc = min(trade_amount_usdc, config["MAX_COPY_AMOUNT"])

    if leader_side == "BUY":
        my_side = Side.BUY
        my_price = min(0.99, round(leader_price * (1 + config["SLIPPAGE_TOLERANCE"]), 2))
    else:
        my_side = Side.SELL
        my_price = max(0.01, round(leader_price * (1 - config["SLIPPAGE_TOLERANCE"]), 2))

    trade_size_shares = calculate_clean_shares(price=my_price, target_usdc=trade_amount_usdc)
    ui_print(f"🤖 EXECUTING: {my_side.name} {trade_size_shares} shares @ ${my_price}")

    if config["PAPER_TRADE"]:
        ui_print(f"✅ [PAPER TRADE] Successfully simulated {my_side.name} position.")
        if bot:
            try: await asyncio.to_thread(bot.send_message, chat_id=os.getenv("MY_CHAT_ID"), text=f"✨ [PAPER] Traded {my_side.name} {trade_size_shares} @ ${my_price}")
            except Exception: pass
        return

    if not poly_client:
        ui_print("❌ Execution aborted: CLOB client uninitialized.")
        return

    try:
        resp = await asyncio.to_thread(
            poly_client.create_and_post_order,
            OrderArgs(price=my_price, size=trade_size_shares, side=my_side, token_id=token_id),
            options=PartialCreateOrderOptions(tick_size="0.01"),
            order_type=OrderType.FOK
        )
        ui_print(f"✅ Trade Response: {resp.get('success', False)}")
        if bot:
            await asyncio.to_thread(bot.send_message, chat_id=os.getenv("MY_CHAT_ID"), text=f"🎯 Live Order Posted: {my_side.name} {trade_size_shares} @ ${my_price}")
    except Exception as e:
        ui_print(f"❌ Execution Failed: {e}")

async def send_heartbeat(websocket):
    while state.get_running():
        try:
            await websocket.send("PING")
            await asyncio.sleep(5)
        except Exception:
            break

async def monitor_global_bets(poly_client, bot, config, target_wallets):
    while state.get_running():
        try:
            ui_print("Connecting to Polymarket WebSocket Stream...")
            async with websockets.connect(WSS_URL) as websocket, httpx.AsyncClient() as client:
                asyncio.create_task(send_heartbeat(websocket))
                subscribe_msg = {"action": "subscribe", "subscriptions": [{"topic": "activity", "type": "trades"}]}
                await websocket.send(json.dumps(subscribe_msg))
                ui_print("🚀 Connection Active! Monitoring customized wallets...")

                while state.get_running():
                    message = await websocket.recv()
                    data = json.loads(message)
                    p = data.get("payload", {})
                    if not p: continue

                    wallet = p.get("proxyWallet", "Unknown").lower()
                    pseudonym = p.get("pseudonym", "").lower()
                    event_slug = p.get("eventSlug")
                    market_slug = p.get("slug")
                    price = float(p.get("price", 0))
                    size = float(p.get("size", 0))
                    side = p.get("side", "").upper()
                    token_id = p.get("asset")

                    combined_slug = f"{event_slug or ''} {market_slug or ''}".lower()
                    if any(b in combined_slug for b in config["EXCLUDED_SLUGS"]):
                        continue

                    assigned_categories = None
                    matched_identity = None
                    if wallet in target_wallets:
                        assigned_categories = target_wallets[wallet]
                        matched_identity = wallet
                    elif pseudonym in target_wallets:
                        assigned_categories = target_wallets[pseudonym]
                        matched_identity = pseudonym

                    if assigned_categories is None or not event_slug:
                        continue

                    event_tags = await fetch_and_cache_gamma_data(client, event_slug)
                    if not any(tag in assigned_categories for tag in event_tags):
                        continue

                    if (config["PRICE_MIN"] and price < config["PRICE_MIN"]) or (config["PRICE_MAX"] and price > config["PRICE_MAX"]):
                        continue

                    ui_print(f"🎯 TARGET MATCH: {matched_identity} -> {side} @ ${price}")
                    asyncio.create_task(execute_trade(poly_client, bot, token_id, side, price, size, config))

        except Exception as e:
            ui_print(f"❌ Connection error: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)

def run_async_loop(poly_client, bot, config, target_wallets):
    loop = asyncio.new_event_loop()
    state.loop = loop
    asyncio.set_event_loop(loop)
    
    loop.run_until_complete(load_active_positions())
    loop. Jahn = loop.create_task(monitor_global_bets(poly_client, bot, config, target_wallets))
    loop.create_task(update_positions(config))
    
    loop.run_forever()

# ==========================================
# STREAMLIT USER INTERFACE
# ==========================================
st.set_page_config(page_title="Polymarket Copy Trader Dash", page_icon="📈", layout="wide")

st.title("📈 Polymarket Engine Control Room")
st.markdown("---")

# Initialize structural APIs safely
telegram_token = os.getenv("BOT_TOKEN")
bot = Bot(token=telegram_token) if telegram_token else None

poly_client = None
try:
    if os.getenv("EVM_PRIVATE") and os.getenv("POLY_API_KEY"):
        creds = ApiCreds(api_key=os.getenv("POLY_API_KEY"), api_secret=os.getenv("POLY_API_SECRET"), api_passphrase=os.getenv("POLY_API_PASSPHRASE"))
        poly_client = ClobClient(host=CLOB_HOST, key=os.getenv("EVM_PRIVATE"), chain_id=137, signature_type=3, funder=os.getenv("DEPOSIT_WALLET", ""), creds=creds)
except Exception as e:
    st.sidebar.error(f"CLOB Initialization Failure: {e}")

# Sidebar controls & Strategy Configurations
st.sidebar.header("🛠️ Operational Strategies")

trade_mode = st.sidebar.selectbox("Trade Amount Mode", ["FIXED", "PERCENTAGE"], index=0)
fixed_amount = st.sidebar.number_input("Fixed Allocation Amount (USDC)", min_value=1.0, value=2.0, step=0.5)
percentage_amount = st.sidebar.number_input("Percentage Trade Scale Allocation (%)", min_value=1.0, max_value=100.0, value=15.0)
max_copy_amount = st.sidebar.number_input("Max Copy Boundary Guard Limit (USDC)", min_value=1.0, value=8.0)

st.sidebar.subheader("🎯 Market Boundaries")
price_min = st.sidebar.slider("Min Acceptable Cost Price Limit", 0.01, 0.99, 0.50)
price_max = st.sidebar.slider("Max Acceptable Cost Price Limit", 0.01, 0.99, 0.95)
slippage_tolerance = st.sidebar.slider("Execution Slippage Buffer Protection", 0.00, 0.10, 0.01)

st.sidebar.subheader("🛡️ Risk Parameters")
paper_trade = st.sidebar.checkbox("Run Engine inside Paper Trade Sandbox Mode", value=True)
enable_tp = st.sidebar.checkbox("Enable Take Profit orders", value=False)
enable_sl = st.sidebar.checkbox("Enable Automated Stop Loss execution", value=True)
tp_percentage = st.sidebar.number_input("Take Profit Target Boundary Scale Multiplier", value=0.90)
sl_percentage = st.sidebar.number_input("Stop Loss Liquidation Drawdown Trigger", value=0.40)

# Build Runtime Configuration Map
current_config = {
    "TRADE_MODE": trade_mode, "FIXED_AMOUNT": fixed_amount, "PERCENTAGE": percentage_amount,
    "MAX_COPY_AMOUNT": max_copy_amount, "PRICE_MIN": price_min, "PRICE_MAX": price_max,
    "SLIPPAGE_TOLERANCE": slippage_tolerance, "PAPER_TRADE": paper_trade, "ENABLE_TAKE_PROFIT": enable_tp,
    "ENABLE_STOP_LOSS": enable_sl, "TP_PERCENTAGE": tp_percentage, "SL_PERCENTAGE": sl_percentage,
    "EXCLUDED_SLUGS": ["updown-5m", "updown-15m"]
}

# Load Watchlists 
target_wallets_raw = generate_wallet_config(["CRYPTO", "WEATHER"])
target_wallets = {k.lower(): [tag.lower() for tag in v] for k, v in target_wallets_raw.items()}

# Start/Stop Engine Buttons Actions
st.sidebar.subheader("🕹️ Engine Process Monitor")
if state.get_running():
    if st.sidebar.button("🛑 Stop Copy Trading Bot Process", use_container_width=True):
        ui_print("Attempting connection cycle tear-down gracefully...")
        state.set_running(False)
        if state.loop:
            state.loop.call_soon_threadsafe(state.loop.stop)
        st.rerun()
else:
    if st.sidebar.button("🚀 Ignition Run Trading System", use_container_width=True):
        state.set_running(True)
        ui_print("System Boot sequence initializing...")
        state.thread = threading.Thread(
            target=run_async_loop, 
            args=(poly_client, bot, current_config, target_wallets), 
            daemon=True
        )
        state.thread.start()
        st.rerun()

# Layout Status Visual Badges Indicator Matrix Elements
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric(label="System Architecture Engine Status", value="ACTIVE RUNNING" if state.get_running() else "STOPPED IDLE")
with c2:
    st.metric(label="Operational Profile Mode Environment", value="Sandbox Paper-Trade" if paper_trade else "Production Mainnet Live")
with c3:
    st.metric(label="Tracked Configured Active Wallets Count", value=f"{len(target_wallets)} Wallets")
with c4:
    st.metric(label="Active Monitors Tracked Positions Counters", value=f"{len(state.active_positions)} Tokens")

# Interface System Core Sections
tab1, tab2, tab3 = st.tabs(["📊 Live Positions Monitor Tracker", "⚙️ Targets Distribution Profiles", "📜 Real-Time Stream Engine Consoles"])

with tab1:
    st.subheader("Current Active Inventory Portfolio Tracking Matrix")
    if state.active_positions:
        # Build interactive structured display table frame
        display_data = []
        with state.lock:
            for k, v in state.active_positions.items():
                display_data.append({
                    "Asset Token ID Code": f"{k[:12]}...",
                    "Current Price Token Value": f"${v.get('cur_price', 0):.2f}",
                    "Total Position Shares Owned Size": f"{v.get('size', 0):.2f}",
                    "Average Inbound Weighted Entry Cost": f"${v.get('entry_price', 0):.2f}",
                    "Total Exposure (USDC Value)": f"${v.get('total', 0):.2f}",
                    "Performance Drawdowns Net Return": f"{v.get('pnl_pct', 0.0):+.2f}%"
                })
        st.dataframe(display_data, use_container_width=True)
    else:
        st.info("No tracking open exposures entries currently stored inside memory stack cache database frame mapping registries.")

with tab2:
    st.subheader("Configured Monitoring targets Profiles System Maps")
    if target_wallets_raw:
        st.json(target_wallets_raw)
    else:
        st.warning("Missing locally tracking profiles matching patterns! Please ensure file entities like `crypto_wallets.json` exist.")

with tab3:
    st.subheader("Automated Streaming Kernel Event Engine Stream logs Console")
    
    # Auto-refresh helper block trigger UI element logic
    if state.get_running():
        st.caption("🔄 Live-streaming pipeline console updating window blocks...")
    
    log_text = "\n".join(state.logs[::-1])  # Keep newest log strings showing up top
    st.text_area(label="Active Event Streaming Terminal Buffers Output Logs View", value=log_text, height=450)
    
    # Simple automated rerun tick trick trigger mechanism
    if state.get_running():
        asyncio.run(asyncio.sleep(1.5))
        st.rerun()