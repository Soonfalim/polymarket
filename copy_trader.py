from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import OrderArgs, OrderType
from py_clob_client_v2.order_builder.constants import BUY, SELL
from typing import Dict
from data_listener import TradeListener
from config import (
    CLOB_HOST, CHAIN_ID, PRIVATE_KEY, POLYMARKET_PROXY_ADDRESS, TARGET_ADDRESS,
    ALLOCATION_PERCENT, MAX_TRADE_USDC, MIN_TRADE_USDC,
    SLIPPAGE_TOLERANCE_PERCENT, MIN_TRADE_SIZE
)

class CopyTrader:
    """Handles the core copy logic and order placement via CLOB API."""
    
    def __init__(self):
        # Initialize CLOB Client (assuming EOA for simplicity, adjust signature_type if using Magic/Proxy)
        # Signature Type 0 (EOA) is the default. Use 1 or 2 for proxy/smart wallets.
        self.client = ClobClient(
            host=CLOB_HOST, 
            chain_id=CHAIN_ID, 
            key=PRIVATE_KEY, 
            funder=POLYMARKET_PROXY_ADDRESS,
            signature_type=3 
        )
        # Create or derive API credentials for L2 CLOB interactions
        self.client.set_api_creds(self.client.create_or_derive_api_key())
        print("CLOB Client initialized. Ready to trade.")

    def _apply_filters(self, original_trade: Dict) -> bool:
        """
        Fulfills the 'Advanced Filters' feature.
        Applies pre-execution checks and risk management logic.
        """
        # Ensure we are copying a completed trade (usually indicated by a non-zero fill size)
        if original_trade.get("size") is None or float(original_trade["size"]) == 0:
             print("Skipping: Invalid or zero-size trade.")
             return False

        # Extract amount traded in USDC (CASH)
        trade_amount_usdc = float(original_trade.get("size", 0))*float(original_trade.get("price", 0))

        # 1. Minimum Trade Size Filter
        if trade_amount_usdc < MIN_TRADE_USDC:
            print(f"Skipping: Trade size ({trade_amount_usdc:.2f} USDC) is below min filter ({MIN_TRADE_USDC:.2f} USDC).")
            return False
        
        if original_trade.get('slug') and '4h' in original_trade.get('slug'):
            print(f"Skipping: Trade in 4h market")
            return False
        # 2. Add other custom filters here (e.g., market ID, PnL of trader, etc.)
        # Example: Filter out trades in non-political markets
        # market_tag = self.get_market_tag(original_trade["conditionId"]) # Requires a lookup
        # if market_tag not in ['Politics', 'Election']:
        #     return False

        return True

    def execute_copy_trade(self, original_trade: Dict):
        """
        Core copy logic: validates, calculates, and submits the order.
        """
        if not self._apply_filters(original_trade):
            return

        original_price = float(original_trade["price"])
        original_side = original_trade["side"] # 'BUY' or 'SELL'
        original_size = float(original_trade.get("size", 0))
        original_amount_usdc = original_price * original_size
        token_id = original_trade["asset"]
        original_outcome = original_trade.get("outcome", "N/A")
        market_title = original_trade.get("title", original_trade["conditionId"])

        print(f"\n--- Copying Trade in: {market_title} ---")
        print(f"Original: {original_side} {original_outcome} -  {original_size:.2f} SHARES @ {original_price:.4f} - {original_amount_usdc:.2f} USDC")

        # --- 1. Calculate Copy Amount (Fulfills 'Customizable Settings/Percentages') ---
        copied_amount_usdc = original_amount_usdc * ALLOCATION_PERCENT
        
        # Apply MAX_TRADE_SIZE_USDC limit
        copied_amount_usdc = min(copied_amount_usdc, MAX_TRADE_USDC)
        
        if copied_amount_usdc < MIN_TRADE_USDC:
             print(f"Skipping: Calculated amount ({copied_amount_usdc:.2f} USDC) too small after allocation.")
             return

        # --- 2. Determine Order Parameters ---
        # The CLOB client requires size in shares/tokens. Price is in $ per share.
        
        # Calculate the size in outcome tokens (shares) to BUY/SELL
        # size_in_tokens = amount_in_usdc / price_per_token
        copied_size_tokens = copied_amount_usdc / original_price
        # Apply MIN_TRADE_SIZE limit (minimum 5 hares by limit order)
        copied_size_tokens = max(copied_size_tokens, MIN_TRADE_SIZE)

        
        # The copy trade should mirror the original: BUY copies BUY, SELL copies SELL.
        copy_side = BUY if original_side == 'BUY' else SELL
        
        # We target the original trader's price.
        if copy_side == BUY:
            # When buying, we want the price to be as low as possible, but we'll submit at the 
            # original price or slightly higher to ensure a fill.
            # Max price the bot is willing to pay: original_price * (1 + SLIPPAGE)
            max_buy_price = original_price * (1 + SLIPPAGE_TOLERANCE_PERCENT)
            order_price = round(max_buy_price, 4) 
        else: # SELL
            # When selling, we want the price to be as high as possible, but we'll submit at the
            # original price or slightly lower to ensure a fill.
            # Min price the bot is willing to accept: original_price * (1 - SLIPPAGE)
            min_sell_price = original_price * (1 - SLIPPAGE_TOLERANCE_PERCENT)
            order_price = round(min_sell_price, 4)
        order_amount = order_price * copied_size_tokens
        print(f"Bot Order: {copy_side} {original_outcome} {copied_size_tokens:.2f} shares @ {order_price:.4f} - {order_amount:.2f} USDC (Limit order)")
        
        # --- 4. Prepare and Post Order ---
        order_args = OrderArgs(
            token_id=token_id,
            price=order_price,
            size=copied_size_tokens,
            side=copy_side
        )

        try:
            # We use GTC (Good-Till-Cancelled) as a robust limit order type. (by default)
            # The order will execute as a market order if marketable.
            signed_order = self.client.create_order(order_args)
            
            # Place the order
            response = self.client.post_order(signed_order, OrderType.GTC)
            if response.get("success"):
                status = response.get("status", "unknown")
                orderID = response.get("orderID", "N/A")
                print(f"✅ Success! Order ID: {orderID}, Status: {status}")
                if "matched" in status:
                    print("💰 Trade was executed immediately (Market Order).")
            else:
                print(f"❌ Order Placement Failed: {response.get('errorMsg')}")
                
        except Exception as e:
            print(f"A critical error occurred during order submission: {e}")

# --- Main Bot Runner ---

def main():
    if not PRIVATE_KEY or not POLYMARKET_PROXY_ADDRESS or not TARGET_ADDRESS:
        print("FATAL ERROR: Configuration missing. Check your .env file and config.py settings.")
        return

    # 1. Initialize Executor
    copy_trader = CopyTrader()
    
    # 2. Initialize Listener
    listener = TradeListener(TARGET_ADDRESS)
    
    # 3. Start the loop, passing the execution method as a callback
    print("\n🚀 Starting Polymarket Copy Trading Bot...")
    listener.run_polling_loop(copy_trader.execute_copy_trade)

if __name__ == "__main__":
    main()