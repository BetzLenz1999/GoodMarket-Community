"""
P2PEscrow Contract Deployment Script for Celo Mainnet.

Deploys the peer-to-peer G$ trading escrow. The deployer wallet (P2P_KEY)
becomes the contract owner == arbiter, used only for the admin-review path
(seller rejected the buyer's proof) and dispute resolution. All normal
buyer/seller fund actions are user-signed.

REQUIRED ENV VARS:
    P2P_KEY                       — Deployer wallet private key (becomes owner/arbiter, pays gas)
    GOODDOLLAR_CONTRACT_ADDRESS   — G$ token address (default: Celo mainnet G$)

OPTIONAL ENV VARS:
    CELO_RPC_URL                  — Celo RPC (default https://forno.celo.org)
    CHAIN_ID                      — default 42220 (Celo Mainnet)
    P2P_PAYMENT_WINDOW_SECONDS    — buyer payment window (default 1800 = 30 min)

AFTER DEPLOYMENT:
    Set env var:  P2P_ESCROW_CONTRACT_ADDRESS=<deployed_address>

Usage:
    uv run python contracts/deploy_p2p_escrow.py
"""

import os
import json
import logging
from web3 import Web3
from eth_account import Account
from solcx import compile_standard, install_solc

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

CELO_RPC_URL = os.getenv('CELO_RPC_URL', 'https://forno.celo.org')
CHAIN_ID = int(os.getenv('CHAIN_ID', 42220))

GOODDOLLAR_CONTRACT = os.getenv(
    'GOODDOLLAR_CONTRACT_ADDRESS',
    '0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A',
)
PAYMENT_WINDOW_SECONDS = int(os.getenv('P2P_PAYMENT_WINDOW_SECONDS', 1800))

P2P_SOURCE = open(os.path.join(os.path.dirname(__file__), 'P2PEscrow.sol')).read()


def compile_contract():
    logger.info("Installing Solidity compiler v0.8.21...")
    install_solc('0.8.21')
    logger.info("Compiling P2PEscrow contract...")

    compiled = compile_standard({
        "language": "Solidity",
        "sources": {
            "P2PEscrow.sol": {"content": P2P_SOURCE}
        },
        "settings": {
            "optimizer": {"enabled": True, "runs": 200},
            "outputSelection": {
                "*": {
                    "*": ["abi", "metadata", "evm.bytecode", "evm.deployedBytecode"]
                }
            }
        }
    }, solc_version='0.8.21')

    contract_data = compiled["contracts"]["P2PEscrow.sol"]["P2PEscrow"]
    return {
        "abi": contract_data["abi"],
        "bytecode": contract_data["evm"]["bytecode"]["object"]
    }


def deploy_contract():
    p2p_key = os.getenv('P2P_KEY')

    if not p2p_key:
        logger.error("P2P_KEY not set!")
        return None
    if not GOODDOLLAR_CONTRACT:
        logger.error("GOODDOLLAR_CONTRACT_ADDRESS not set!")
        return None

    w3 = Web3(Web3.HTTPProvider(CELO_RPC_URL))
    if not w3.is_connected():
        logger.error("Failed to connect to Celo network")
        return None

    logger.info(f"Connected to Celo Mainnet (Chain ID: {CHAIN_ID})")

    key = p2p_key if p2p_key.startswith('0x') else '0x' + p2p_key
    account = Account.from_key(key)
    logger.info(f"Deploying from P2P_KEY address: {account.address}")
    logger.info(f"  G$ token:        {GOODDOLLAR_CONTRACT}")
    logger.info(f"  Payment window:  {PAYMENT_WINDOW_SECONDS}s")

    celo_balance = w3.eth.get_balance(account.address)
    celo_human = w3.from_wei(celo_balance, 'ether')
    logger.info(f"CELO balance: {celo_human} CELO")

    if celo_balance < w3.to_wei(0.05, 'ether'):
        logger.error(f"Insufficient CELO for gas (need ~0.05, have {celo_human}). Top up the P2P_KEY address.")
        return None

    compiled = compile_contract()

    contract = w3.eth.contract(abi=compiled["abi"], bytecode=compiled["bytecode"])

    nonce = w3.eth.get_transaction_count(account.address)
    gas_price = int(w3.eth.gas_price * 1.2)

    ctor_call = contract.constructor(
        Web3.to_checksum_address(GOODDOLLAR_CONTRACT),
        PAYMENT_WINDOW_SECONDS,
    )
    try:
        gas_estimate = ctor_call.estimate_gas({'from': account.address})
    except Exception as e:
        logger.warning(f"estimate_gas failed ({e}); falling back to 2_500_000")
        gas_estimate = 2_500_000
    gas_limit = int(gas_estimate * 1.15)
    logger.info(f"Gas estimate: {gas_estimate} (using limit: {gas_limit})")
    logger.info(f"Gas price:    {gas_price} wei (~{gas_price / 1e9:.2f} gwei)")
    logger.info(f"Max tx cost:  {gas_limit * gas_price} wei (~{gas_limit * gas_price / 1e18:.4f} CELO)")

    constructor_txn = ctor_call.build_transaction({
        'chainId':  CHAIN_ID,
        'gas':      gas_limit,
        'gasPrice': gas_price,
        'nonce':    nonce,
    })

    signed_txn = w3.eth.account.sign_transaction(constructor_txn, key)
    tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
    tx_hash_hex = tx_hash.hex()
    if not tx_hash_hex.startswith('0x'):
        tx_hash_hex = '0x' + tx_hash_hex

    logger.info(f"Tx hash: {tx_hash_hex}")
    logger.info(f"Explorer: https://celoscan.io/tx/{tx_hash_hex}")
    logger.info("Waiting for confirmation...")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

    if receipt.status == 1:
        contract_address = receipt.contractAddress
        logger.info(f"Contract deployed: {contract_address}")
        logger.info(f"   CeloScan: https://celoscan.io/address/{contract_address}")
        logger.info(f"   Gas used: {receipt.gasUsed}")

        deployment_info = {
            "contract_name": "P2PEscrow",
            "version": "1",
            "contract_address": contract_address,
            "tx_hash": tx_hash_hex,
            "deployer": account.address,
            "owner": account.address,
            "gooddollar_token": GOODDOLLAR_CONTRACT,
            "payment_window_seconds": PAYMENT_WINDOW_SECONDS,
            "chain_id": CHAIN_ID,
            "network": "Celo Mainnet",
            "block_number": receipt.blockNumber,
            "gas_used": receipt.gasUsed,
            "compiler_version": "v0.8.21+commit.d9974bed",
            "optimization": True,
            "optimization_runs": 200,
            "notes": (
                "P2P G$ trading escrow. Seller locks G$ (1,000 - 1,000,000 per listing); "
                "buyer opens an order reserving G$, pays off-chain, then the seller "
                "(Approve = releaseOrder) or owner (admin review) releases G$ to the buyer. "
                "Owner == deployer (P2P_KEY) == arbiter, used only for admin review / disputes."
            ),
            "abi": compiled["abi"]
        }

        out = os.path.join(os.path.dirname(__file__), 'p2p_escrow_deployment_info.json')
        with open(out, 'w') as f:
            json.dump(deployment_info, f, indent=2)

        logger.info(f"Deployment info saved to: {out}")
        logger.info("\nSet this env variable:")
        logger.info(f"  P2P_ESCROW_CONTRACT_ADDRESS={contract_address}")

        return deployment_info
    else:
        logger.error("Deployment failed!")
        return None


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("P2PEscrow Contract Deployment - Celo Mainnet")
    logger.info("=" * 60)
    result = deploy_contract()
    if result:
        logger.info("\nDEPLOYMENT SUCCESSFUL!")
        logger.info(f"Contract:  {result['contract_address']}")
        logger.info(f"Deployer:  {result['deployer']}")
        logger.info(f"Set env:   P2P_ESCROW_CONTRACT_ADDRESS={result['contract_address']}")
    else:
        logger.error("Deployment failed.")
