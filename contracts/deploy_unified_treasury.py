"""
UnifiedTreasury Contract Deployment Script for Celo Mainnet

Deploys the UnifiedTreasury contract which:
  - Accepts G$ deposits from anyone
  - Only allows LEARN_WALLET_PRIVATE_KEY to distribute funds
  - Recipient addresses are hardcoded at deploy time (derived from existing keys)

Recipients:
  1. Learn & Earn Contract   (LEARN_EARN_CONTRACT_ADDRESS)
  2. Daily Task Contract     (DAILY_TASK_CONTRACT_ADDRESS)
  3. Discourse Wallet        (derived from DISCOURSE_TASK_KEY)
  4. Minigames Wallet        (derived from GAMES_KEY)
  5. Community Stories Wallet(derived from COMMUNITY_KEY)
  6. Referral Wallet         (derived from REFERRAL_KEY)

Authorized Signer: LEARN_WALLET_PRIVATE_KEY
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
GOODDOLLAR_TOKEN = os.getenv('GOODDOLLAR_CONTRACT_ADDRESS', '0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A')

SOL_FILE = os.path.join(os.path.dirname(__file__), 'UnifiedTreasury.sol')


def derive_address(private_key_hex: str) -> str:
    key = private_key_hex if private_key_hex.startswith('0x') else '0x' + private_key_hex
    account = Account.from_key(key)
    return account.address


def compile_contract():
    logger.info("Installing Solidity compiler v0.8.21...")
    install_solc('0.8.21')
    logger.info("Compiling UnifiedTreasury contract...")

    source = open(SOL_FILE).read()

    compiled = compile_standard({
        "language": "Solidity",
        "sources": {
            "UnifiedTreasury.sol": {"content": source}
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

    contract_data = compiled["contracts"]["UnifiedTreasury.sol"]["UnifiedTreasury"]
    logger.info("✅ Compilation successful")
    return {
        "abi": contract_data["abi"],
        "bytecode": contract_data["evm"]["bytecode"]["object"]
    }


def deploy_contract():
    # ── Load deployer key (LEARN_WALLET_PRIVATE_KEY) ──────────────────────────
    learn_key = os.getenv('LEARN_WALLET_PRIVATE_KEY')
    if not learn_key:
        logger.error("❌ LEARN_WALLET_PRIVATE_KEY not set!")
        return None

    # ── Derive all recipient wallet addresses from private keys ────────────────
    discourse_key = os.getenv('DISCOURSE_TASK_KEY')
    games_key     = os.getenv('GAMES_KEY')
    community_key = os.getenv('COMMUNITY_KEY')
    referral_key  = os.getenv('REFERRAL_KEY')

    if not all([discourse_key, games_key, community_key, referral_key]):
        logger.error("❌ One or more private keys missing: DISCOURSE_TASK_KEY, GAMES_KEY, COMMUNITY_KEY, REFERRAL_KEY")
        return None

    # ── Load hardcoded contract addresses ─────────────────────────────────────
    learn_earn_contract  = os.getenv('LEARN_EARN_CONTRACT_ADDRESS')
    daily_task_contract  = os.getenv('DAILY_TASK_CONTRACT_ADDRESS')

    if not learn_earn_contract or not daily_task_contract:
        logger.error("❌ LEARN_EARN_CONTRACT_ADDRESS or DAILY_TASK_CONTRACT_ADDRESS not set!")
        return None

    # Derive wallet addresses
    authorized_signer     = derive_address(learn_key)
    discourse_wallet      = derive_address(discourse_key)
    minigames_wallet      = derive_address(games_key)
    community_wallet      = derive_address(community_key)
    referral_wallet       = derive_address(referral_key)

    logger.info("📋 Deployment Configuration:")
    logger.info(f"   Authorized Signer (LEARN_WALLET): {authorized_signer}")
    logger.info(f"   Learn & Earn Contract:            {learn_earn_contract}")
    logger.info(f"   Daily Task Contract:              {daily_task_contract}")
    logger.info(f"   Discourse Wallet:                 {discourse_wallet}")
    logger.info(f"   Minigames Wallet:                 {minigames_wallet}")
    logger.info(f"   Community Stories Wallet:         {community_wallet}")
    logger.info(f"   Referral Wallet:                  {referral_wallet}")
    logger.info(f"   G$ Token:                         {GOODDOLLAR_TOKEN}")

    # ── Connect to Celo ───────────────────────────────────────────────────────
    w3 = Web3(Web3.HTTPProvider(CELO_RPC_URL))
    if not w3.is_connected():
        logger.error("❌ Failed to connect to Celo network")
        return None

    logger.info(f"✅ Connected to Celo Mainnet (Chain ID: {CHAIN_ID})")

    key_hex = learn_key if learn_key.startswith('0x') else '0x' + learn_key
    account = Account.from_key(key_hex)

    balance_wei = w3.eth.get_balance(account.address)
    balance_celo = w3.from_wei(balance_wei, 'ether')
    logger.info(f"💰 Deployer CELO balance: {balance_celo:.4f} CELO")

    if balance_celo < 0.01:
        logger.error("❌ Insufficient CELO for gas fees. Top up the LEARN_WALLET address.")
        return None

    # ── Compile ───────────────────────────────────────────────────────────────
    contract_data = compile_contract()

    # ── Deploy ────────────────────────────────────────────────────────────────
    contract = w3.eth.contract(
        abi=contract_data["abi"],
        bytecode=contract_data["bytecode"]
    )

    nonce = w3.eth.get_transaction_count(account.address)
    gas_price = w3.eth.gas_price
    logger.info(f"⛽ Gas price: {w3.from_wei(gas_price, 'gwei'):.2f} Gwei")

    constructor_tx = contract.constructor(
        GOODDOLLAR_TOKEN,
        authorized_signer,
        Web3.to_checksum_address(learn_earn_contract),
        Web3.to_checksum_address(daily_task_contract),
        discourse_wallet,
        minigames_wallet,
        community_wallet,
        referral_wallet
    ).build_transaction({
        'from':     account.address,
        'nonce':    nonce,
        'gas':      3_000_000,
        'gasPrice': gas_price,
        'chainId':  CHAIN_ID,
    })

    logger.info("✍️  Signing transaction with LEARN_WALLET_PRIVATE_KEY...")
    signed_tx = account.sign_transaction(constructor_tx)

    logger.info("📡 Broadcasting deployment transaction...")
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    logger.info(f"📨 Tx hash: {tx_hash.hex()}")
    logger.info("⏳ Waiting for confirmation...")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

    if receipt.status != 1:
        logger.error("❌ Deployment transaction failed!")
        return None

    contract_address = receipt.contractAddress
    logger.info(f"✅ UnifiedTreasury deployed at: {contract_address}")
    logger.info(f"   Block:    {receipt.blockNumber}")
    logger.info(f"   Gas used: {receipt.gasUsed:,}")

    # ── Save deployment info ──────────────────────────────────────────────────
    source_code = open(SOL_FILE).read()
    deployment_info = {
        "contract_name":            "UnifiedTreasury",
        "contract_address":         contract_address,
        "tx_hash":                  tx_hash.hex(),
        "authorized_signer":        authorized_signer,
        "gooddollar_token":         GOODDOLLAR_TOKEN,
        "recipients": {
            "learn_earn":           learn_earn_contract,
            "daily_task":           daily_task_contract,
            "discourse":            discourse_wallet,
            "minigames":            minigames_wallet,
            "community_stories":    community_wallet,
            "referral":             referral_wallet,
        },
        "chain_id":                 CHAIN_ID,
        "network":                  "Celo Mainnet",
        "block_number":             receipt.blockNumber,
        "gas_used":                 receipt.gasUsed,
        "compiler_version":         "v0.8.21",
        "optimization":             True,
        "optimization_runs":        200,
        "source_code":              source_code,
        "abi":                      contract_data["abi"],
    }

    output_path = os.path.join(os.path.dirname(__file__), 'unified_treasury_deployment.json')
    with open(output_path, 'w') as f:
        json.dump(deployment_info, f, indent=2)

    logger.info(f"💾 Deployment info saved to: {output_path}")

    logger.info("")
    logger.info("=" * 60)
    logger.info("🎉 UnifiedTreasury Deployment Complete!")
    logger.info("=" * 60)
    logger.info(f"Contract Address:  {contract_address}")
    logger.info(f"Network:           Celo Mainnet")
    logger.info(f"Authorized Signer: {authorized_signer}")
    logger.info("")
    logger.info("Recipients (hardcoded):")
    logger.info(f"  learn_earn:        {learn_earn_contract}")
    logger.info(f"  daily_task:        {daily_task_contract}")
    logger.info(f"  discourse:         {discourse_wallet}")
    logger.info(f"  minigames:         {minigames_wallet}")
    logger.info(f"  community_stories: {community_wallet}")
    logger.info(f"  referral:          {referral_wallet}")
    logger.info("=" * 60)
    logger.info("")
    logger.info("⚠️  NEXT STEP: Add this to your Replit Secrets:")
    logger.info(f"   UNIFIED_TREASURY_ADDRESS = {contract_address}")

    return deployment_info


if __name__ == "__main__":
    result = deploy_contract()
    if result:
        logger.info("✅ Deployment successful!")
    else:
        logger.error("❌ Deployment failed!")
        exit(1)
