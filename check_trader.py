#pip install requests
import requests

TARGET_WALLETS = [
    "0xce25e214d5cfe4f459cf67f08df581885aae7fdc",
    #"0xfbd8c9c22ca76b3662d0e53a4f79719fdc684027",
]

# ================================================
# Check closed positions (using API)
# ================================================
def print_closed_positions(wallet_address):
    url = "https://data-api.polymarket.com/closed-positions"
    
    closed_page = 1
    closed_index = 0
    
    while True:
        # Query parameters based on the closed positions API specification
        params = {
            "user": wallet_address,
            "limit": 50,               # Maximum allowed limit per request for this endpoint is 50
            "sortBy": "REALIZEDPNL",   # Options: REALIZEDPNL, TITLE, PRICE, AVGPRICE, TIMESTAMP
            "sortDirection": "DESC",
            "offset": closed_page
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            positions = response.json()
            
            if not positions:
                print(f"Done for wallet: {wallet_address}")
                return

            print(f"=== Closed Positions for {wallet_address} ===\n")
            
            for pos in positions:
                title = pos.get("title", "Unknown Market")
                outcome = pos.get("outcome", "N/A")
                total_bought = pos.get("totalBought", 0)
                avg_price = pos.get("avgPrice", 0)
                cur_price = pos.get("curPrice", 0)       # Final settlement price (usually $1.00 or $0.00)
                realized_pnl = pos.get("realizedPnl", 0)
                
                # Format the end date if it exists
                end_date = pos.get("endDate", "Unknown Date")

                closed_index += 1

                print(f"[{closed_index}] {title}")
                print(f"    • Outcome Bet:       {outcome}")
                print(f"    • Total Vol Bought:  ${total_bought:.2f}")
                print(f"    • Avg Entry Price:   ${avg_price:.2f} | Settlement Price: ${cur_price:.2f}")
                print(f"    • Realized PnL:      ${realized_pnl:.2f}")
                print(f"    • Market Closed:     {end_date}")
                print("-" * 50)

                closed_page += 1
                
        except requests.exceptions.RequestException as e:
            print(f"Error fetching closed positions: {e}")


if __name__ == "__main__":
    for wallet in TARGET_WALLETS:
        print_closed_positions(wallet)