# config.py
import os
from dotenv import load_dotenv

load_dotenv()


# --- Polymarket CLOB Configuration ---
CLOB_HOST = os.getenv("CLOB_API_URL")
CHAIN_ID = 137 # Polygon Mainnet
GAMMA_URL = os.getenv("GAMMA_URL")

# Your trading credentials (required for placing orders)
# WARNING: Keep this secure!
PRIVATE_KEY = os.getenv("PK")
POLYMARKET_PROXY_ADDRESS = os.getenv("POLYMARKET_PROXY_ADDRESS") # Your Polymarket proxy or funder address

# --- Polymarket Data Configuration ---
DATA_API_BASE_URL = os.getenv("DATA_API_URL")

# --- Bot Configuration ---
TARGET_ADDRESS = os.getenv("TARGET_ADDRESS") # The address you want to copy (REQUIRED)
POLLING_INTERVAL_SECONDS = 5 # How often to check for new trades (adjust for latency)

# --- Copy Logic & Risk Management Features ---
# Fulfills "Customizable Settings" and "Advanced Filters"
ALLOCATION_PERCENT = 0.15 # e.g., 0.50 means 50%
MAX_TRADE_USDC = 4 # Maximum size of any single copied trade in USDC
MIN_TRADE_USDC = 0 # Minimum size of any single copied trade in USDC
SLIPPAGE_TOLERANCE_PERCENT = 0 # 0.5% max price slippage for market orders
MIN_TRADE_SIZE = 5 # Minimum trade shares
