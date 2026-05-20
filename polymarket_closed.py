import requests
import json

def fetch_closed_polymarket_bets():
    count = 0
    page = 1

    while True:
        """
        Fetches closed/resolved markets from the Polymarket Gamma API.
        """
        # Polymarket Gamma API endpoint for markets
        url = "https://gamma-api.polymarket.com/markets"
        
        # Query parameters to filter for closed and inactive markets
        params = {
            "closed": "true",
            "limit": 100,
            "offset": page
        }
        
        try:
            print(f"Fetching closed Polymarket bets...")
            response = requests.get(url, params=params)
            
            # Check if request was successful
            if response.status_code != 200:
                print(f"Error: Unable to fetch data (Status Code: {response.status_code})")
                return
            
            markets = response.json()
            
            if not markets:
                print("No closed markets found.")
                return

            print("-" * 80)
            print(f"{'CLOSED MARKET QUESTION':<50} | {'VOLUME (USD)':<12} | {'OUTCOME'}")
            print("-" * 80)
            
            for market in markets:
                # Extract relevant fields cleanly
                question = market.get("question", "Unknown Question")
                
                # Volume is string-based in the API, we parse it to a float for clean formatting
                volume = market.get("volume", "0")
                    
                # The winning outcome/resolution text
                liquidity = market.get("liquidity")
                
                if liquidity != "0":
                    outcomes = json.loads(market["outcomes"])
                    outcomes_prices = [float(p) for p in json.loads(market["outcomePrices"])]

                    if any(outcomes_prices):
                        winning_index = outcomes_prices.index(max(outcomes_prices))
                        winner = outcomes[winning_index]
                        outcomes.pop(winning_index)
                        losers = outcomes
                else:
                    winner = "Not applicable"
                    losers = "Not applicable"
                
                # Truncate text if it's too long for the console table layout
                if len(question) > 47:
                    question = question[:44] + "..."
                
                page +=1
                count += 1

                if isinstance(losers, list):
                    loser_str = ", ".join(losers)
                elif isinstance(losers, str):
                    loser_str = losers
                print(f"{count}. {question:<50} | {volume:<12} | Winner = {winner} | Loser = {loser_str}")
                
            print("-" * 80)
            
        except Exception as e:
            print(f"An error occurred: {e}")

if __name__ == "__main__":
    # Change the limit value to pull more or fewer closed bets
    fetch_closed_polymarket_bets()