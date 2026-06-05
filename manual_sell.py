import os
from dotenv import load_dotenv
# Load the variables from .env into the environment
load_dotenv()
from py_clob_client_v2 import OrderArgs, OrderType, PartialCreateOrderOptions
from py_clob_client_v2.order_builder.constants import BUY, SELL
from py_clob_client_v2 import ClobClient, SignatureTypeV2

host = "https://clob.polymarket.com"
chain = 137  # Polygon mainnet
private_key = os.getenv("EVM_PRIVATE")
deposit_wallet_address = os.getenv("DEPOSIT_WALLET")

# Derive API credentials
temp_client = ClobClient(host, key=private_key, chain_id=chain)
api_creds = temp_client.create_or_derive_api_key()

# Initialize trading client
client = ClobClient(
    host,
    key=private_key,
    chain_id=chain,
    creds=api_creds,
    signature_type=SignatureTypeV2.POLY_1271,
    funder=deposit_wallet_address
)

response = client.create_and_post_order(
    OrderArgs(
        token_id="76086983820547840506848095969875012507662997048459822544420595518715225273522",
        price=0.15,
        size=10,
        side=SELL,
    ),
    options=PartialCreateOrderOptions(
        tick_size="0.01",
        neg_risk=False,  # Set to True for multi-outcome markets
    ),
    order_type=OrderType.GTC
)

print("Order ID:", response["orderID"])
print("Status:", response["status"])