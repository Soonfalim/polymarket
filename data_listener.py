import requests
import time
from typing import List, Dict
from config import DATA_API_BASE_URL, POLLING_INTERVAL_SECONDS

class TradeListener:
    """Monitors the target address for new trades using fixed-sort API endpoint."""
    
    def __init__(self, target_address: str):
        self.target_address = target_address
        # Initialize with the current time to avoid processing old trades on first run
        self.last_trade_timestamp = int(time.time())
        print(f"Tracking address: {self.target_address}")
        print(f"Ignoring trades before timestamp: {self.last_trade_timestamp}")

    def _fetch_new_trades(self) -> List[Dict]:
        """
        Fetches trades for the target address.
        The API returns trades ordered by timestamp DESC (newest first).
        """
        endpoint = f"{DATA_API_BASE_URL}/trades"
        
        # Query parameters to filter by user and limit the result set
        params = {
            "user": self.target_address,
            "limit": 10, # Check a small batch of recent trades
        }
        
        try:
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status() # Raises an exception for bad status codes (4xx or 5xx)
            trades = response.json()
            new_trades = []
            
            # Since the trades are in DESC order (newest first), we iterate through them
            for trade in trades:
                # API timestamps are typically in seconds
                trade_ts = trade.get("timestamp", 0) 
                
                if trade_ts > self.last_trade_timestamp:
                    new_trades.append(trade)
                else:
                    # Because the list is sorted DESC, we can stop checking once we hit an old trade
                    break

            # The API returns DESC, but for safe copy trading, we must process the 
            # trades in the order they occurred (ASC: oldest new trade first).
            new_trades.reverse()
            return new_trades

        except requests.exceptions.RequestException as e:
            print(f"Error fetching trades: {e}")
            return []

    def run_polling_loop(self, copy_trader_callback):
        """Main loop for trade surveillance."""
        while True:
            new_trades = self._fetch_new_trades()
            if new_trades:
                print(f"Found {len(new_trades)} new trade(s) to copy at {time.ctime()}:")
                for trade in new_trades:
                    copy_trader_callback(trade)
                
                # Update the last recorded timestamp to the timestamp of the latest trade processed.
                # Since we reversed the list, the last item is the most recent trade.
                self.last_trade_timestamp = new_trades[-1].get("timestamp", self.last_trade_timestamp)
                print(f"Updated last tracked timestamp to: {self.last_trade_timestamp}")
            
            time.sleep(POLLING_INTERVAL_SECONDS)