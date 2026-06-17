import json
import requests


def fetch_and_store_wallets(target_count=110, category="CRYPTO"):
    url = "https://data-api.polymarket.com/v1/leaderboard"
    all_wallets = []
    offset = 0

    print(f"Starting extraction for {target_count} wallets...")

    while offset < target_count:
        # Calculate how many wallets are remaining to hit the target
        remaining = target_count - offset
        # The API allows a maximum limit of 50 per request
        current_limit = min(50, remaining)

        params = {
            "category": category,
            "timePeriod": "ALL",
            "orderBy": "PNL",
            "limit": current_limit,
            "offset": offset,
        }

        try:
            print(
                f"-> Fetching: offset={offset}, limit={current_limit}..."
            )
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            # Extract wallets from current batch
            batch_wallets = [
                trader["proxyWallet"] for trader in data if "proxyWallet" in trader
            ]

            # If the API returns fewer items than expected, we've hit the end of the leaderboard
            if not batch_wallets:
                print("No more data available on the leaderboard.")
                break

            all_wallets.extend(batch_wallets)

            # Move offset forward by 50 for the next cycle
            offset += 50

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data at offset {offset}: {e}")
            break

    # Truncate strictly to target_count just in case the API returned a tiny bit extra
    all_wallets = all_wallets[:target_count]

    # Save all accumulated results to the JSON file
    with open(f"{category}_wallets.json", "w") as f:
        json.dump(all_wallets, f, indent=4)

    print(
        f"\nSuccessfully stored {len(all_wallets)} wallets total in '{category}_wallets.json'"
    )


if __name__ == "__main__":
    fetch_and_store_wallets(target_count=100, category="SPORTS")