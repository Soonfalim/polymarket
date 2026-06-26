from dotenv import load_dotenv
from _func import make_relayer, CHAIN_ID

# Load the variables from .env into the environment
load_dotenv()

relayer = make_relayer()

# Deterministically derive the deposit wallet address before deploying
deposit_wallet = relayer.get_expected_deposit_wallet()
print(f"Chain          : {CHAIN_ID}")
print(f"Owner (EOA)    : {relayer.signer.address()}")
print(f"Deposit wallet : {deposit_wallet}  (deterministic — store as DEPOSIT_WALLET in .env)\n")

print("Submitting WALLET-CREATE to relayer…")
response  = relayer.deploy_deposit_wallet()
confirmed = response.wait()

print(f"\n✓ Deposit wallet deployed: {deposit_wallet}")
print(f"  Add to .env:  DEPOSIT_WALLET={deposit_wallet}")
print("\nNext: fund the wallet — send USDC.e to your EOA then run 3_wrap.py")