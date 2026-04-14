"""
GDSavings Contract Deployment Script for Celo Mainnet (v2)

Deploys the GDSavings time-locked savings vault (no owner, no pause).

Features:
  - Users lock G$ for 1 day up to 365 days
  - Min deposit: 1,000 G$ | Max: 10,000,000 G$
  - Tiered optional bonus (requires >= 150-day lock, funded reward pool):
      10,000 –  99,999 G$  →  1,000 G$
     100,000 – 499,999 G$  →  2,500 G$
     500,000 – 10,000,000 G$ → 10,000 G$
  - Sponsors can fund the reward pool; those funds can never be withdrawn
  - No owner, no pause/unpause — fully trustless savings vault
  - Only the depositor can ever withdraw their own funds
"""

import os
import json
import logging
from web3 import Web3
from eth_account import Account
from solcx import compile_standard, install_solc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CELO_RPC_URL = os.getenv('CELO_RPC_URL', 'https://forno.celo.org')
CHAIN_ID = int(os.getenv('CHAIN_ID', 42220))
GOODDOLLAR_CONTRACT = os.getenv('GOODDOLLAR_CONTRACT_ADDRESS', '0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A')

FLATTENED_SOURCE = open(os.path.join(os.path.dirname(__file__), 'GDSavings.sol')).read()


def compile_contract():
    logger.info("Installing Solidity compiler v0.8.21...")
    install_solc('0.8.21')
    logger.info("Compiling GDSavings contract...")

    compiled = compile_standard({
        "language": "Solidity",
        "sources": {
            "GDSavings.sol": {"content": FLATTENED_SOURCE}
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

    contract_data = compiled["contracts"]["GDSavings.sol"]["GDSavings"]
    return {
        "abi": contract_data["abi"],
        "bytecode": contract_data["evm"]["bytecode"]["object"]
    }


def deploy_contract():
    saving_key = os.getenv('SAVING_KEY')

    if not saving_key:
        logger.error("SAVING_KEY not set!")
        return None

    if not GOODDOLLAR_CONTRACT:
        logger.error("GOODDOLLAR_CONTRACT_ADDRESS not set!")
        return None

    w3 = Web3(Web3.HTTPProvider(CELO_RPC_URL))
    if not w3.is_connected():
        logger.error("Failed to connect to Celo network")
        return None

    logger.info(f"Connected to Celo Mainnet (Chain ID: {CHAIN_ID})")

    key = saving_key if saving_key.startswith('0x') else '0x' + saving_key
    account = Account.from_key(key)
    logger.info(f"Deploying from SAVING_KEY address: {account.address}")

    celo_balance = w3.eth.get_balance(account.address)
    celo_human = w3.from_wei(celo_balance, 'ether')
    logger.info(f"CELO balance: {celo_human} CELO")

    if celo_balance < w3.to_wei(0.05, 'ether'):
        logger.error(f"Insufficient CELO for gas (need ~0.05, have {celo_human}). Top up the SAVING_KEY address.")
        return None

    compiled = compile_contract()

    contract = w3.eth.contract(
        abi=compiled["abi"],
        bytecode=compiled["bytecode"]
    )

    nonce = w3.eth.get_transaction_count(account.address)
    gas_price = int(w3.eth.gas_price * 1.2)

    constructor_txn = contract.constructor(
        Web3.to_checksum_address(GOODDOLLAR_CONTRACT)
    ).build_transaction({
        'chainId': CHAIN_ID,
        'gas': 3_000_000,
        'gasPrice': gas_price,
        'nonce': nonce,
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
        logger.info(f"✅ Contract deployed: {contract_address}")
        logger.info(f"   CeloScan: https://celoscan.io/address/{contract_address}")
        logger.info(f"   Gas used: {receipt.gasUsed}")

        deployment_info = {
            "contract_name": "GDSavings",
            "version": "2",
            "contract_address": contract_address,
            "tx_hash": tx_hash_hex,
            "deployer": account.address,
            "gooddollar_token": GOODDOLLAR_CONTRACT,
            "chain_id": CHAIN_ID,
            "network": "Celo Mainnet",
            "block_number": receipt.blockNumber,
            "gas_used": receipt.gasUsed,
            "compiler_version": "v0.8.21+commit.d9974bed",
            "optimization": True,
            "optimization_runs": 200,
            "notes": "No owner, no pause. Reward pool is trustless — funds can only be used for user bonuses.",
            "abi": compiled["abi"]
        }

        out = os.path.join(os.path.dirname(__file__), 'savings_deployment_info.json')
        with open(out, 'w') as f:
            json.dump(deployment_info, f, indent=2)

        logger.info(f"Deployment info saved to: {out}")
        logger.info(f"\nSet this env variable:")
        logger.info(f"  SAVINGS_CONTRACT_ADDRESS={contract_address}")

        return deployment_info
    else:
        logger.error("❌ Deployment failed!")
        return None


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("GDSavings Contract Deployment — Celo Mainnet")
    logger.info("=" * 60)
    result = deploy_contract()
    if result:
        logger.info("\n✅ DEPLOYMENT SUCCESSFUL!")
        logger.info(f"Contract:  {result['contract_address']}")
        logger.info(f"Deployer:  {result['deployer']}")
        logger.info(f"Set env:   SAVINGS_CONTRACT_ADDRESS={result['contract_address']}")
    else:
        logger.error("Deployment failed.")
