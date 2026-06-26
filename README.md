# Polymarket Trading Bot

> **Disclaimer:** This project is created for personal and educational purposes only. Performance is not guaranteed. Use at your own risk.

A copy-trading bot for [Polymarket](https://polymarket.com) — a decentralized prediction market platform on Polygon. It uses the Polymarket CLOB Client v2 and a Deposit Wallet (signature type = 3) architecture to automate trading.

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
  - [1. Account Creation](#1-account-creation)
  - [2. Wallet Setup](#2-wallet-setup)
  - [3. Funding](#3-funding)
  - [4. Copy Trading](#4-copy-trading)
  - [5. Redeem & Withdraw](#5-redeem--withdraw)
  - [6. Monitoring & Analysis](#6-monitoring--analysis)
- [Project Structure](#project-structure)
- [Dependencies](#dependencies)
- [License](#license)

## Features

- **Automated Account Setup** — Create an EOA and derive Polymarket API credentials
- **Deposit Wallet Management** — Deploy and configure a Polymarket Deposit Wallet (smart contract wallet) with the Polymarket Relayer for gasless transactions
- **Copy Trading** — Automatically mirror trades from top-performing wallets with configurable filters:
  - Target specific wallet addresses and market categories
  - Fixed amount or percentage-based trade sizing
  - Price range filtering and slippage tolerance
  - Take profit / stop loss tracking
  - Paper trading mode
- **AI-Powered Market Analysis** — Free edge detection using Google Gemini + DuckDuckGo news
- **Real-Time Monitoring** — WebSocket-based trade activity and market resolution streams
- **Telegram Notifications** — Trade execution alerts and bot status updates
- **Redemption & Withdrawal** — Redeem winning positions and withdraw funds via the Polymarket Bridge

## Architecture

```
                    ┌─────────────────────┐
                    │   EOA (Signer)      │
                    │  Signs transactions │
                    └──────────┬──────────┘
                               │ deploys & signs for
                    ┌──────────▼──────────┐
                    │  Deposit Wallet     │
                    │  (Smart Contract)   │
                    │  Holds: pUSD, USDC, │
                    │  CTF tokens         │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐ ┌──────▼───────┐ ┌──────▼──────────┐
    │ Polymarket     │ │ Polymarket   │ │ Polymarket      │
    │ CLOB API       │ │ Relayer      │ │ Bridge          │
    │ (Orders,       │ │ (Gasless ops)│ │ (Deposit/       │
    │  Credentials)  │ │              │ │  Withdraw)      │
    └────────────────┘ └──────────────┘ └─────────────────┘
```

The EOA (Externally Owned Account) acts as the signer, while the Deposit Wallet (smart contract) holds funds and executes trades using signature type 3 (EIP-1271 / POLY_1271). The Polymarket Relayer sponsors gas for all on-chain operations.

## Prerequisites

- Python 3.8+
- A Polymarket Builder API key (get from the [Polymarket Builder Portal](https://builder.polymarket.com))
- A small amount of MATIC and USDC.e on Polygon for initial funding
- (Optional) A Telegram bot token for notifications
- (Optional) A Google Gemini API key for AI analysis

## Installation

1. Clone the repository:

```bash
git clone <repository-url>
cd polymarket
```

2. Install dependencies:

```bash
pip install -r module_requirement
```

3. Copy the environment template and fill in your configuration:

```bash
cp .env.example .env
```

## Configuration

Edit `.env` with your credentials:

| Variable | Description |
|---|---|
| `EVM_ADDRESS` | Your Ethereum account address |
| `EVM_PRIVATE` | Your Ethereum account private key |
| `POLY_API_KEY` | Polymarket CLOB API key |
| `POLY_API_SECRET` | Polymarket CLOB API secret |
| `POLY_API_PASSPHRASE` | Polymarket CLOB API passphrase |
| `BUILDER_CODE` | Polymarket builder code |
| `BUILDER_API_KEY` | Polymarket relayer API key |
| `BUILDER_SECRET` | Polymarket relayer secret |
| `BUILDER_PASS_PHRASE` | Polymarket relayer passphrase |
| `DEPOSIT_WALLET` | Deposit wallet address (after deployment) |
| `TARGET_WALLET` | Target wallet address for copy trading |
| `BOT_TOKEN` | Telegram bot token (optional) |
| `MY_CHAT_ID` | Telegram chat ID (optional) |

## Usage

### 1. Account Creation

Generate a new Ethereum account and derive Polymarket CLOB API credentials:

```bash
python 1_account_creation.py
```

Save the output (address, private key, API key/secret/passphrase) to your `.env` file.

### 2. Wallet Setup

**Check wallet balances:**

```bash
python 2_check_wallet.py
```

**Deploy the deposit wallet:**

```bash
python 3_deploy_deposit_wallet.py
```

Add the resulting `DEPOSIT_WALLET` address to your `.env`.

**Set contract allowances:**

```bash
python 4_wallet_allowance.py
```

This approves infinite allowances for pUSD, USDC, and CTF tokens to the relevant exchange contracts.

### 3. Funding

Get a bridge deposit address to fund your deposit wallet:

```bash
python 5_deposit_address.py
```

Send USDC (from Ethereum mainnet, Solana, TRON, or Bitcoin) to the returned address. Polymarket's bridge will wrap it to pUSD and deliver it to your deposit wallet.

### 4. Copy Trading

**Generate leaderboard wallet lists (optional):**

```bash
python generate_smart_wallets.py
```

This creates `{category}_wallets.json` files (e.g., `CRYPTO_wallets.json`) for use by the copy trader.

**Start the copy trading bot:**

```bash
python 6_copy_trading.py
```

Configure trading parameters at the top of the script:
- `TRADE_MODE` — `"FIXED"` (bet a fixed amount) or `"PERCENTAGE"` (bet a percentage of the leader's size)
- `FIXED_AMOUNT` / `PERCENTAGE` — Trade sizing
- `MAX_COPY_AMOUNT` — Maximum per-trade amount (default: $13)
- `PRICE_MIN` / `PRICE_MAX` — Price range filter
- `SLIPPAGE_TOLERANCE` — Maximum allowed slippage
- `PAPER_TRADE` — Set to `True` for dry runs

### 5. Redeem & Withdraw

**Redeem winnings from resolved markets:**

```bash
python redeem_winnings.py
```

**Withdraw pUSD via the bridge (converts to native USDC):**

```bash
python pusd_extraction.py
```

**Directly transfer native USDC out of the deposit wallet:**

```bash
python usdc_extraction.py
```

### 6. Monitoring & Analysis

**Monitor specific wallets in real-time (console):**

```bash
python monitor_trader.py
```

**Watch global trade activity filtered by category:**

```bash
python polymarket_activity.py
```

**Listen for market resolution events:**

```bash
python polymarket_resolved.py
```

**Check open and closed positions:**

```bash
python check_trader.py
```

**View recently closed markets:**

```bash
python polymarket_closed.py
```

**AI-powered market edge analysis:**

```bash
python ai_analysis.py
```

## Project Structure

```
polymarket/
├── .env.example              # Environment variable template
├── module_requirement        # Python dependencies
├── README.md                 # This file
├── 1_account_creation.py     # Create EOA & derive API credentials
├── 2_check_wallet.py         # Check wallet balances
├── 3_deploy_deposit_wallet.py # Deploy deposit wallet via relayer
├── 4_wallet_allowance.py     # Set contract allowances
├── 5_deposit_address.py      # Get bridge deposit address
├── 6_copy_trading.py         # Main copy trading bot
├── ai_analysis.py            # AI-powered market analysis
├── check_trader.py           # Check positions for any wallet
├── generate_smart_wallets.py # Fetch leaderboard wallets
├── manual_sell.py            # Manual sell order utility
├── monitor_trader.py         # Real-time wallet monitor
├── polymarket_activity.py    # Global trade activity stream
├── polymarket_closed.py      # Recently closed markets
├── polymarket_resolved.py    # Market resolution events
├── pusd_extraction.py        # Withdraw pUSD via bridge
├── redeem_winnings.py        # Redeem winning positions
└── usdc_extraction.py        # Direct USDC transfer
```

## Dependencies

| Package | Purpose |
|---|---|
| `py_clob_client_v2` | Polymarket CLOB v2 client |
| `poly-web3` | High-level redemption service |
| `py_builder_relayer_client` | Gasless relayer operations |
| `web3` | Ethereum interaction |
| `requests` | HTTP API calls |
| `httpx` | Async HTTP client |
| `websockets` | WebSocket client |
| `python-dotenv` | Environment variable loading |
| `python-telegram-bot` | Telegram notifications |
| `beautifulsoup4` | HTML parsing |
| `duckduckgo_search` | Web search for AI analysis |
| `openai` | OpenAI API |

## License

This project is for personal and educational use only.
