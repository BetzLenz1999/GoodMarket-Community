
import os
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from supabase_client import get_supabase_client
from .blockchain import p2p_blockchain_service
import uuid
import random

logger = logging.getLogger(__name__)

class P2PTradingService:
    """
    P2P Trading Service - Database-driven Escrow System

    This service handles G$ to fiat trading using platform escrow instead of smart contracts.
    Compatible with current wallet-address-only login system.
    """

    def __init__(self):
        self.supabase = get_supabase_client()
        self.blockchain_service = p2p_blockchain_service
        self.escrow_timeout_hours = 24  # Auto-cancel after 24 hours

        # Supported payment methods
        self.payment_methods = [
            # Traditional Payment Methods
            "PayPal", "GCash", "PayMaya", "BPI", "BDO", 
            "UnionBank", "Metrobank", "Wise", "Remitly", "Western Union",
            
            # Cryptocurrency Payment Methods
            "Bitcoin (BTC)", "Ethereum (ETH)", "USDC", "USDT", 
            "Binance Pay", "Crypto.com Pay", "Coins.ph", "PDAX",
            
            # Custom/Other
            "Custom Crypto Wallet", "Other Payment Method"
        ]

        # Supported fiat currencies
        self.fiat_currencies = [
            "USD", "PHP", "EUR", "GBP", "CAD", "AUD", "SGD"
        ]

        logger.info("🔄 P2P Trading Service initialized")
        logger.info(f"💰 Supported payment methods: {len(self.payment_methods)}")
        logger.info(f"💵 Supported currencies: {len(self.fiat_currencies)}")

    async def create_sell_order(self, seller_wallet: str, g_dollar_amount: float, 
                              g_dollar_price_usd: float, fiat_amount: float, fiat_currency: str, 
                              payment_method: str, description: str = "",
                              payment_details: str = "") -> Dict[str, Any]:
        """Create a new sell order"""
        try:
            logger.info(f"🛒 Creating sell order: {seller_wallet[:8]}... selling {g_dollar_amount} G$")

            # Validate inputs
            if g_dollar_amount <= 0 or fiat_amount <= 0:
                return {"success": False, "error": "Invalid amounts"}

            if fiat_currency not in self.fiat_currencies:
                return {"success": False, "error": f"Currency {fiat_currency} not supported"}

            if payment_method not in self.payment_methods:
                return {"success": False, "error": f"Payment method {payment_method} not supported"}

            # Check seller's G$ balance
            balance_check = await self.blockchain_service.check_g_balance(seller_wallet)
            if not balance_check["success"] or balance_check["balance"] < g_dollar_amount:
                return {"success": False, "error": "Insufficient G$ balance"}

            # Store G$ price per USD and calculate rate
            usd_rate = fiat_amount / g_dollar_amount  # Rate in selected currency
            
            # Create order in database
            order_data = {
                "order_id": f"P2P-{uuid.uuid4().hex[:8].upper()}",
                "seller_wallet": seller_wallet,
                "g_dollar_amount": g_dollar_amount,
                "g_dollar_price_usd": g_dollar_price_usd,
                "fiat_amount": fiat_amount,
                "fiat_currency": fiat_currency,
                "payment_method": payment_method,
                "payment_details": payment_details,
                "rate": usd_rate,  # Rate in the selected fiat currency
                "description": description,
                "status": "active",
                "created_at": datetime.now().isoformat()
            }

            if self.supabase:
                result = self.supabase.table("p2p_orders").insert(order_data).execute()
                if result.data:
                    logger.info(f"✅ Sell order created: {order_data['order_id']}")
                    return {
                        "success": True,
                        "order": result.data[0],
                        "message": "Sell order created successfully"
                    }

            return {"success": False, "error": "Database not available"}

        except Exception as e:
            logger.error(f"❌ Error creating sell order: {e}")
            return {"success": False, "error": str(e)}

    async def get_available_orders(self, buyer_wallet: str = None, 
                                 fiat_currency: str = None, 
                                 payment_method: str = None,
                                 limit: int = 20) -> List[Dict]:
        """Get available sell orders"""
        try:
            logger.info(f"📋 Fetching available orders (limit: {limit})")

            if not self.supabase:
                return []

            # Build query
            query = self.supabase.table("p2p_orders").select("*").eq("status", "active")

            # Add filters
            if fiat_currency:
                query = query.eq("fiat_currency", fiat_currency)
            if payment_method:
                query = query.eq("payment_method", payment_method)

            # Exclude buyer's own orders
            if buyer_wallet:
                query = query.neq("seller_wallet", buyer_wallet)

            result = query.order("created_at", desc=True).limit(limit).execute()

            orders = result.data if result.data else []

            # Debug logging
            logger.info(f"🔍 Query filters: currency={fiat_currency}, payment={payment_method}, buyer={buyer_wallet}")
            logger.info(f"📊 Raw query result: {len(orders)} orders found")

            # Also check total orders in database for debugging
            total_orders = self.supabase.table("p2p_orders").select("*").execute()
            logger.info(f"📈 Total orders in database: {len(total_orders.data) if total_orders.data else 0}")

            active_orders = self.supabase.table("p2p_orders").select("*").eq("status", "active").execute()
            logger.info(f"🟢 Active orders in database: {len(active_orders.data) if active_orders.data else 0}")

            if active_orders.data:
                for order in active_orders.data:
                    logger.info(f"   📝 Order {order['order_id']}: {order['g_dollar_amount']} G$ for {order['fiat_amount']} {order['fiat_currency']} via {order['payment_method']}")
                    logger.info(f"      👤 Seller: {order['seller_wallet'][:8]}... | Status: {order['status']}")

            # Add seller ratings
            for order in orders:
                seller_rating = await self.get_user_rating(order["seller_wallet"])
                order["seller_rating"] = seller_rating
                order["seller_display"] = f"{order['seller_wallet'][:6]}...{order['seller_wallet'][-4:]}"

            logger.info(f"✅ Found {len(orders)} available orders")
            return orders

        except Exception as e:
            logger.error(f"❌ Error fetching orders: {e}")
            return []

    async def accept_order(self, buyer_wallet: str, order_id: str) -> Dict[str, Any]:
        """Accept a sell order and start escrow process"""
        try:
            logger.info(f"🤝 Order acceptance: {buyer_wallet[:8]}... accepting {order_id}")

            if not self.supabase:
                return {"success": False, "error": "Database not available"}

            # Get order details
            order_result = self.supabase.table("p2p_orders")\
                .select("*")\
                .eq("order_id", order_id)\
                .eq("status", "active")\
                .execute()

            if not order_result.data:
                return {"success": False, "error": "Order not found or already taken"}

            order = order_result.data[0]

            # Check if buyer is not the seller
            if order["seller_wallet"] == buyer_wallet:
                return {"success": False, "error": "Cannot buy your own order"}

            # Check seller still has balance
            balance_check = await self.blockchain_service.check_g_balance(order["seller_wallet"])
            if not balance_check["success"] or balance_check["balance"] < order["g_dollar_amount"]:
                # Deactivate order
                self.supabase.table("p2p_orders")\
                    .update({"status": "insufficient_funds"})\
                    .eq("id", order["id"])\
                    .execute()
                return {"success": False, "error": "Seller has insufficient funds"}

            # Create active trade (escrow record)
            trade_data = {
                "trade_id": f"TRADE-{uuid.uuid4().hex[:8].upper()}",
                "order_id": order_id,
                "buyer_wallet": buyer_wallet,
                "seller_wallet": order["seller_wallet"],
                "g_dollar_amount": order["g_dollar_amount"],
                "fiat_amount": order["fiat_amount"],
                "fiat_currency": order["fiat_currency"],
                "payment_method": order["payment_method"],
                "rate": order["rate"],
                "status": "waiting_seller_deposit",
                "timeout_at": (datetime.now() + timedelta(hours=self.escrow_timeout_hours)).isoformat(),
                "created_at": datetime.now().isoformat()
            }

            # Insert trade and update order status
            trade_result = self.supabase.table("p2p_trades").insert(trade_data).execute()

            if trade_result.data:
                # Update order status
                self.supabase.table("p2p_orders")\
                    .update({"status": "in_progress"})\
                    .eq("id", order["id"])\
                    .execute()

                logger.info(f"✅ Trade created: {trade_data['trade_id']}")

                return {
                    "success": True,
                    "trade": trade_result.data[0],
                    "message": "Order accepted! Waiting for seller to deposit G$ to escrow.",
                    "next_step": "seller_deposit"
                }

            return {"success": False, "error": "Failed to create trade"}

        except Exception as e:
            logger.error(f"❌ Error accepting order: {e}")
            return {"success": False, "error": str(e)}

    async def confirm_seller_deposit(self, trade_id: str, seller_wallet: str) -> Dict[str, Any]:
        """Confirm seller has deposited G$ to platform escrow"""
        try:
            logger.info(f"💰 Seller deposit confirmation: {trade_id}")

            # Get trade details
            trade = await self.get_trade_by_id(trade_id)
            if not trade or trade["seller_wallet"] != seller_wallet:
                return {"success": False, "error": "Trade not found or unauthorized"}

            if trade["status"] != "waiting_seller_deposit":
                return {"success": False, "error": "Trade not in correct state"}

            # Check if seller has actually sent G$ to platform
            # This would check recent transactions to merchant address
            deposit_verified = await self.blockchain_service.verify_seller_deposit(
                seller_wallet, trade["g_dollar_amount"], trade_id
            )

            if not deposit_verified["success"]:
                return {"success": False, "error": "G$ deposit not verified"}

            # Update trade status
            update_result = self.supabase.table("p2p_trades")\
                .update({
                    "status": "escrow_active",
                    "seller_deposit_tx": deposit_verified.get("tx_hash"),
                    "seller_deposited_at": datetime.now().isoformat()
                })\
                .eq("trade_id", trade_id)\
                .execute()

            if update_result.data:
                logger.info(f"✅ Escrow activated for trade {trade_id}")

                # Log escrow action
                await self.log_escrow_action(trade_id, "deposit_confirmed", 
                                           trade["g_dollar_amount"], 
                                           deposit_verified.get("tx_hash"))

                return {
                    "success": True,
                    "message": "G$ deposited to escrow. Buyer can now send fiat payment.",
                    "next_step": "buyer_payment"
                }

            return {"success": False, "error": "Failed to update trade status"}

        except Exception as e:
            logger.error(f"❌ Error confirming seller deposit: {e}")
            return {"success": False, "error": str(e)}

    async def confirm_buyer_payment(self, trade_id: str, buyer_wallet: str, payment_proof_url: str = None) -> Dict[str, Any]:
        """Confirm buyer has sent fiat payment"""
        try:
            logger.info(f"💸 Buyer payment confirmation: {trade_id}")

            # Get trade details
            trade = await self.get_trade_by_id(trade_id)
            if not trade or trade["buyer_wallet"] != buyer_wallet:
                return {"success": False, "error": "Trade not found or unauthorized"}

            if trade["status"] != "escrow_active":
                return {"success": False, "error": "Escrow not active"}

            # Update trade status
            update_data = {
                "status": "payment_sent",
                "buyer_paid_at": datetime.now().isoformat()
            }

            if payment_proof_url:
                update_data["payment_proof_url"] = payment_proof_url
                update_data["payment_proof_uploaded_at"] = datetime.now().isoformat()

            update_result = self.supabase.table("p2p_trades")\
                .update(update_data)\
                .eq("trade_id", trade_id)\
                .execute()

            if update_result.data:
                logger.info(f"✅ Payment sent confirmed for trade {trade_id}")
                return {
                    "success": True,
                    "message": "Payment confirmation recorded. Waiting for seller to confirm receipt.",
                    "next_step": "seller_confirmation"
                }

            return {"success": False, "error": "Failed to update payment status"}

        except Exception as e:
            logger.error(f"❌ Error confirming buyer payment: {e}")
            return {"success": False, "error": str(e)}

    async def upload_payment_proof(self, trade_id: str, buyer_wallet: str, proof_url: str) -> Dict[str, Any]:
        """Upload payment proof URL for a trade"""
        try:
            logger.info(f"📸 Uploading payment proof for trade: {trade_id}")

            # Get trade details
            trade = await self.get_trade_by_id(trade_id)
            if not trade or trade["buyer_wallet"] != buyer_wallet:
                return {"success": False, "error": "Trade not found or unauthorized"}

            if trade["status"] not in ["escrow_active", "payment_sent"]:
                return {"success": False, "error": "Invalid trade status for proof upload"}

            # Validate ImgBB URL format
            if not proof_url.startswith(("https://i.ibb.co/", "https://ibb.co/")):
                return {"success": False, "error": "Invalid ImgBB URL format"}

            # Update trade with payment proof
            update_result = self.supabase.table("p2p_trades")\
                .update({
                    "payment_proof_url": proof_url,
                    "payment_proof_uploaded_at": datetime.now().isoformat(),
                    "status": "payment_sent" if trade["status"] == "escrow_active" else trade["status"],
                    "buyer_paid_at": datetime.now().isoformat() if trade["status"] == "escrow_active" else trade.get("buyer_paid_at")
                })\
                .eq("trade_id", trade_id)\
                .execute()

            if update_result.data:
                logger.info(f"✅ Payment proof uploaded for trade {trade_id}")
                return {
                    "success": True,
                    "message": "Payment proof uploaded successfully. Seller can now review the proof.",
                    "proof_url": proof_url
                }

            return {"success": False, "error": "Failed to upload payment proof"}

        except Exception as e:
            logger.error(f"❌ Error uploading payment proof: {e}")
            return {"success": False, "error": str(e)}

    async def confirm_seller_received_payment(self, trade_id: str, seller_wallet: str) -> Dict[str, Any]:
        """Confirm seller received fiat payment and release G$ to buyer"""
        try:
            logger.info(f"✅ Seller payment receipt confirmation: {trade_id}")

            # Get trade details
            trade = await self.get_trade_by_id(trade_id)
            if not trade or trade["seller_wallet"] != seller_wallet:
                return {"success": False, "error": "Trade not found or unauthorized"}

            if trade["status"] != "payment_sent":
                return {"success": False, "error": "Payment not marked as sent"}

            # Release G$ to buyer using platform private key
            release_result = await self.blockchain_service.release_escrowed_g(
                trade["buyer_wallet"], 
                trade["g_dollar_amount"], 
                trade_id
            )

            if not release_result["success"]:
                return {"success": False, "error": "Failed to release G$ to buyer"}

            # Update trade as completed
            update_result = self.supabase.table("p2p_trades")\
                .update({
                    "status": "completed",
                    "seller_confirmed_at": datetime.now().isoformat(),
                    "completed_at": datetime.now().isoformat(),
                    "release_tx_hash": release_result.get("tx_hash")
                })\
                .eq("trade_id", trade_id)\
                .execute()

            if update_result.data:
                # Log escrow release
                await self.log_escrow_action(trade_id, "funds_released", 
                                           trade["g_dollar_amount"], 
                                           release_result.get("tx_hash"))

                logger.info(f"🎉 Trade completed successfully: {trade_id}")

                # Update user ratings
                await self.update_user_ratings(trade_id)

                return {
                    "success": True,
                    "message": "Trade completed! G$ released to buyer.",
                    "tx_hash": release_result.get("tx_hash")
                }

            return {"success": False, "error": "Failed to complete trade"}

        except Exception as e:
            logger.error(f"❌ Error confirming payment receipt: {e}")
            return {"success": False, "error": str(e)}

    async def cancel_trade(self, trade_id: str, wallet_address: str, reason: str = "") -> Dict[str, Any]:
        """Cancel trade and refund G$ to seller if escrowed"""
        try:
            logger.info(f"❌ Trade cancellation: {trade_id} by {wallet_address[:8]}...")

            # Get trade details
            trade = await self.get_trade_by_id(trade_id)
            if not trade:
                return {"success": False, "error": "Trade not found"}

            # Check if user is involved in this trade
            if wallet_address not in [trade["buyer_wallet"], trade["seller_wallet"]]:
                return {"success": False, "error": "Unauthorized to cancel this trade"}

            # Check if trade can be cancelled
            if trade["status"] in ["completed", "cancelled", "disputed"]:
                return {"success": False, "error": "Trade cannot be cancelled"}

            refund_tx_hash = None

            # If G$ is in escrow, refund to seller
            if trade["status"] in ["escrow_active", "payment_sent"]:
                refund_result = await self.blockchain_service.refund_escrowed_g(
                    trade["seller_wallet"], 
                    trade["g_dollar_amount"], 
                    trade_id
                )

                if refund_result["success"]:
                    refund_tx_hash = refund_result.get("tx_hash")
                    logger.info(f"💰 Refunded {trade['g_dollar_amount']} G$ to seller")

            # Update trade status
            update_result = self.supabase.table("p2p_trades")\
                .update({
                    "status": "cancelled",
                    "cancelled_at": datetime.now().isoformat(),
                    "cancelled_by": wallet_address,
                    "cancel_reason": reason,
                    "refund_tx_hash": refund_tx_hash
                })\
                .eq("trade_id", trade_id)\
                .execute()

            if update_result.data:
                # Log cancellation
                await self.log_escrow_action(trade_id, "trade_cancelled", 
                                           trade["g_dollar_amount"], 
                                           refund_tx_hash)

                return {
                    "success": True,
                    "message": "Trade cancelled successfully",
                    "refund_tx": refund_tx_hash
                }

            return {"success": False, "error": "Failed to cancel trade"}

        except Exception as e:
            logger.error(f"❌ Error cancelling trade: {e}")
            return {"success": False, "error": str(e)}

    async def get_user_orders(self, wallet_address: str, limit: int = 20) -> List[Dict]:
        """Get user's own sell orders"""
        try:
            if not self.supabase:
                return []

            # Get orders where user is the seller
            orders_result = self.supabase.table("p2p_orders")\
                .select("*")\
                .eq("seller_wallet", wallet_address)\
                .order("created_at", desc=True)\
                .limit(limit)\
                .execute()

            orders = orders_result.data if orders_result.data else []

            logger.info(f"✅ Found {len(orders)} orders for seller {wallet_address[:8]}...")
            return orders

        except Exception as e:
            logger.error(f"❌ Error getting user orders: {e}")
            return []

    async def get_user_orders_with_trades(self, wallet_address: str, limit: int = 20) -> List[Dict]:
        """Get user's own sell orders with active trade information"""
        try:
            if not self.supabase:
                return []

            # Get orders where user is the seller
            orders_result = self.supabase.table("p2p_orders")\
                .select("*")\
                .eq("seller_wallet", wallet_address)\
                .order("created_at", desc=True)\
                .limit(limit)\
                .execute()

            orders = orders_result.data if orders_result.data else []

            # For each order, check trade status and update order status accordingly
            filtered_orders = []
            for order in orders:
                # Get the most recent trade for this order (any status)
                all_trades_result = self.supabase.table("p2p_trades")\
                    .select("*")\
                    .eq("order_id", order["order_id"])\
                    .order("created_at", desc=True)\
                    .limit(1)\
                    .execute()

                # Check if there's a completed trade and update order status
                if all_trades_result.data:
                    latest_trade = all_trades_result.data[0]
                    
                    # If latest trade is completed, update order status and skip showing it
                    if latest_trade["status"] == "completed":
                        # Update order status to completed
                        if order["status"] != "completed":
                            self.supabase.table("p2p_orders")\
                                .update({"status": "completed"})\
                                .eq("id", order["id"])\
                                .execute()
                            logger.info(f"📝 Updated order {order['order_id']} status to completed")
                        
                        logger.info(f"🎯 Hiding completed order {order['order_id']}")
                        continue
                    
                    # If latest trade is cancelled, revert order to active
                    elif latest_trade["status"] == "cancelled":
                        if order["status"] != "active":
                            self.supabase.table("p2p_orders")\
                                .update({"status": "active"})\
                                .eq("id", order["id"])\
                                .execute()
                            logger.info(f"📝 Reverted order {order['order_id']} status to active after cancellation")
                
                # Get active trade for this order
                trades_result = self.supabase.table("p2p_trades")\
                    .select("*")\
                    .eq("order_id", order["order_id"])\
                    .in_("status", ["waiting_seller_deposit", "escrow_active", "payment_sent"])\
                    .order("created_at", desc=True)\
                    .limit(1)\
                    .execute()

                if trades_result.data:
                    trade = trades_result.data[0]
                    order["active_trade"] = {
                        "trade_id": trade["trade_id"],
                        "buyer_wallet": trade["buyer_wallet"],
                        "buyer_display": f"{trade['buyer_wallet'][:6]}...{trade['buyer_wallet'][-4:]}",
                        "status": trade["status"],
                        "created_at": trade["created_at"]
                    }
                    
                    # Update order status to in_progress if there's an active trade
                    if order["status"] == "active":
                        self.supabase.table("p2p_orders")\
                            .update({"status": "in_progress"})\
                            .eq("id", order["id"])\
                            .execute()
                        logger.info(f"📝 Updated order {order['order_id']} status to in_progress")
                else:
                    order["active_trade"] = None
                    
                    # Revert to active if no active trades and not completed
                    if order["status"] == "in_progress":
                        self.supabase.table("p2p_orders")\
                            .update({"status": "active"})\
                            .eq("id", order["id"])\
                            .execute()
                        logger.info(f"📝 Reverted order {order['order_id']} status to active (no active trades)")
                
                # Add to filtered list
                filtered_orders.append(order)
            
            orders = filtered_orders

            logger.info(f"✅ Found {len(orders)} orders with trade info for seller {wallet_address[:8]}...")
            return orders

        except Exception as e:
            logger.error(f"❌ Error getting user orders with trades: {e}")
            return []

    async def get_user_trades(self, wallet_address: str, limit: int = 20) -> List[Dict]:
        """Get user's trade history with enhanced logging"""
        try:
            if not self.supabase:
                logger.error("❌ Supabase client not available for trades")
                return []

            logger.info(f"🔍 Fetching P2P trades for wallet {wallet_address[:8]}... (limit: {limit})")

            # Get trades where user is buyer or seller
            trades_result = self.supabase.table("p2p_trades")\
                .select("*")\
                .or_(f"buyer_wallet.eq.{wallet_address},seller_wallet.eq.{wallet_address}")\
                .order("created_at", desc=True)\
                .limit(limit)\
                .execute()

            trades = trades_result.data if trades_result.data else []
            logger.info(f"📊 Raw query returned {len(trades)} trades")

            # Add role information and validate data
            processed_trades = []
            for i, trade in enumerate(trades):
                try:
                    # Determine user role
                    trade["user_role"] = "seller" if trade["seller_wallet"] == wallet_address else "buyer"
                    trade["counterpart"] = trade["buyer_wallet"] if trade["user_role"] == "seller" else trade["seller_wallet"]
                    trade["counterpart_display"] = f"{trade['counterpart'][:6]}...{trade['counterpart'][-4:]}"
                    
                    # Validate and log trade data
                    trade_id = trade.get("trade_id", f"trade_{i}")
                    status = trade.get("status", "unknown")
                    g_amount = trade.get("g_dollar_amount", 0)
                    fiat_amount = trade.get("fiat_amount", 0)
                    
                    logger.info(f"   Trade {i+1}: {trade_id} | Role: {trade['user_role']} | Status: {status} | {g_amount} G$ = {fiat_amount} {trade.get('fiat_currency', 'USD')}")
                    
                    # Log transaction hashes if available
                    if trade.get("seller_deposit_tx"):
                        logger.info(f"     Deposit TX: {trade['seller_deposit_tx']}")
                    if trade.get("release_tx_hash"):
                        logger.info(f"     Release TX: {trade['release_tx_hash']}")
                    
                    processed_trades.append(trade)
                    
                except Exception as trade_error:
                    logger.error(f"❌ Error processing trade {i}: {trade_error}")
                    continue

            logger.info(f"✅ Successfully processed {len(processed_trades)} trades for {wallet_address[:8]}...")
            return processed_trades

        except Exception as e:
            logger.error(f"❌ Error getting user trades for {wallet_address[:8]}...: {e}")
            return []

    async def get_trade_by_id(self, trade_id: str) -> Optional[Dict]:
        """Get trade details by ID"""
        try:
            if not self.supabase:
                return None

            result = self.supabase.table("p2p_trades")\
                .select("*")\
                .eq("trade_id", trade_id)\
                .execute()

            return result.data[0] if result.data else None

        except Exception as e:
            logger.error(f"❌ Error getting trade: {e}")
            return None

    async def log_escrow_action(self, trade_id: str, action: str, 
                              amount: float, tx_hash: str = None):
        """Log escrow action for transparency"""
        try:
            if not self.supabase:
                return

            log_data = {
                "trade_id": trade_id,
                "action": action,
                "g_dollar_amount": amount,
                "transaction_hash": tx_hash,
                "timestamp": datetime.now().isoformat()
            }

            self.supabase.table("p2p_escrow_logs").insert(log_data).execute()

        except Exception as e:
            logger.error(f"❌ Error logging escrow action: {e}")

    async def get_user_rating(self, wallet_address: str) -> Dict[str, Any]:
        """Get user's trading rating"""
        try:
            if not self.supabase:
                return {"rating": 0, "total_trades": 0}

            # Get completed trades
            trades_result = self.supabase.table("p2p_trades")\
                .select("*")\
                .or_(f"buyer_wallet.eq.{wallet_address},seller_wallet.eq.{wallet_address}")\
                .eq("status", "completed")\
                .execute()

            total_trades = len(trades_result.data) if trades_result.data else 0

            # Get ratings
            ratings_result = self.supabase.table("p2p_ratings")\
                .select("rating")\
                .eq("rated_wallet", wallet_address)\
                .execute()

            if ratings_result.data:
                total_rating = sum(r["rating"] for r in ratings_result.data)
                avg_rating = total_rating / len(ratings_result.data)
            else:
                avg_rating = 0

            return {
                "rating": round(avg_rating, 1),
                "total_trades": total_trades,
                "total_ratings": len(ratings_result.data) if ratings_result.data else 0
            }

        except Exception as e:
            logger.error(f"❌ Error getting user rating: {e}")
            return {"rating": 0, "total_trades": 0}

    async def update_user_ratings(self, trade_id: str):
        """Auto-generate positive ratings for successful trades"""
        try:
            trade = await self.get_trade_by_id(trade_id)
            if not trade:
                return

            # Create ratings for both parties
            ratings = [
                {
                    "trade_id": trade_id,
                    "rater_wallet": trade["buyer_wallet"],
                    "rated_wallet": trade["seller_wallet"],
                    "rating": 5,  # Auto-positive rating for successful trade
                    "comment": "Trade completed successfully",
                    "created_at": datetime.now().isoformat()
                },
                {
                    "trade_id": trade_id,
                    "rater_wallet": trade["seller_wallet"], 
                    "rated_wallet": trade["buyer_wallet"],
                    "rating": 5,  # Auto-positive rating for successful trade
                    "comment": "Trade completed successfully",
                    "created_at": datetime.now().isoformat()
                }
            ]

            if self.supabase:
                self.supabase.table("p2p_ratings").insert(ratings).execute()
                logger.info(f"✅ Auto-ratings created for trade {trade_id}")

        except Exception as e:
            logger.error(f"❌ Error updating ratings: {e}")

    def get_trading_stats(self) -> Dict[str, Any]:
        """Get platform trading statistics"""
        try:
            if not self.supabase:
                return {}

            # Get total orders
            orders_result = self.supabase.table("p2p_orders").select("*").execute()
            total_orders = len(orders_result.data) if orders_result.data else 0

            # Get completed trades
            trades_result = self.supabase.table("p2p_trades").select("*").eq("status", "completed").execute()
            completed_trades = len(trades_result.data) if trades_result.data else 0

            # Calculate total volume
            total_volume = 0
            if trades_result.data:
                total_volume = sum(float(t.get("g_dollar_amount", 0)) for t in trades_result.data)

            # Get active orders
            active_orders = self.supabase.table("p2p_orders").select("*").eq("status", "active").execute()
            active_count = len(active_orders.data) if active_orders.data else 0

            return {
                "total_orders": total_orders,
                "completed_trades": completed_trades,
                "total_volume_g": total_volume,
                "active_orders": active_count,
                "success_rate": f"{(completed_trades / max(total_orders, 1) * 100):.1f}%"
            }

        except Exception as e:
            logger.error(f"❌ Error getting trading stats: {e}")
            return {}

    async def auto_verify_pending_deposits(self) -> Dict[str, Any]:
        """Auto-verify pending deposits by checking blockchain"""
        try:
            logger.info("🔍 AUTO-VERIFICATION: Starting deposit check...")

            if not self.supabase:
                logger.error("❌ Database not available for verification")
                return {"success": False, "error": "Database not available", "deposits_verified": 0}

            # Get all trades waiting for seller deposit
            pending_trades = self.supabase.table('p2p_trades').select('*').eq('status', 'waiting_seller_deposit').execute()

            if not pending_trades.data:
                logger.info("📋 No pending deposits to verify")
                return {
                    "success": True,
                    "deposits_verified": 0,
                    "message": "No pending deposits found"
                }

            logger.info(f"📊 Found {len(pending_trades.data)} pending deposit(s) to verify")

            verified_count = 0
            checked_count = 0
            verification_details = []

            for trade in pending_trades.data:
                trade_id = trade['trade_id']
                seller_wallet = trade['seller_wallet']
                expected_amount = float(trade['g_dollar_amount'])
                buyer_wallet = trade['buyer_wallet']
                checked_count += 1

                logger.info(f"🔍 [{checked_count}] Verifying trade {trade_id}")
                logger.info(f"   💰 Expected: {expected_amount} G$")
                logger.info(f"   👤 From: {seller_wallet}")
                logger.info(f"   🏪 To: {self.blockchain_service.merchant_address}")

                # Check blockchain for deposit
                deposit_result = await self.blockchain_service.verify_seller_deposit(
                    seller_wallet, expected_amount, trade_id
                )

                verification_details.append({
                    "trade_id": trade_id,
                    "seller": seller_wallet[:8] + "...",
                    "buyer": buyer_wallet[:8] + "...",
                    "amount": expected_amount,
                    "verified": deposit_result.get('verified', False),
                    "tx_hash": deposit_result.get('tx_hash', 'None'),
                    "error": deposit_result.get('error', 'None')
                })

                if deposit_result.get('success') and deposit_result.get('verified') and deposit_result.get('tx_hash'):
                    # Update trade status
                    update_result = self.supabase.table('p2p_trades').update({
                        'status': 'escrow_active',
                        'seller_deposit_tx': deposit_result['tx_hash'],
                        'seller_deposited_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat()
                    }).eq('trade_id', trade_id).execute()

                    if update_result.data:
                        verified_count += 1
                        logger.info(f"✅ VERIFIED & UPDATED trade {trade_id}")
                        logger.info(f"   TX: {deposit_result['tx_hash']}")
                        logger.info(f"   Amount: {deposit_result['amount']} G$")
                        
                        # Log escrow action
                        await self.log_escrow_action(trade_id, "deposit_confirmed", 
                                                   expected_amount, 
                                                   deposit_result['tx_hash'])
                    else:
                        logger.error(f"❌ Database update failed for trade {trade_id}")
                else:
                    logger.warning(f"⏳ No deposit found for trade {trade_id}")
                    if deposit_result.get('error'):
                        logger.warning(f"   Error: {deposit_result['error']}")

            logger.info(f"🎯 VERIFICATION COMPLETE: {verified_count}/{checked_count} deposits verified")
            
            # Log summary
            for detail in verification_details:
                status = "✅ VERIFIED" if detail['verified'] else "❌ PENDING"
                logger.info(f"   {detail['trade_id']}: {status} - {detail['amount']} G$ from {detail['seller']}")

            return {
                "success": True,
                "deposits_verified": verified_count,
                "trades_checked": checked_count,
                "verification_details": verification_details,
                "message": f"Verified {verified_count} out of {checked_count} pending deposits"
            }

        except Exception as e:
            logger.error(f"❌ VERIFICATION ERROR: {e}")
            return {
                "success": False, 
                "error": str(e), 
                "deposits_verified": 0,
                "trades_checked": 0
            }

    async def start_monitoring_service(self) -> Dict[str, Any]:
        """Restart the P2P blockchain monitoring service"""
        try:
            logger.info("🔄 Starting P2P blockchain monitoring service...")

            # Check if blockchain service is connected
            if not self.blockchain_service.w3.is_connected():
                logger.error("❌ Blockchain service not connected")
                return {"success": False, "error": "Blockchain not connected"}

            # Auto-verify any pending deposits first
            verification_result = await self.auto_verify_pending_deposits()

            logger.info("✅ P2P blockchain monitoring service restarted")
            return {
                "success": True,
                "message": "Monitoring service active",
                "merchant_address": self.blockchain_service.merchant_address,
                "verification_result": verification_result
            }

        except Exception as e:
            logger.error(f"❌ Error starting monitoring service: {e}")
            return {"success": False, "error": str(e)}

# Global service instance
p2p_trading_service = P2PTradingService()

def init_p2p_trading(app):
    """Initialize P2P Trading module with Flask app"""
    try:
        logger.info("🔄 Initializing P2P Trading system...")

        # Import and register blueprint
        from .routes import p2p_bp
        app.register_blueprint(p2p_bp, url_prefix='/p2p')

        logger.info("✅ P2P Trading system initialized successfully")
        logger.info("🔄 Available endpoints:")
        logger.info("   GET  /p2p/ - P2P Trading Dashboard")
        logger.info("   POST /p2p/create-order - Create sell order") 
        logger.info("   GET  /p2p/orders - Get available orders")
        logger.info("   POST /p2p/accept-order - Accept order")
        logger.info("   POST /p2p/confirm-deposit - Confirm seller deposit")
        logger.info("   POST /p2p/confirm-payment - Confirm buyer payment")
        logger.info("   POST /p2p/confirm-receipt - Confirm payment receipt")
        logger.info("   POST /p2p/cancel-trade - Cancel trade")
        logger.info("   GET  /p2p/my-trades - Get user trades")
        logger.info("   GET  /p2p/stats - Get trading stats")

        return True

    except Exception as e:
        logger.error(f"❌ P2P Trading initialization failed: {e}")
        return False
