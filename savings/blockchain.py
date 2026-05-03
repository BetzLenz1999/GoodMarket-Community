"""
G$ Savings blockchain service.
All on-chain reads. Withdrawals and deposits happen directly from the user's wallet (frontend).

Contract mechanics (v3 — multi-token, slot-based):
  - Tokens accepted: G$, CELO, cUSD
  - One slot per (user, token, lockDays). Top-ups inherit the slot's
    original unlocksAt (no lock extension).
  - Lock durations (days): 1, 30, 60, 90, 120, 150, 180, 210, 240, 270,
    300, 330, 365.
  - Per-token min/max (18-decimal units):
      G$:   1,000        – 10,000,000
      CELO: 1            – 100,000
      cUSD: 1            – 1,000,000
  - Bonus tiers (always paid in G$, regardless of deposit token):
      1-day lock, ≥ token MIN → 10 G$
      ≥150-day lock, by token amount:
        G$:   10k–100k → 1k G$ | 100k–500k → 2.5k G$ | 500k–10M → 10k G$
        CELO: 10–100   → 1k G$ |   100–500 → 2.5k G$ |   500–100k → 10k G$
        cUSD: 10–100   → 1k G$ |   100–500 → 2.5k G$ |   500–1M  → 10k G$
  - Bonus only paid if reward pool has sufficient G$ (optional / trustless).
  - No owner, no pause, no early withdrawal.
"""
import os
import logging
from web3 import Web3

logger = logging.getLogger(__name__)

CELO_RPC_URL = os.getenv('CELO_RPC_URL', 'https://forno.celo.org')
CHAIN_ID = int(os.getenv('CHAIN_ID', 42220))
SAVINGS_CONTRACT_ADDRESS = os.getenv('SAVINGS_CONTRACT_ADDRESS', '')
GD_TOKEN_ADDRESS = os.getenv('GOODDOLLAR_CONTRACT_ADDRESS', '0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A')
CELO_TOKEN_ADDRESS = os.getenv('CELO_TOKEN_ADDRESS', '0x471EcE3750Da237f93B8E339c536989b8978a438')
CUSD_TOKEN_ADDRESS = os.getenv('CUSD_TOKEN_ADDRESS', '0x765DE816845861e75A25fCA122bb6898B8B1282a')

# Map of supported tokens, used by the frontend / API to label slots.
SUPPORTED_TOKENS = {
    GD_TOKEN_ADDRESS.lower():   {"symbol": "G$",   "decimals": 18},
    CELO_TOKEN_ADDRESS.lower(): {"symbol": "CELO", "decimals": 18},
    CUSD_TOKEN_ADDRESS.lower(): {"symbol": "cUSD", "decimals": 18},
}


def _token_meta(addr):
    if not addr:
        return {"symbol": "?", "decimals": 18}
    return SUPPORTED_TOKENS.get(addr.lower(), {"symbol": "?", "decimals": 18})


SAVINGS_ABI = [
    # ── Constructor ──────────────────────────────────────────────────────
    {
        "inputs": [
            {"internalType": "address", "name": "_gd",        "type": "address"},
            {"internalType": "address", "name": "_celoToken", "type": "address"},
            {"internalType": "address", "name": "_cusd",      "type": "address"},
        ],
        "stateMutability": "nonpayable",
        "type": "constructor",
    },
    # ── Write functions ──────────────────────────────────────────────────
    {
        "inputs": [
            {"internalType": "address", "name": "token",    "type": "address"},
            {"internalType": "uint256", "name": "amount",   "type": "uint256"},
            {"internalType": "uint256", "name": "lockDays", "type": "uint256"},
        ],
        "name": "depositSavings",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "token",    "type": "address"},
            {"internalType": "uint256", "name": "lockDays", "type": "uint256"},
        ],
        "name": "withdraw",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "amount", "type": "uint256"}],
        "name": "fundRewardPool",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # ── View: slot details ───────────────────────────────────────────────
    {
        "inputs": [
            {"internalType": "address", "name": "user",     "type": "address"},
            {"internalType": "address", "name": "token",    "type": "address"},
            {"internalType": "uint256", "name": "lockDays", "type": "uint256"},
        ],
        "name": "getSlot",
        "outputs": [
            {"internalType": "uint256", "name": "amount",         "type": "uint256"},
            {"internalType": "uint256", "name": "firstDepositAt", "type": "uint256"},
            {"internalType": "uint256", "name": "unlocksAt",      "type": "uint256"},
            {"internalType": "bool",    "name": "bonusClaimed",   "type": "bool"},
            {"internalType": "bool",    "name": "isUnlocked",     "type": "bool"},
            {"internalType": "uint256", "name": "pendingBonus",   "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "user", "type": "address"}],
        "name": "getUserSlotRefs",
        "outputs": [
            {
                "components": [
                    {"internalType": "address", "name": "token",    "type": "address"},
                    {"internalType": "uint256", "name": "lockDays", "type": "uint256"},
                ],
                "internalType": "struct GDSavings.SlotRef[]",
                "name": "",
                "type": "tuple[]",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "user", "type": "address"}],
        "name": "getUserActiveSlots",
        "outputs": [
            {"internalType": "address[]", "name": "tokens",         "type": "address[]"},
            {"internalType": "uint256[]", "name": "lockDays_",      "type": "uint256[]"},
            {"internalType": "uint256[]", "name": "amounts",        "type": "uint256[]"},
            {"internalType": "uint256[]", "name": "unlocksAts",     "type": "uint256[]"},
            {"internalType": "bool[]",    "name": "areUnlocked",    "type": "bool[]"},
            {"internalType": "bool[]",    "name": "bonusClaimed",   "type": "bool[]"},
            {"internalType": "uint256[]", "name": "pendingBonuses", "type": "uint256[]"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    # ── View: contract stats ─────────────────────────────────────────────
    {
        "inputs": [],
        "name": "getContractStats",
        "outputs": [
            {"internalType": "uint256", "name": "totalLockedGd",       "type": "uint256"},
            {"internalType": "uint256", "name": "totalLockedCelo",     "type": "uint256"},
            {"internalType": "uint256", "name": "totalLockedCusd",     "type": "uint256"},
            {"internalType": "uint256", "name": "rewardPoolBalance",   "type": "uint256"},
            {"internalType": "uint256", "name": "contractGdBalance",   "type": "uint256"},
            {"internalType": "uint256", "name": "contractCeloBalance", "type": "uint256"},
            {"internalType": "uint256", "name": "contractCusdBalance", "type": "uint256"},
            {"internalType": "uint256", "name": "slotsOpenedTotal",    "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    # ── View: bonus calculator ───────────────────────────────────────────
    {
        "inputs": [
            {"internalType": "address", "name": "token",    "type": "address"},
            {"internalType": "uint256", "name": "amount",   "type": "uint256"},
            {"internalType": "uint256", "name": "lockDays", "type": "uint256"},
        ],
        "name": "getBonusAmount",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "token", "type": "address"}],
        "name": "getMinMax",
        "outputs": [
            {"internalType": "uint256", "name": "minA", "type": "uint256"},
            {"internalType": "uint256", "name": "maxA", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "token", "type": "address"}],
        "name": "isAllowedToken",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getValidDurations",
        "outputs": [{"internalType": "uint16[13]", "name": "", "type": "uint16[13]"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getTokens",
        "outputs": [
            {"internalType": "address", "name": "gdAddr",   "type": "address"},
            {"internalType": "address", "name": "celoAddr", "type": "address"},
            {"internalType": "address", "name": "cusdAddr", "type": "address"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    # ── View: state vars ─────────────────────────────────────────────────
    {"inputs": [], "name": "rewardPool",
     "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "totalSlotsOpened",
     "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "gd",
     "outputs": [{"internalType": "address", "name": "", "type": "address"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "celoToken",
     "outputs": [{"internalType": "address", "name": "", "type": "address"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "cusd",
     "outputs": [{"internalType": "address", "name": "", "type": "address"}],
     "stateMutability": "view", "type": "function"},
]

ERC20_ABI = [
    {
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "owner",   "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount",  "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


def get_w3():
    return Web3(Web3.HTTPProvider(CELO_RPC_URL))


def get_savings_contract(w3):
    if not SAVINGS_CONTRACT_ADDRESS:
        raise ValueError("SAVINGS_CONTRACT_ADDRESS not set")
    return w3.eth.contract(
        address=Web3.to_checksum_address(SAVINGS_CONTRACT_ADDRESS),
        abi=SAVINGS_ABI,
    )


def get_erc20_contract(w3, token_address):
    return w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=ERC20_ABI,
    )


def get_gd_contract(w3):
    """Backwards-compatible helper for callers that only need the G$ token."""
    return get_erc20_contract(w3, GD_TOKEN_ADDRESS)


def get_contract_stats():
    """Return high-level stats about the savings vault."""
    try:
        w3 = get_w3()
        contract = get_savings_contract(w3)
        s = contract.functions.getContractStats().call()
        (
            total_locked_gd_raw,
            total_locked_celo_raw,
            total_locked_cusd_raw,
            reward_pool_raw,
            contract_gd_raw,
            contract_celo_raw,
            contract_cusd_raw,
            slots_opened,
        ) = s
        return {
            "total_locked_gd":      str(total_locked_gd_raw),
            "total_locked_gd_h":    float(Web3.from_wei(total_locked_gd_raw,   'ether')),
            "total_locked_celo":    str(total_locked_celo_raw),
            "total_locked_celo_h":  float(Web3.from_wei(total_locked_celo_raw, 'ether')),
            "total_locked_cusd":    str(total_locked_cusd_raw),
            "total_locked_cusd_h":  float(Web3.from_wei(total_locked_cusd_raw, 'ether')),
            "reward_pool":          str(reward_pool_raw),
            "reward_pool_gd":       float(Web3.from_wei(reward_pool_raw, 'ether')),
            "contract_gd_balance":  str(contract_gd_raw),
            "contract_celo_balance":str(contract_celo_raw),
            "contract_cusd_balance":str(contract_cusd_raw),
            "total_slots_opened":   slots_opened,
            "contract_address":     SAVINGS_CONTRACT_ADDRESS,
            "tokens": {
                "gd":   GD_TOKEN_ADDRESS,
                "celo": CELO_TOKEN_ADDRESS,
                "cusd": CUSD_TOKEN_ADDRESS,
            },
        }
    except Exception as e:
        logger.error(f"get_contract_stats error: {e}")
        return None


def get_user_deposits(wallet_address):
    """Return all active slots for a given wallet address.

    Each entry represents one (token, lockDays) slot with its current
    aggregated `amount` and the slot's `unlocks_at` (which never moves
    after the first deposit, even if the user tops up later).
    """
    try:
        w3 = get_w3()
        contract = get_savings_contract(w3)
        addr = Web3.to_checksum_address(wallet_address)
        (
            tokens,
            lock_days_list,
            amounts,
            unlocks_ats,
            are_unlocked,
            bonus_claimeds,
            pending_bonuses,
        ) = contract.functions.getUserActiveSlots(addr).call()

        result = []
        for i in range(len(tokens)):
            token_addr = tokens[i]
            meta = _token_meta(token_addr)
            result.append({
                "token":             token_addr,
                "token_symbol":      meta["symbol"],
                "token_decimals":    meta["decimals"],
                "lock_days":         lock_days_list[i],
                "amount":            str(amounts[i]),
                "amount_h":          float(Web3.from_wei(amounts[i], 'ether')),
                "unlocks_at":        unlocks_ats[i],
                "is_unlocked":       are_unlocked[i],
                "bonus_claimed":     bonus_claimeds[i],
                "pending_bonus":     str(pending_bonuses[i]),
                "pending_bonus_gd":  float(Web3.from_wei(pending_bonuses[i], 'ether')),
            })
        return result
    except Exception as e:
        logger.error(f"get_user_deposits error: {e}")
        return []


def get_token_allowance(wallet_address, token_address):
    """Check how much `token_address` the user has approved for the savings contract."""
    try:
        w3 = get_w3()
        token = get_erc20_contract(w3, token_address)
        addr = Web3.to_checksum_address(wallet_address)
        savings_addr = Web3.to_checksum_address(SAVINGS_CONTRACT_ADDRESS)
        return token.functions.allowance(addr, savings_addr).call()
    except Exception as e:
        logger.error(f"get_token_allowance({token_address}) error: {e}")
        return 0


def get_gd_allowance(wallet_address):
    """Backwards-compatible: G$ allowance for the savings contract."""
    return get_token_allowance(wallet_address, GD_TOKEN_ADDRESS)


def get_user_token_balances(wallet_address):
    """Return the user's balances for all three supported tokens."""
    try:
        w3 = get_w3()
        addr = Web3.to_checksum_address(wallet_address)
        out = {}
        for key, token_addr in (("gd", GD_TOKEN_ADDRESS), ("celo", CELO_TOKEN_ADDRESS), ("cusd", CUSD_TOKEN_ADDRESS)):
            try:
                token = get_erc20_contract(w3, token_addr)
                bal = token.functions.balanceOf(addr).call()
                allowance = token.functions.allowance(addr, Web3.to_checksum_address(SAVINGS_CONTRACT_ADDRESS)).call() if SAVINGS_CONTRACT_ADDRESS else 0
                out[key] = {
                    "address":     token_addr,
                    "balance":     str(bal),
                    "balance_h":   float(Web3.from_wei(bal, 'ether')),
                    "allowance":   str(allowance),
                    "allowance_h": float(Web3.from_wei(allowance, 'ether')),
                }
            except Exception as inner:
                logger.warning(f"balance fetch failed for {key}: {inner}")
                out[key] = {"address": token_addr, "balance": "0", "balance_h": 0.0, "allowance": "0", "allowance_h": 0.0}
        return out
    except Exception as e:
        logger.error(f"get_user_token_balances error: {e}")
        return {}
