
import os
import logging
from web3 import Web3
from eth_account import Account
from config import DAILY_TASK_CONTRACT_ADDRESS as _CONFIG_DAILY_TASK_ADDRESS

logger = logging.getLogger(__name__)

def _decode_revert_reason(data: bytes) -> str:
    """Decode revert reason from raw bytes returned by eth_call"""
    try:
        if not data or data == b'':
            return "No revert reason returned"
        # Standard ABI-encoded revert: 0x08c379a0 + offset + length + string
        if data[:4] == bytes.fromhex('08c379a0'):
            reason = data[4:]
            # Skip 32-byte offset, read 32-byte length, then read string
            length = int.from_bytes(reason[32:64], 'big')
            return reason[64:64 + length].decode('utf-8', errors='replace')
        # Panic
        if data[:4] == bytes.fromhex('4e487b71'):
            code = int.from_bytes(data[4:], 'big')
            return f"Panic code {code}"
        return f"Unknown revert data: {data.hex()[:64]}"
    except Exception as e:
        return f"Could not decode revert: {str(e)}"

DAILY_TASK_CONTRACT_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "recipient", "type": "address"},
            {"internalType": "string", "name": "taskId", "type": "string"},
            {"internalType": "string", "name": "platform", "type": "string"}
        ],
        "name": "disburseReward",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "getContractBalance",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "rewardAmount",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]

class TwitterTaskBlockchain:
    """Twitter Task Disbursement via DailyTaskRewards Contract"""

    def __init__(self):
        self.celo_rpc_url = os.getenv('CELO_RPC_URL', 'https://forno.celo.org')
        self.chain_id = int(os.getenv('CHAIN_ID', 42220))
        self.daily_task_contract_address = _CONFIG_DAILY_TASK_ADDRESS

        self.task_key = os.getenv('TASK_KEY')

        self.w3 = Web3(Web3.HTTPProvider(self.celo_rpc_url))

        if self.w3.is_connected():
            logger.info("✅ Connected to Celo network for Twitter Task")
        else:
            logger.error("❌ Failed to connect to Celo network")

        if self.daily_task_contract_address:
            logger.info(f"📋 DailyTaskRewards contract: {self.daily_task_contract_address}")
        else:
            logger.error("❌ DAILY_TASK_CONTRACT_ADDRESS not set")

        logger.info("🐦 Twitter Task Blockchain Service initialized (contract mode)")

    def mask_wallet_address(self, wallet_address: str) -> str:
        """Mask wallet address for logging"""
        if not wallet_address or len(wallet_address) < 10:
            return wallet_address
        return wallet_address[:6] + "..." + wallet_address[-4:]

    async def disburse_twitter_reward(self, wallet_address: str, amount: float, task_id: str = None) -> dict:
        """
        Disburse Twitter Task reward via DailyTaskRewards contract.
        TASK_KEY signs the disburseReward() call on the contract.

        Args:
            wallet_address: Recipient wallet address
            amount: Amount in G$ (informational — actual amount set on contract)
            task_id: Unique task/submission ID for deduplication

        Returns:
            dict: Result with success status, tx_hash, or error
        """
        try:
            logger.info(f"🐦 Twitter reward disbursement: to {self.mask_wallet_address(wallet_address)} | task_id={task_id}")

            task_key = os.getenv('TASK_KEY') or self.task_key

            if not task_key:
                logger.error("❌ TASK_KEY not configured")
                return {"success": False, "error": "Task key not configured"}

            if not self.daily_task_contract_address:
                logger.error("❌ DAILY_TASK_CONTRACT_ADDRESS not configured")
                return {"success": False, "error": "Daily task contract address not configured"}

            if not task_id:
                logger.error("❌ task_id is required for contract disbursement")
                return {"success": False, "error": "task_id is required"}

            try:
                task_account = Account.from_key(task_key)
                logger.info(f"✅ Task account loaded: {self.mask_wallet_address(task_account.address)}")
            except Exception as key_error:
                logger.error(f"❌ Failed to load task account: {key_error}")
                return {"success": False, "error": "Invalid task key"}

            try:
                contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(self.daily_task_contract_address),
                    abi=DAILY_TASK_CONTRACT_ABI
                )
            except Exception as contract_error:
                logger.error(f"❌ Failed to load DailyTaskRewards contract: {contract_error}")
                return {"success": False, "error": "Contract load error"}

            try:
                contract_balance = contract.functions.getContractBalance().call()
                reward_amount = contract.functions.rewardAmount().call()
                logger.info(f"💵 Contract balance: {contract_balance / 10**18} G$ | Reward: {reward_amount / 10**18} G$")

                if contract_balance < reward_amount:
                    logger.error(f"❌ Insufficient contract balance: {contract_balance / 10**18} G$ < {reward_amount / 10**18} G$")
                    return {"success": False, "error": "insufficient_balance", "error_type": "insufficient_balance"}
            except Exception as balance_error:
                logger.error(f"❌ Failed to check contract balance: {balance_error}")
                return {"success": False, "error": "Failed to check contract balance"}

            # ----------------------------------------------------------
            # Gas + balance preflight.
            #
            # The previous version hardcoded `gas: 600000`, so the L2
            # sequencer reserved gas_limit × gas_price upfront from the
            # task wallet even though disburseReward() really only burns
            # ~120k. With sequencer spikes of ~200 gwei that meant
            # ~0.15 CELO had to be sitting in the wallet before *any*
            # tx could go out, producing the misleading
            # "error_forwarding_sequencer: insufficient funds" error.
            #
            # Now: estimate real gas via eth_estimateGas, add a 20%
            # safety buffer (capped at 500k as a sanity ceiling), cap
            # gas price at 200 gwei, and verify the wallet can actually
            # cover gas_limit × gas_price before broadcasting — surfacing
            # a clear top-up message if not.
            # ----------------------------------------------------------
            try:
                nonce = self.w3.eth.get_transaction_count(task_account.address)

                raw_gas_price = self.w3.eth.gas_price
                gas_price = int(raw_gas_price * 1.2)
                # Safety cap: 200 gwei. Celo L2 should never legitimately
                # need more than this; if the sequencer reports higher we
                # fail clearly instead of draining the task wallet.
                MAX_GAS_PRICE_WEI = 200 * 10**9
                if gas_price > MAX_GAS_PRICE_WEI:
                    logger.warning(
                        f"⚠️ Sequencer gas price {gas_price/10**9:.1f} gwei exceeds "
                        f"safety cap {MAX_GAS_PRICE_WEI/10**9:.0f} gwei — clamping."
                    )
                    gas_price = MAX_GAS_PRICE_WEI

                # Estimate the real gas this call needs.
                try:
                    estimated_gas = contract.functions.disburseReward(
                        Web3.to_checksum_address(wallet_address),
                        str(task_id),
                        "twitter"
                    ).estimate_gas({'from': task_account.address})
                    gas_limit = min(int(estimated_gas * 1.2), 500_000)
                    logger.info(
                        f"⛽ Estimated gas: {estimated_gas} | limit (×1.2): {gas_limit} | "
                        f"price: {gas_price/10**9:.2f} gwei"
                    )
                except Exception as est_err:
                    # If estimate_gas reverts, the underlying call would also
                    # revert on-chain — surface the reason instead of paying
                    # to find out.
                    err_str = str(est_err)
                    revert_reason = err_str
                    if hasattr(est_err, 'data') and est_err.data:
                        raw = est_err.data
                        if isinstance(raw, str):
                            try:
                                raw = bytes.fromhex(raw.replace('0x', ''))
                                revert_reason = _decode_revert_reason(raw)
                            except Exception:
                                pass
                    reason_lower = revert_reason.lower()
                    if any(k in reason_lower for k in ['already', 'duplicate', 'rewarded', 'claimed']):
                        error_type = "already_rewarded"
                    elif any(k in reason_lower for k in ['balance', 'insufficient', 'funds']):
                        error_type = "insufficient_balance"
                    elif any(k in reason_lower for k in ['access', 'owner', 'authorized', 'permission']):
                        error_type = "access_denied"
                    else:
                        error_type = "contract_revert"
                    logger.error(f"❌ estimate_gas reverted [{error_type}]: {revert_reason}")
                    return {
                        "success": False,
                        "error": f"Pre-flight check failed: {revert_reason}",
                        "error_type": error_type,
                        "revert_reason": revert_reason,
                    }

                # Wallet balance preflight — fail clearly with topup amount
                # before broadcasting.
                wallet_balance = self.w3.eth.get_balance(task_account.address)
                tx_cost = gas_limit * gas_price
                if wallet_balance < tx_cost:
                    needed_eth = (tx_cost - wallet_balance) / 10**18
                    have_eth = wallet_balance / 10**18
                    cost_eth = tx_cost / 10**18
                    logger.error(
                        f"❌ Task wallet underfunded: have {have_eth:.6f} CELO, "
                        f"need {cost_eth:.6f} CELO (top up ~{needed_eth:.6f} CELO)"
                    )
                    return {
                        "success": False,
                        "error": (
                            f"Task wallet has {have_eth:.6f} CELO but this disbursement "
                            f"needs {cost_eth:.6f} CELO for gas. Top up ~{needed_eth:.6f} "
                            f"CELO to {task_account.address} and retry."
                        ),
                        "error_type": "task_wallet_underfunded",
                        "task_wallet": task_account.address,
                        "balance_celo": have_eth,
                        "required_celo": cost_eth,
                        "topup_celo": needed_eth,
                    }
            except Exception as network_error:
                logger.error(f"❌ Failed to get network info: {network_error}")
                return {"success": False, "error": "Network error"}

            try:
                txn = contract.functions.disburseReward(
                    Web3.to_checksum_address(wallet_address),
                    str(task_id),
                    "twitter"
                ).build_transaction({
                    'chainId': self.chain_id,
                    'gas': gas_limit,
                    'gasPrice': gas_price,
                    'nonce': nonce,
                    'from': task_account.address
                })
            except Exception as build_error:
                logger.error(f"❌ Failed to build transaction: {build_error}")
                return {"success": False, "error": "Failed to build transaction"}

            try:
                signed_txn = self.w3.eth.account.sign_transaction(txn, task_key)
                logger.info("✅ Transaction signed successfully")
            except Exception as sign_error:
                logger.error(f"❌ Failed to sign transaction: {sign_error}")
                return {"success": False, "error": "Failed to sign transaction"}

            try:
                tx_hash = self.w3.eth.send_raw_transaction(signed_txn.raw_transaction)
                tx_hash_hex = tx_hash.hex()
                if not tx_hash_hex.startswith('0x'):
                    tx_hash_hex = '0x' + tx_hash_hex
                logger.info(f"📤 Transaction sent: {tx_hash_hex}")
            except Exception as send_error:
                logger.error(f"❌ Failed to send transaction: {send_error}")
                return {"success": False, "error": f"Failed to send transaction: {str(send_error)}"}

            try:
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

                if receipt.status == 1:
                    logger.info(f"✅ Twitter reward disbursed via contract: {tx_hash_hex}")
                    return {
                        "success": True,
                        "tx_hash": tx_hash_hex,
                        "amount": reward_amount / 10**18,
                        "recipient": wallet_address,
                        "contract": self.daily_task_contract_address
                    }
                else:
                    # Try to decode the exact revert reason via eth_call simulation
                    revert_reason = "Unknown"
                    try:
                        call_data = contract.functions.disburseReward(
                            Web3.to_checksum_address(wallet_address),
                            str(task_id),
                            "twitter"
                        ).build_transaction({
                            'chainId': self.chain_id,
                            'gas': gas_limit,
                            'gasPrice': gas_price,
                            'nonce': nonce,
                            'from': task_account.address
                        })
                        self.w3.eth.call(call_data, receipt.blockNumber)
                    except Exception as call_err:
                        err_str = str(call_err)
                        if hasattr(call_err, 'data') and call_err.data:
                            raw = call_err.data
                            if isinstance(raw, str):
                                raw = bytes.fromhex(raw.replace('0x', ''))
                            revert_reason = _decode_revert_reason(raw)
                        else:
                            revert_reason = err_str

                    # Classify the reason
                    reason_lower = revert_reason.lower()
                    if any(k in reason_lower for k in ['already', 'duplicate', 'rewarded', 'claimed']):
                        error_type = "already_rewarded"
                        friendly = f"Already rewarded: {revert_reason}"
                    elif any(k in reason_lower for k in ['balance', 'insufficient', 'funds']):
                        error_type = "insufficient_balance"
                        friendly = f"Insufficient contract balance: {revert_reason}"
                    elif any(k in reason_lower for k in ['access', 'owner', 'authorized', 'permission']):
                        error_type = "access_denied"
                        friendly = f"Access denied: {revert_reason}"
                    else:
                        error_type = "contract_revert"
                        friendly = f"Contract reverted: {revert_reason}"

                    logger.error(f"❌ Twitter transaction failed on-chain [{error_type}]: {revert_reason} | TX: {tx_hash_hex}")
                    return {
                        "success": False,
                        "error": friendly,
                        "error_type": error_type,
                        "revert_reason": revert_reason,
                        "tx_hash": tx_hash_hex,
                        "explorer_url": f"https://celoscan.io/tx/{tx_hash_hex}"
                    }

            except Exception as receipt_error:
                logger.error(f"❌ Failed to get receipt: {receipt_error}")
                return {"success": False, "error": "Transaction timeout", "tx_hash": tx_hash_hex}

        except Exception as e:
            logger.error(f"❌ Twitter reward disbursement error: {e}")
            import traceback
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")
            return {"success": False, "error": str(e)}

    def disburse_twitter_reward_sync(self, wallet_address: str, amount: float, task_id: str = None) -> dict:
        """Synchronous wrapper for async disbursement"""
        import asyncio
        import concurrent.futures

        try:
            loop = asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(self._run_in_new_loop, wallet_address, amount, task_id)
                return future.result()
        except RuntimeError:
            return asyncio.run(self.disburse_twitter_reward(wallet_address, amount, task_id))
        except Exception as e:
            logger.error(f"❌ Sync disbursement wrapper error: {e}")
            return {"success": False, "error": str(e)}

    def _run_in_new_loop(self, wallet_address: str, amount: float, task_id: str = None) -> dict:
        """Helper to run async function in a new loop in a separate thread"""
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.disburse_twitter_reward(wallet_address, amount, task_id))
        finally:
            loop.close()

# Global instance
twitter_blockchain_service = TwitterTaskBlockchain()
