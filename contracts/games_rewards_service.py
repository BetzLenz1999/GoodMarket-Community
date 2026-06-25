"""
GamesRewards Blockchain Service
=============================

Updated service to use the GamesRewards smart contract instead of direct private key transfers.

Usage:
1. Deploy GamesRewards.sol contract using Remix
2. Update CONTRACT_ADDRESS with deployed address
3. Authorize your server address as disburser
4. Fund the contract with G$ tokens

REQUIREMENTS:
- Contract deployed and funded
- Server wallet authorized as disburser
- No need for GAMES_KEY private key anymore!
"""

import os
import logging
from web3 import Web3
from datetime import datetime

logger = logging.getLogger(__name__)

# ============================================
# CONFIGURATION - UPDATE THESE VALUES
# ============================================

# RPC Configuration
CELO_RPC_URL = os.getenv('CELO_RPC_URL', 'https://forno.celo.org')
CHAIN_ID = int(os.getenv('CHAIN_ID', 42220))

# G$ Token Contract (DO NOT CHANGE)
G$DOLLAR_TOKEN = os.getenv('GOODDOLLAR_CONTRACT', '0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A')

# ============================================
# NEW: GamesRewards Contract Configuration
# ============================================

# UPDATE THIS AFTER DEPLOYMENT
GAMES_REWARDS_CONTRACT = os.getenv('GAMES_REWARDS_CONTRACT', 'YOUR_CONTRACT_ADDRESS_HERE')

# Server wallet that is authorized to call disbursement
# This wallet needs to be authorized in the contract
SERVER_WALLET_ADDRESS = os.getenv('SERVER_WALLET_ADDRESS', 'YOUR_SERVER_ADDRESS_HERE')

# Server private key for signing transactions
# IMPORTANT: This is LESS risky than GAMES_KEY because:
# 1. The server can only disburse up to dailyLimit per user
# 2. The contract has pause functionality
# 3. All disbursements are logged as events
SERVER_PRIVATE_KEY = os.getenv('SERVER_PRIVATE_KEY', 'YOUR_SERVER_PRIVATE_KEY_HERE')

# ============================================
# CONTRACT ABI
# ============================================

GAMES_REWARDS_ABI = [
    # Core disbursement function
    {
        "inputs": [
            {"name": "recipient", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "sessionId", "type": "string"}
        ],
        "name": "disburseReward",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # Batch disbursement
    {
        "inputs": [
            {"name": "recipients", "type": "address[]"},
            {"name": "amounts", "type": "uint256[]"},
            {"name": "sessionIds", "type": "string[]"}
        ],
        "name": "batchDisburse",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # View functions
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "getRemainingDailyLimit",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "getUserStats",
        "outputs": [
            {"name": "total", "type": "uint256"},
            {"name": "dailyToday", "type": "uint256"},
            {"name": "lastClaim", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "getContractBalance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "dailyLimitPerUser",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "totalRewardsDisbursed",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "paused",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "owner",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    # Owner functions (for admin)
    {
        "inputs": [{"name": "newOwner", "type": "address"}],
        "name": "transferOwnership",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "disburser", "type": "address"},
            {"name": "authorized", "type": "bool"}
        ],
        "name": "setAuthorizedDisburser",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"name": "newLimit", "type": "uint256"}],
        "name": "updateDailyLimit",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"name": "_paused", "type": "bool"}],
        "name": "setPaused",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "recipient", "type": "address"},
            {"name": "amount", "type": "uint256"}
        ],
        "name": "withdrawTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
]

# ERC20 ABI for balance checks
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    }
]


class GamesRewardsContractService:
    """Service for interacting with GamesRewards smart contract"""
    
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(CELO_RPC_URL))
        
        if not self.w3.is_connected():
            logger.error("Failed to connect to Celo network")
            raise ConnectionError("Cannot connect to Celo network")
        
        logger.info("Connected to Celo network")
        
        # Initialize contract
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(GAMES_REWARDS_CONTRACT),
            abi=GAMES_REWARDS_ABI
        )
        
        # Initialize token contract for balance checks
        self.token = self.w3.eth.contract(
            address=Web3.to_checksum_address(G$DOLLAR_TOKEN),
            abi=ERC20_ABI
        )
        
        # Server wallet
        if SERVER_PRIVATE_KEY and SERVER_PRIVATE_KEY != 'YOUR_SERVER_PRIVATE_KEY_HERE':
            if not SERVER_PRIVATE_KEY.startswith('0x'):
                SERVER_PRIVATE_KEY = '0x' + SERVER_PRIVATE_KEY
            self.server_account = self.w3.eth.account.from_key(SERVER_PRIVATE_KEY)
            self.server_address = self.server_account.address
            # Store the cleaned key for signing (Account.key is bytes, not hex string)
            self._server_key = SERVER_PRIVATE_KEY
        else:
            self.server_account = None
            self.server_address = None
            logger.warning("SERVER_PRIVATE_KEY not configured")
        
        logger.info(f"GamesRewards Contract: {GAMES_REWARDS_CONTRACT}")
        logger.info(f"Server Address: {self.server_address}")
    
    def mask_wallet(self, address: str) -> str:
        """Mask wallet for logging"""
        if not address or len(address) < 10:
            return address
        return address[:6] + "..." + address[-4:]
    
    async def disburse_reward(
        self, 
        wallet_address: str, 
        amount: float, 
        game_type: str, 
        session_id: str
    ) -> dict:
        """
        Disburse reward using smart contract
        
        Args:
            wallet_address: Recipient wallet
            amount: Amount in G$ (not wei)
            game_type: Type of game (for logging)
            session_id: Session ID for tracking
        """
        try:
            logger.info(f"🎮 Contract disbursement: {amount} G$ to {self.mask_wallet(wallet_address)}")
            
            if not self.server_account:
                return {"success": False, "error": "Server wallet not configured"}
            
            # Check contract status
            is_paused = self.contract.functions.paused().call()
            if is_paused:
                return {"success": False, "error": "Contract is paused"}
            
            # Check remaining daily limit
            amount_wei = int(amount * (10 ** 18))
            remaining = self.contract.functions.getRemainingDailyLimit(
                Web3.to_checksum_address(wallet_address)
            ).call()
            
            if amount_wei > remaining:
                return {
                    "success": False, 
                    "error": f"Daily limit exceeded. Remaining: {remaining / (10**18):.2f} G$"
                }
            
            # Build transaction
            nonce = self.w3.eth.get_transaction_count(self.server_address)
            gas_price = int(self.w3.eth.gas_price * 1.2)
            
            # Estimate gas
            try:
                estimated_gas = self.contract.functions.disburseReward(
                    Web3.to_checksum_address(wallet_address),
                    amount_wei,
                    session_id
                ).estimate_gas({'from': self.server_address})
                gas_limit = int(estimated_gas * 1.3)
            except:
                gas_limit = 200000
            
            # Build and sign transaction
            txn = self.contract.functions.disburseReward(
                Web3.to_checksum_address(wallet_address),
                amount_wei,
                session_id
            ).build_transaction({
                'from': self.server_address,
                'nonce': nonce,
                'gas': gas_limit,
                'gasPrice': gas_price,
                'chainId': CHAIN_ID
            })
            
            signed = self.w3.eth.account.sign_transaction(txn, private_key=self._server_key)
            
            # Send transaction
            logger.info("📡 Sending contract transaction...")
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            tx_hash_hex = tx_hash.hex()
            
            if not tx_hash_hex.startswith('0x'):
                tx_hash_hex = '0x' + tx_hash_hex
            
            # Wait for confirmation
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt.status == 1:
                logger.info(f"✅ Reward disbursed: {amount} G$ - TX: {tx_hash_hex}")
                explorer_url = f"https://explorer.celo.org/mainnet/tx/{tx_hash_hex}"
                
                return {
                    "success": True,
                    "tx_hash": tx_hash_hex,
                    "amount": amount,
                    "game_type": game_type,
                    "session_id": session_id,
                    "recipient": wallet_address,
                    "explorer_url": explorer_url,
                    "contract_address": GAMES_REWARDS_CONTRACT,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {"success": False, "error": "Transaction failed", "tx_hash": tx_hash_hex}
        
        except Exception as e:
            logger.error(f"❌ Disbursement error: {e}")
            return {"success": False, "error": str(e)}
    
    def get_user_claimable(self, wallet_address: str) -> float:
        """Get remaining daily claimable amount for user"""
        try:
            remaining_wei = self.contract.functions.getRemainingDailyLimit(
                Web3.to_checksum_address(wallet_address)
            ).call()
            return remaining_wei / (10 ** 18)
        except Exception as e:
            logger.error(f"Error getting claimable: {e}")
            return 0.0
    
    def get_contract_balance(self) -> float:
        """Get contract G$ balance"""
        try:
            balance_wei = self.contract.functions.getContractBalance().call()
            return balance_wei / (10 ** 18)
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return 0.0
    
    def get_total_disbursed(self) -> float:
        """Get total rewards disbursed"""
        try:
            total_wei = self.contract.functions.totalRewardsDisbursed().call()
            return total_wei / (10 ** 18)
        except Exception as e:
            logger.error(f"Error getting total: {e}")
            return 0.0
    
    def get_stats(self, wallet_address: str) -> dict:
        """Get user stats from contract"""
        try:
            total, daily, last = self.contract.functions.getUserStats(
                Web3.to_checksum_address(wallet_address)
            ).call()
            return {
                "total_claimed": total / (10 ** 18),
                "claimed_today": daily / (10 ** 18),
                "remaining_today": (total - daily) / (10 ** 18) if total > daily else 0,
                "last_claim": datetime.fromtimestamp(last).isoformat() if last > 0 else None
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}


# For backward compatibility with existing code
# You can replace minigames_blockchain with this service
games_rewards_contract = None

def init_games_rewards_contract():
    """Initialize the contract service"""
    global games_rewards_contract
    try:
        games_rewards_contract = GamesRewardsContractService()
        logger.info("GamesRewards contract service initialized")
    except Exception as e:
        logger.error(f"Failed to initialize: {e}")
        games_rewards_contract = None
    return games_rewards_contract
