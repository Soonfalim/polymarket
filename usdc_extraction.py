#=========================================
#  TO EXTRACT USDC OUT OF DEPOSIT WALLET
#=========================================
import os
from dotenv import load_dotenv
from web3 import Web3
from py_builder_relayer_client.models import DepositWalletCall
from _func import make_relayer, wallet_batch

# Load the variables from .env into the environment
load_dotenv()

PRIVATE_KEY    = os.getenv("EVM_PRIVATE")
DEPOSIT_WALLET = os.getenv("DEPOSIT_WALLET")
RPC_URL        = "https://polygon-bor-rpc.publicnode.com"
DESTINATION_ADDRESS = os.getenv("PERSONAL_ADDRESS")
AMOUNT = 10

DW = Web3.to_checksum_address(DEPOSIT_WALLET)
USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")

w3 = Web3(Web3.HTTPProvider(RPC_URL))

# Minimal ABI for transfer
USDC_TRANSFER_ABI = [
    {"name": "transfer", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "recipient", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]}
]

# Destination address where you want to receive USDC
DESTINATION_ADDRESS = "0xba2175aa786cF9cDdD46461EDDa708e620aB279A"

print(f"Queuing recovery transfer of {AMOUNT} USDC out of proxy contract...")
usdc_contract = w3.eth.contract(address=USDC, abi=USDC_TRANSFER_ABI)
amount_usdc = AMOUNT * 10**6

transfer_data = usdc_contract.encode_abi("transfer", args=[DESTINATION_ADDRESS, amount_usdc])

# This target (USDC contract) and method (transfer) ARE explicitly allowed by the relayer
calls = [DepositWalletCall(target=USDC, value="0", data=transfer_data)]

print(f"Submitting WALLET batch to release funds...")
relayer = make_relayer()
wallet_batch(relayer, DW, calls)

print("✓ Funds successfully extracted from the deposit wallet proxy!")