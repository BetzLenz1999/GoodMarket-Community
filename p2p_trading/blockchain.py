
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from web3 import Web3
import asyncio
import requests

logger = logging.getLogger(__name__)

class P2PBlockchainService:
    """
    P2P Trading Blockchain Service

    Uses the same proven approach as Reloadly blockchain monitoring
    """

    def __init__(self):
        self.celo_rpc_url = os.getenv('CELO_RPC_URL', 'https://forno.celo.org')
        self.gooddollar_contract = os.getenv('GOODDOLLAR_CONTRACT', '0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A')
        self.merchant_private_key = os.getenv('MERCHANT_KEY')
        self.chain_id = int(os.getenv('CHAIN_ID', 42220))

        # Get merchant address from private key
        if self.merchant_private_key:
            self.w3 = Web3(Web3.HTTPProvider(self.celo_rpc_url))
            account = self.w3.eth.account.from_key(self.merchant_private_key)
            self.merchant_address = account.address
            logger.info(f"✅ P2P merchant account loaded: {self.merchant_address[:10]}...")
        else:
            logger.error("❌ MERCHANT_KEY not configured - P2P trading will fail")
            self.merchant_address = None
            self.w3 = Web3(Web3.HTTPProvider(self.celo_rpc_url))

        if self.w3.is_connected():
            logger.info("✅ Connected to Celo network for P2P Trading")
        else:
            logger.error("❌ Failed to connect to Celo network")

        # ERC20 ABI for GoodDollar
        self.erc20_abi = [
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
            },
            {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "type": "function"
            },
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "from", "type": "address"},
                    {"indexed": True, "name": "to", "type": "address"},
                    {"indexed": False, "name": "value", "type": "uint256"}
                ],
                "name": "Transfer",
                "type": "event"
            }
        ]

        # Create contract instance
        if self.gooddollar_contract:
            self.contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(self.gooddollar_contract),
                abi=self.erc20_abi
            )
            logger.info(f"✅ P2P GoodDollar contract loaded: {self.gooddollar_contract[:10]}...")

    async def check_g_balance(self, wallet_address: str) -> Dict[str, Any]:
        """Check G$ balance for a wallet"""
        try:
            if not self.contract:
                return {"success": False, "error": "Contract not initialized", "balance": 0}

            checksum_address = Web3.to_checksum_address(wallet_address)
            balance_wei = self.contract.functions.balanceOf(checksum_address).call()
            balance_g = balance_wei / (10 ** 18)

            logger.info(f"💰 Balance check: {wallet_address[:8]}... has {balance_g:.6f} G$")

            return {
                "success": True,
                "balance": float(balance_g),
                "balance_formatted": f"{balance_g:.6f} G$",
                "wallet": wallet_address
            }

        except Exception as e:
            logger.error(f"❌ Balance check error: {e}")
            return {"success": False, "error": str(e), "balance": 0}

    async def _get_recent_g_dollar_transfers(self, to_address: str, from_address: str = None, hours_back: int = 2) -> List[Dict]:
        """Get recent G$ transfers using the same proven method as Reloadly"""
        try:
            # Calculate block range
            current_block = self.w3.eth.get_block('latest')
            blocks_per_hour = 720  # Celo ~5 second blocks
            from_block = current_block['number'] - (hours_back * blocks_per_hour)

            # G$ Transfer event signature
            transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

            # Pad addresses to 32 bytes for topic filtering
            padded_to_address = "0x" + "0" * 24 + to_address.lower().replace("0x", "")

            # Build filter params
            topics = [transfer_topic]  # Transfer event signature
            if from_address:
                padded_from_address = "0x" + "0" * 24 + from_address.lower().replace("0x", "")
                topics.append(padded_from_address)  # From specific address
                topics.append(padded_to_address)    # To merchant address
            else:
                topics.append(None)                 # Any from address
                topics.append(padded_to_address)    # To merchant address

            # Get transfer events
            filter_params = {
                "fromBlock": hex(from_block),
                "toBlock": "latest",
                "address": self.gooddollar_contract,
                "topics": topics
            }

            logs = self.w3.eth.get_logs(filter_params)

            transfers = []
            for log in logs:
                try:
                    # Enhanced decoding with better error handling (same as Reloadly)
                    amount_hex = log['data']

                    # Validate hex data format
                    if isinstance(amount_hex, bytes):
                        amount_hex_str = "0x" + amount_hex.hex()
                    elif isinstance(amount_hex, str):
                        amount_hex_str = amount_hex
                    else:
                        logger.error(f"❌ Invalid amount data type: {type(amount_hex)}")
                        continue

                    # Clean and validate hex string
                    if not amount_hex_str.startswith('0x'):
                        amount_hex_str = '0x' + amount_hex_str

                    # Remove '0x' prefix and validate
                    hex_data = amount_hex_str[2:]
                    if not hex_data or not all(c in '0123456789abcdefABCDEF' for c in hex_data):
                        logger.error(f"❌ Invalid hex data: {amount_hex_str}")
                        continue

                    # Convert to wei with error handling
                    try:
                        amount_wei = int(hex_data, 16)
                        amount_g = amount_wei / (10 ** 18)  # Convert from wei to G$
                    except ValueError as hex_error:
                        logger.error(f"❌ Failed to convert hex to int: {hex_data} - {hex_error}")
                        continue

                    # Get from address with validation
                    try:
                        if len(log['topics']) > 1:
                            from_topic = log['topics'][1]
                            if isinstance(from_topic, bytes):
                                from_addr = "0x" + from_topic.hex()[-40:]
                            else:
                                from_addr = "0x" + from_topic.hex()[-40:]
                        else:
                            logger.error(f"❌ Insufficient topics in log")
                            continue
                    except Exception as addr_error:
                        logger.error(f"❌ Error extracting from address: {addr_error}")
                        continue

                    # Get transaction details with validation
                    try:
                        tx_hash_raw = log['transactionHash']
                        if isinstance(tx_hash_raw, bytes):
                            tx_hash = tx_hash_raw.hex()
                        else:
                            tx_hash = tx_hash_raw.hex()

                        if not tx_hash.startswith('0x'):
                            tx_hash = '0x' + tx_hash

                        block_number = log['blockNumber']
                    except Exception as tx_error:
                        logger.error(f"❌ Error extracting transaction details: {tx_error}")
                        continue

                    # Only add valid transfers
                    if amount_g > 0 and from_addr and tx_hash:
                        transfers.append({
                            "tx_hash": tx_hash,
                            "from_address": from_addr,
                            "to_address": to_address,
                            "amount": amount_g,
                            "block_number": block_number,
                            "timestamp": datetime.now().isoformat()
                        })
                        logger.debug(f"✅ Decoded transfer: {amount_g} G$ from {from_addr[:10]}...")
                    else:
                        logger.warning(f"⚠️ Skipping invalid transfer: amount={amount_g}, from={from_addr[:10] if from_addr else 'None'}...")

                except Exception as decode_error:
                    logger.error(f"❌ Error decoding transfer: {decode_error}")
                    logger.debug(f"❌ Problematic log data: {log}")
                    continue

            logger.info(f"📦 Found {len(transfers)} recent G$ transfers to {to_address[:10]}...")
            return transfers

        except Exception as e:
            logger.error(f"❌ Error getting recent transfers: {e}")
            return []

    def _is_payment_for_order(self, transfer: Dict, trade_id: str, expected_amount: float, expected_from_wallet: str) -> bool:
        """Check if a transfer matches our trade requirements (same logic as Reloadly)"""
        try:
            # Check sender wallet address (MOST CRITICAL CHECK)
            from_address_matches = transfer["from_address"].lower() == expected_from_wallet.lower()

            # Check amount with tolerance (0.1% or minimum 0.01 G$)
            amount_tolerance = max(expected_amount * 0.001, 0.01)
            amount_diff = abs(transfer["amount"] - expected_amount)
            amount_matches = amount_diff <= amount_tolerance

            # Check timing - payment should be recent (within 30 minutes)
            transfer_time = datetime.fromisoformat(transfer["timestamp"].replace('Z', '+00:00'))
            current_time = datetime.now(transfer_time.tzinfo)
            time_diff = current_time - transfer_time
            is_recent = time_diff <= timedelta(minutes=30)

            # Enhanced verification logging
            logger.info(f"🔍 Payment verification for {transfer['tx_hash'][:16]}...")
            logger.info(f"   🎯 From wallet: {transfer['from_address'][:10]}... (expected: {expected_from_wallet[:10]}...) - {'✅' if from_address_matches else '❌'}")
            logger.info(f"   💰 Amount: {transfer['amount']} G$ (expected: {expected_amount} G$, tolerance: ±{amount_tolerance}) - {'✅' if amount_matches else '❌'}")
            logger.info(f"   ⏰ Timing: {time_diff.total_seconds():.0f}s ago (must be <30min) - {'✅' if is_recent else '❌'}")

            matches = from_address_matches and amount_matches and is_recent

            if matches:
                logger.info(f"✅ Payment VERIFIED for trade {trade_id} from wallet {expected_from_wallet[:10]}...")
            else:
                failed_checks = []
                if not from_address_matches:
                    failed_checks.append("WRONG_SENDER")
                if not amount_matches:
                    failed_checks.append("WRONG_AMOUNT")
                if not is_recent:
                    failed_checks.append("TOO_OLD")
                logger.warning(f"❌ Payment verification FAILED for trade {trade_id}: {', '.join(failed_checks)}")

            return matches

        except Exception as e:
            logger.error(f"❌ Error verifying payment: {e}")
            return False

    async def verify_seller_deposit(self, seller_wallet: str, expected_amount: float, trade_id: str) -> Dict[str, Any]:
        """Verify seller has deposited G$ to platform escrow"""
        try:
            logger.info(f"🔍 Verifying deposit: {expected_amount} G$ from {seller_wallet[:8]}... for trade {trade_id}")

            if not self.merchant_address:
                logger.error("❌ Merchant address not configured")
                return {"success": False, "error": "Merchant address not configured"}

            if not self.w3.is_connected():
                logger.error("❌ Blockchain not connected")
                return {"success": False, "error": "Blockchain connection failed"}

            # Get recent transfers to merchant address with extended lookback
            recent_transfers = await self.get_recent_g_dollar_transfers(
                self.merchant_address, 
                from_address=seller_wallet,  # Filter by specific sender
                hours_back=2  # Look back 2 hours for better detection
            )

            logger.info(f"📊 Found {len(recent_transfers)} recent transfers from {seller_wallet[:8]}... to merchant")

            # Log all transfers for debugging
            for i, transfer in enumerate(recent_transfers):
                logger.info(f"   Transfer {i+1}: {transfer['amount']} G$ from {transfer['from_address'][:8]}... TX: {transfer['tx_hash'][:16]}...")

            # Look for matching deposit with improved tolerance
            tolerance = max(expected_amount * 0.002, 0.02)  # 0.2% or minimum 0.02 G$ for better matching

            for transfer in recent_transfers:
                amount_diff = abs(float(transfer["amount"]) - expected_amount)
                from_match = transfer["from_address"].lower() == seller_wallet.lower()
                to_match = transfer["to_address"].lower() == self.merchant_address.lower()

                # Check timing - within last 2 hours
                try:
                    transfer_time = datetime.fromisoformat(transfer["timestamp"].replace('Z', '+00:00'))
                    current_time = datetime.now(transfer_time.tzinfo)
                    time_diff = current_time - transfer_time
                    is_recent = time_diff.total_seconds() < 7200  # 2 hours
                except:
                    is_recent = True  # Assume recent if can't parse time

                logger.info(f"🔍 Checking transfer {transfer['tx_hash'][:16]}...")
                logger.info(f"   Amount diff: {amount_diff} (tolerance: {tolerance})")
                logger.info(f"   From match: {from_match} ({transfer['from_address'][:10]}... == {seller_wallet[:10]}...)")
                logger.info(f"   To match: {to_match} ({transfer['to_address'][:10]}... == {self.merchant_address[:10]}...)")
                logger.info(f"   Recent: {is_recent} ({time_diff.total_seconds():.0f}s ago)")

                # Check if this transfer matches our requirements
                if from_match and to_match and amount_diff <= tolerance and is_recent:

                    logger.info(f"✅ VERIFIED DEPOSIT for trade {trade_id}!")
                    logger.info(f"   TX Hash: {transfer['tx_hash']}")
                    logger.info(f"   Amount: {transfer['amount']} G$ (expected: {expected_amount})")
                    logger.info(f"   From: {transfer['from_address']}")
                    logger.info(f"   Block: {transfer['block_number']}")

                    return {
                        "success": True,
                        "verified": True,
                        "tx_hash": transfer["tx_hash"],
                        "amount": transfer["amount"],
                        "block_number": transfer["block_number"],
                        "timestamp": transfer["timestamp"],
                        "from_address": transfer["from_address"]
                    }

            logger.warning(f"❌ No matching deposit found for trade {trade_id}")
            logger.warning(f"   Expected: {expected_amount} G$ from {seller_wallet}")
            logger.warning(f"   Merchant: {self.merchant_address}")
            logger.warning(f"   Tolerance: ±{tolerance} G$")

            return {
                "success": False, 
                "verified": False,
                "error": "No matching deposit found",
                "expected_amount": expected_amount,
                "expected_from": seller_wallet,
                "merchant_address": self.merchant_address,
                "transfers_checked": len(recent_transfers)
            }

        except Exception as e:
            logger.error(f"❌ Error verifying deposit for {trade_id}: {e}")
            return {
                "success": False, 
                "verified": False,
                "error": f"Verification error: {str(e)}"
            }

    async def release_escrowed_g(self, buyer_wallet: str, amount: float, 
                               trade_id: str) -> Dict[str, Any]:
        """Release G$ from escrow to buyer"""
        try:
            logger.info(f"🎯 Releasing {amount} G$ to buyer: {buyer_wallet[:8]}...")

            if not self.merchant_private_key or not self.merchant_address:
                return {"success": False, "error": "Merchant credentials not configured"}

            # Prepare transaction
            buyer_checksum = Web3.to_checksum_address(buyer_wallet)
            amount_wei = int(amount * (10 ** 18))

            # Get nonce
            nonce = self.w3.eth.get_transaction_count(self.merchant_address)

            # Build transaction with fixed 250,000 gas and optimized gas price
            current_gas_price = self.w3.eth.gas_price
            min_gas_price = self.w3.to_wei('60', 'gwei')  # Increased minimum for better success rate
            # Add 20% buffer to current gas price for priority
            buffered_gas_price = int(current_gas_price * 1.2)
            gas_price = max(buffered_gas_price, min_gas_price)

            logger.info(f"💰 Gas configuration: limit={250000}, price={self.w3.from_wei(gas_price, 'gwei')} gwei")

            transaction = self.contract.functions.transfer(
                buyer_checksum,
                amount_wei
            ).build_transaction({
                'chainId': self.chain_id,
                'gas': 250000,  # Increased gas limit to 250,000 for better reliability
                'gasPrice': gas_price,
                'nonce': nonce,
            })

            # Sign transaction
            signed_txn = self.w3.eth.account.sign_transaction(transaction, self.merchant_private_key)

            # Send transaction
            tx_hash = self.w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            tx_hash_hex = tx_hash.hex()
            
            # Ensure 0x prefix for transaction hash
            if not tx_hash_hex.startswith('0x'):
                tx_hash_hex = '0x' + tx_hash_hex

            logger.info(f"🎉 G$ released successfully: {tx_hash_hex}")

            # Wait for confirmation with better error handling
            try:
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                if receipt.status == 1:
                    logger.info(f"✅ Transaction confirmed: {tx_hash_hex}")
                    logger.info(f"   Gas used: {receipt.gasUsed}/{receipt.gasLimit if hasattr(receipt, 'gasLimit') else 'unknown'}")
                    return {
                        "success": True,
                        "tx_hash": tx_hash_hex,
                        "amount": amount,
                        "recipient": buyer_wallet,
                        "trade_id": trade_id,
                        "confirmed": True,
                        "gas_used": receipt.gasUsed
                    }
                else:
                    logger.error(f"❌ Transaction failed on blockchain: {tx_hash_hex}")
                    logger.error(f"   Gas used: {receipt.gasUsed}")

                    # Try to get revert reason
                    try:
                        tx_details = self.w3.eth.get_transaction(tx_hash)
                        self.w3.eth.call(tx_details, receipt.blockNumber - 1)
                    except Exception as call_error:
                        logger.error(f"   Revert reason: {call_error}")

                    return {
                        "success": False,
                        "error": "Transaction failed on blockchain",
                        "tx_hash": tx_hash_hex,
                        "gas_used": receipt.gasUsed,
                        "confirmed": True
                    }

            except Exception as wait_error:
                logger.warning(f"⚠️ Transaction sent but confirmation timeout: {wait_error}")
                logger.warning(f"   TX Hash: {tx_hash_hex} - Check manually on Celo explorer")

                # Return success but mark as unconfirmed for manual checking
                return {
                    "success": True,  # Transaction was sent
                    "tx_hash": tx_hash_hex,
                    "amount": amount,
                    "recipient": buyer_wallet,
                    "trade_id": trade_id,
                    "confirmed": False,
                    "warning": "Transaction sent but confirmation timeout"
                }

        except Exception as e:
            logger.error(f"❌ Error releasing G$: {e}")
            return {"success": False, "error": str(e)}

    async def refund_escrowed_g(self, seller_wallet: str, amount: float, 
                              trade_id: str) -> Dict[str, Any]:
        """Refund G$ from escrow back to seller"""
        try:
            logger.info(f"↩️ Refunding {amount} G$ to seller: {seller_wallet[:8]}...")

            # Use the same release mechanism but to seller instead of buyer
            result = await self.release_escrowed_g(seller_wallet, amount, f"refund-{trade_id}")

            if result["success"]:
                logger.info(f"💰 Refund completed: {result['tx_hash']}")
                result["refund"] = True

            return result

        except Exception as e:
            logger.error(f"❌ Error refunding G$: {e}")
            return {"success": False, "error": str(e)}

    async def get_recent_g_dollar_transfers(self, to_address: str, from_address: str = None, hours_back: int = 2) -> List[Dict]:
        """Public wrapper for _get_recent_g_dollar_transfers"""
        return await self._get_recent_g_dollar_transfers(to_address, from_address, hours_back)

    async def get_merchant_balance(self) -> Dict[str, Any]:
        """Get merchant escrow balance"""
        try:
            if not self.merchant_address:
                return {"success": False, "error": "Merchant address not configured"}

            result = await self.check_g_balance(self.merchant_address)
            return result

        except Exception as e:
            logger.error(f"❌ Error getting merchant balance: {e}")
            return {"success": False, "error": str(e)}

# Global service instance
p2p_blockchain_service = P2PBlockchainService()
