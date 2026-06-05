import requests

# Replace with your target Polymarket wallet address
TARGET_WALLET = "0x51C2059Cef7D809E7F915d8a36517f19c060A259"

def print_current_positions(wallet_address):
    """
    Fetches and prints all active current positions for a given Polymarket wallet.
    """
    url = "https://data-api.polymarket.com/positions"
    
    # Query parameters based on the API specification
    params = {
        "user": wallet_address,
        "sizeThreshold": 1,       # Only show positions with a meaningful size
        "limit": 500,             # Number of positions to return per request (max 500)
        "sortBy": "TOKENS",
        "sortDirection": "DESC"
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        positions = response.json()
        
        if not positions:
            print(f"No current active positions found for wallet: {wallet_address}")
            return

        print(f"=== Current Positions for {wallet_address} ===\n")
        
        for index, pos in enumerate(positions, 1):
            title = pos.get("title", "Unknown Market")
            outcome = pos.get("outcome", "N/A")
            size = pos.get("size", 0)
            avg_price = pos.get("avgPrice", 0)
            cur_price = pos.get("curPrice", 0)
            current_value = pos.get("currentValue", 0)
            pnl = pos.get("cashPnl", 0)
            pnl_percent = pos.get("percentPnl", 0)
            asset = pos.get("asset")

            print(f"[{index}] {title}")
            print(f"    • Outcome Bet:   {outcome}")
            print(f"    • Position Size: {size:.2f} tokens")
            print(f"    • Avg Price:     ${avg_price:.2f} | Current Price: ${cur_price:.2f}")
            print(f"    • Total Value:   ${current_value:.2f}")
            print(f"    • Cash PnL:      ${pnl:.2f} ({pnl_percent:.2f}%)")
            print(f"    • Asset ID:      {asset}")
            print("-" * 50)
            
    except requests.exceptions.RequestException as e:
        print(f"Error fetching positions: {e}")

def print_closed_positions(wallet_address):
    """
    Fetches and prints all closed positions for a given Polymarket wallet.
    """
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
            
            for index, pos in enumerate(positions, 1):
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
    print_current_positions(TARGET_WALLET)
    
    #print_closed_positions(TARGET_WALLET)