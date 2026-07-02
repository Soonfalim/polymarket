from dotenv import load_dotenv, set_key
from _func import make_relayer, CHAIN_ID

dotenv_path = '.env'

# Load the variables from .env into the environment
load_dotenv()

relayer = make_relayer()

# Deterministically derive the deposit wallet address before deploying
deposit_wallet = relayer.get_expected_deposit_wallet()
print(f"Chain          : {CHAIN_ID}")
print(f"Owner (EOA)    : {relayer.signer.address()}")
print(f"Deposit wallet : {deposit_wallet}  (deterministic — store as DEPOSIT_WALLET in .env)\n")

set_key(dotenv_path, "DEPOSIT_WALLET", deposit_wallet)

print("Submitting WALLET-CREATE to relayer…")
response  = relayer.deploy_deposit_wallet()
confirmed = response.wait()

print(f"\n✓ Deposit wallet deployed: {deposit_wallet}")
print("\nNext: fund the wallet — send USDC to deposit address obtained from 5_deposit_address.py")