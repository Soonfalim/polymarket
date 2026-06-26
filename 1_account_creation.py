from eth_account import Account
from py_clob_client_v2.client import ClobClient

# 1. Create a new Ethereum Account
def create_eth_account():
    # Enables secure entropy for key generation
    Account.enable_unaudited_hdwallet_features()
    new_acc = Account.create()
    
    print("--- NEW ETH ACCOUNT CREATED ---")
    print(f"Address: {new_acc.address}")
    print(f"Private Key: {new_acc.key.hex()}")
    return new_acc

# 2. Link the created eth account to Polymarket
def link_to_polymarket(eth_account):
    host = "https://clob.polymarket.com"
    chain_id = 137  # Polygon Mainnet
    
    # Initialize the client with the newly created private key
    # signature_type=0 for a standard EOA (Externally Owned Account)
    client = ClobClient(
        host, 
        key=eth_account.key.hex(), 
        chain_id=chain_id, 
        signature_type=0
    )

    try:
        # This derives the L2 API Key, Secret, and Passphrase 
        creds = client.create_or_derive_api_creds()
        
        print("\n--- POLYMARKET API CREDENTIALS ---")
        print(f"API Key: {creds.api_key}")
        print(f"API Secret: {creds.api_secret}")
        print(f"API Passphrase: {creds.api_passphrase}")
        
        return creds
    except Exception as e:
        print(f"Error linking to Polymarket: {e}")
        return None

if __name__ == "__main__":
    # Execute the flow
    my_new_wallet = create_eth_account()
    polymarket_creds = link_to_polymarket(my_new_wallet)
    
    if polymarket_creds:
        print("\nSuccess! Account created.")