
import logging
import asyncio
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for
from .p2p_service import p2p_trading_service

logger = logging.getLogger(__name__)

# Create P2P Trading Blueprint
p2p_bp = Blueprint('p2p', __name__)

def p2p_auth_required(f):
    """Decorator for P2P endpoints requiring authentication"""
    def wrapper(*args, **kwargs):
        if not session.get("verified") or not session.get("wallet"):
            return jsonify({"success": False, "error": "Authentication required"}), 401
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

def p2p_terms_required(f):
    """Decorator for P2P endpoints requiring terms acceptance"""
    def wrapper(*args, **kwargs):
        if not session.get("verified") or not session.get("wallet"):
            return jsonify({"success": False, "error": "Authentication required"}), 401
        if not session.get("p2p_terms_accepted"):
            return jsonify({"success": False, "error": "P2P terms acceptance required"}), 403
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@p2p_bp.route('/terms')
@p2p_auth_required
def p2p_terms():
    """P2P Trading Terms & Conditions"""
    wallet = session.get("wallet")
    return render_template('p2p_terms.html', wallet=wallet)

@p2p_bp.route('/accept-terms', methods=['POST'])
@p2p_auth_required
def accept_p2p_terms():
    """Accept P2P Trading terms"""
    try:
        wallet = session.get("wallet")
        data = request.get_json()

        # Store P2P terms acceptance in session
        session["p2p_terms_accepted"] = True
        session.permanent = True  # Make session permanent

        logger.info(f"✅ P2P Terms accepted by {wallet[:8]}...")

        return jsonify({
            "success": True,
            "message": "P2P Trading terms accepted successfully",
            "redirect_to": "/p2p/"
        })

    except Exception as e:
        logger.error(f"❌ Error accepting P2P terms: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/')
@p2p_auth_required
def p2p_dashboard():
    """P2P Trading dashboard"""
    wallet = session.get("wallet")

    # Get user's recent trades
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        recent_trades = loop.run_until_complete(
            p2p_trading_service.get_user_trades(wallet, limit=5)
        )

        # Get available orders
        available_orders = loop.run_until_complete(
            p2p_trading_service.get_available_orders(buyer_wallet=wallet, limit=10)
        )

        # Get trading stats
        trading_stats = p2p_trading_service.get_trading_stats()

        # Get user rating
        user_rating = loop.run_until_complete(
            p2p_trading_service.get_user_rating(wallet)
        )

    finally:
        loop.close()

    return render_template('p2p_trading.html', 
                         wallet=wallet,
                         recent_trades=recent_trades,
                         available_orders=available_orders,
                         trading_stats=trading_stats,
                         user_rating=user_rating,
                         payment_methods=p2p_trading_service.payment_methods,
                         fiat_currencies=p2p_trading_service.fiat_currencies)

@p2p_bp.route('/create-order', methods=['POST'])
@p2p_auth_required
def create_sell_order():
    """Create a new sell order"""
    try:
        wallet = session.get("wallet")
        data = request.get_json()

        required_fields = ['g_dollar_amount', 'g_dollar_price_usd', 'fiat_amount', 'fiat_currency', 'payment_method']
        for field in required_fields:
            if field not in data:
                return jsonify({"success": False, "error": f"Missing field: {field}"}), 400

        # Run async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                p2p_trading_service.create_sell_order(
                    seller_wallet=wallet,
                    g_dollar_amount=float(data['g_dollar_amount']),
                    g_dollar_price_usd=float(data['g_dollar_price_usd']),
                    fiat_amount=float(data['fiat_amount']),
                    fiat_currency=data['fiat_currency'],
                    payment_method=data['payment_method'],
                    description=data.get('description', ''),
                    payment_details=data.get('payment_details', '')
                )
            )
        finally:
            loop.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error creating sell order: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/orders', methods=['GET'])
@p2p_auth_required
def get_available_orders():
    """Get available sell orders"""
    try:
        wallet = session.get("wallet")

        # Get query parameters
        fiat_currency = request.args.get('fiat_currency')
        payment_method = request.args.get('payment_method')
        limit = int(request.args.get('limit', 20))

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            orders = loop.run_until_complete(
                p2p_trading_service.get_available_orders(
                    buyer_wallet=wallet,
                    fiat_currency=fiat_currency,
                    payment_method=payment_method,
                    limit=limit
                )
            )
        finally:
            loop.close()

        return jsonify({
            "success": True,
            "orders": orders,
            "total": len(orders)
        })

    except Exception as e:
        logger.error(f"❌ Error getting orders: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/accept-order', methods=['POST'])
@p2p_auth_required
def accept_order():
    """Accept a sell order"""
    try:
        wallet = session.get("wallet")
        data = request.get_json()

        if 'order_id' not in data:
            return jsonify({"success": False, "error": "Order ID required"}), 400

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                p2p_trading_service.accept_order(wallet, data['order_id'])
            )
        finally:
            loop.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error accepting order: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/confirm-deposit', methods=['POST'])
@p2p_auth_required
def confirm_seller_deposit():
    """Confirm seller has deposited G$ to escrow"""
    try:
        wallet = session.get("wallet")
        data = request.get_json()

        if 'trade_id' not in data:
            return jsonify({"success": False, "error": "Trade ID required"}), 400

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                p2p_trading_service.confirm_seller_deposit(data['trade_id'], wallet)
            )
        finally:
            loop.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error confirming deposit: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/confirm-payment', methods=['POST'])
@p2p_auth_required
def confirm_buyer_payment():
    """Confirm buyer has sent fiat payment"""
    try:
        wallet = session.get("wallet")
        data = request.get_json()

        if 'trade_id' not in data:
            return jsonify({"success": False, "error": "Trade ID required"}), 400

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                p2p_trading_service.confirm_buyer_payment(
                    data['trade_id'], 
                    wallet, 
                    data.get('payment_proof_url')
                )
            )
        finally:
            loop.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error confirming payment: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/upload-payment-proof', methods=['POST'])
@p2p_auth_required
def upload_payment_proof():
    """Upload payment proof via ImgBB"""
    try:
        wallet = session.get("wallet")
        data = request.get_json()

        required_fields = ['trade_id', 'proof_url']
        for field in required_fields:
            if field not in data:
                return jsonify({"success": False, "error": f"Missing field: {field}"}), 400

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                p2p_trading_service.upload_payment_proof(
                    data['trade_id'], 
                    wallet, 
                    data['proof_url']
                )
            )
        finally:
            loop.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error uploading payment proof: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/confirm-receipt', methods=['POST'])
@p2p_auth_required
def confirm_payment_receipt():
    """Confirm seller received fiat payment"""
    try:
        wallet = session.get("wallet")
        data = request.get_json()

        if 'trade_id' not in data:
            return jsonify({"success": False, "error": "Trade ID required"}), 400

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                p2p_trading_service.confirm_seller_received_payment(data['trade_id'], wallet)
            )
        finally:
            loop.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error confirming receipt: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/cancel-trade', methods=['POST'])
@p2p_auth_required
def cancel_trade():
    """Cancel a trade"""
    try:
        wallet = session.get("wallet")
        data = request.get_json()

        if 'trade_id' not in data:
            return jsonify({"success": False, "error": "Trade ID required"}), 400

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                p2p_trading_service.cancel_trade(
                    data['trade_id'], 
                    wallet, 
                    data.get('reason', '')
                )
            )
        finally:
            loop.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error cancelling trade: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/my-orders', methods=['GET'])
@p2p_auth_required
def get_my_orders():
    """Get user's own sell orders"""
    try:
        wallet = session.get("wallet")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            orders = loop.run_until_complete(
                p2p_trading_service.get_user_orders(wallet)
            )
        finally:
            loop.close()

        return jsonify({
            "success": True,
            "orders": orders,
            "total": len(orders)
        })

    except Exception as e:
        logger.error(f"❌ Error getting user orders: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/my-orders-with-trades', methods=['GET'])
@p2p_auth_required
def get_my_orders_with_trades():
    """Get user's own sell orders with active trade information"""
    try:
        wallet = session.get("wallet")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            orders = loop.run_until_complete(
                p2p_trading_service.get_user_orders_with_trades(wallet)
            )
        finally:
            loop.close()

        return jsonify({
            "success": True,
            "orders": orders,
            "total": len(orders)
        })

    except Exception as e:
        logger.error(f"❌ Error getting user orders with trades: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/my-trades', methods=['GET'])
@p2p_auth_required
def get_my_trades():
    """Get user's trade history"""
    try:
        wallet = session.get("wallet")
        limit = int(request.args.get('limit', 20))

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            trades = loop.run_until_complete(
                p2p_trading_service.get_user_trades(wallet, limit)
            )
        finally:
            loop.close()

        return jsonify({
            "success": True,
            "trades": trades,
            "total": len(trades)
        })

    except Exception as e:
        logger.error(f"❌ Error getting user trades: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/trade/<trade_id>', methods=['GET'])
@p2p_auth_required
def get_trade_details(trade_id):
    """Get detailed trade information"""
    try:
        wallet = session.get("wallet")
        logger.info(f"🔍 Trade details request: user {wallet[:8]}... requesting trade {trade_id}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            trade = loop.run_until_complete(
                p2p_trading_service.get_trade_by_id(trade_id)
            )
        finally:
            loop.close()

        if not trade:
            logger.error(f"❌ Trade not found: {trade_id}")
            return jsonify({"success": False, "error": "Trade not found"}), 404

        logger.info(f"✅ Found trade: {trade_id}, buyer: {trade['buyer_wallet'][:8]}..., seller: {trade['seller_wallet'][:8]}...")

        # Check if user is involved in this trade
        if wallet.lower() not in [trade["buyer_wallet"].lower(), trade["seller_wallet"].lower()]:
            logger.error(f"❌ Unauthorized access attempt: user {wallet} not in trade participants {trade['buyer_wallet']}, {trade['seller_wallet']}")
            return jsonify({"success": False, "error": "Unauthorized"}), 403

        return jsonify({
            "success": True,
            "trade": trade
        })

    except Exception as e:
        logger.error(f"❌ Error getting trade details: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/stats', methods=['GET'])
@p2p_auth_required
def get_trading_stats():
    """Get platform trading statistics"""
    try:
        stats = p2p_trading_service.get_trading_stats()

        return jsonify({
            "success": True,
            "stats": stats
        })

    except Exception as e:
        logger.error(f"❌ Error getting stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/order/<order_id>', methods=['GET'])
@p2p_auth_required
def get_order_details(order_id):
    """Get detailed order information"""
    try:
        wallet = session.get("wallet")
        logger.info(f"🔍 Order details request: user {wallet[:8]}... requesting order {order_id}")

        if not p2p_trading_service.supabase:
            return jsonify({"success": False, "error": "Database not available"}), 500

        # Get order details
        order_result = p2p_trading_service.supabase.table("p2p_orders")\
            .select("*")\
            .eq("order_id", order_id)\
            .execute()

        if not order_result.data:
            logger.error(f"❌ Order not found: {order_id}")
            return jsonify({"success": False, "error": "Order not found"}), 404

        order = order_result.data[0]
        
        # Check if there's an active trade for this order
        trade_result = p2p_trading_service.supabase.table("p2p_trades")\
            .select("*")\
            .eq("order_id", order_id)\
            .order("created_at", desc=True)\
            .limit(1)\
            .execute()

        active_trade = None
        if trade_result.data:
            active_trade = trade_result.data[0]

        logger.info(f"✅ Found order: {order_id}, seller: {order['seller_wallet'][:8]}...")

        return jsonify({
            "success": True,
            "order": order,
            "active_trade": active_trade
        })

    except Exception as e:
        logger.error(f"❌ Error getting order details: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/user-rating/<wallet_address>', methods=['GET'])
@p2p_auth_required
def get_user_rating(wallet_address):
    """Get user's trading rating"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            rating = loop.run_until_complete(
                p2p_trading_service.get_user_rating(wallet_address)
            )
        finally:
            loop.close()

        return jsonify({
            "success": True,
            "rating": rating
        })

    except Exception as e:
        logger.error(f"❌ Error getting user rating: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/merchant-info', methods=['GET'])
@p2p_auth_required
def get_merchant_info():
    """Get merchant address for deposits"""
    try:
        from .blockchain import p2p_blockchain_service

        return jsonify({
            "success": True,
            "merchant_address": p2p_blockchain_service.merchant_address,
            "message": "Send G$ to this address for escrow"
        })

    except Exception as e:
        logger.error(f"❌ Error getting merchant info: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/monitor-deposits', methods=['POST'])
@p2p_auth_required
def monitor_deposits():
    """Monitor and verify pending deposits automatically"""
    try:
        wallet = session.get("wallet")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                p2p_trading_service.auto_verify_pending_deposits()
            )
        finally:
            loop.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error monitoring deposits: {e}")
        return jsonify({"success": False, "error": str(e)}), 500



@p2p_bp.route('/start-monitoring', methods=['POST'])
@p2p_auth_required
def start_monitoring():
    """Start blockchain monitoring service"""
    try:
        wallet = session.get("wallet")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                p2p_trading_service.start_monitoring_service()
            )
        finally:
            loop.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error starting monitoring: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/history', methods=['GET'])
@p2p_auth_required
def get_p2p_history():
    """Get P2P trading history for dashboard integration"""
    try:
        wallet = session.get("wallet")
        limit = int(request.args.get('limit', 50))

        logger.info(f"📋 Getting P2P history for {wallet[:8]}... (limit: {limit})")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            trades = loop.run_until_complete(
                p2p_trading_service.get_user_trades(wallet, limit)
            )
        finally:
            loop.close()

        # Format trades for dashboard display
        formatted_trades = []
        for trade in trades:
            # Get the appropriate transaction hash based on role and status
            tx_hash = None
            if trade.get('status') == 'completed':
                tx_hash = trade.get('release_tx_hash') or trade.get('seller_deposit_tx')
            elif trade.get('status') in ['escrow_active', 'payment_sent']:
                tx_hash = trade.get('seller_deposit_tx')
            
            # Ensure transaction hash has 0x prefix if it exists
            if tx_hash and not tx_hash.startswith('0x'):
                tx_hash = '0x' + tx_hash

            formatted_trade = {
                'trade_id': trade.get('trade_id'),
                'g_dollar_amount': trade.get('g_dollar_amount'),
                'fiat_amount': trade.get('fiat_amount'),
                'fiat_currency': trade.get('fiat_currency'),
                'payment_method': trade.get('payment_method'),
                'status': trade.get('status'),
                'user_role': trade.get('user_role'),
                'counterpart': trade.get('counterpart_display'),
                'created_at': trade.get('created_at'),
                'completed_at': trade.get('completed_at'),
                'transaction_hash': tx_hash,
                'seller_wallet': trade.get('seller_wallet'),
                'buyer_wallet': trade.get('buyer_wallet'),
                'seller_deposit_tx': trade.get('seller_deposit_tx'),
                'release_tx_hash': trade.get('release_tx_hash')
            }
            formatted_trades.append(formatted_trade)

        logger.info(f"✅ Found {len(formatted_trades)} P2P trades for {wallet[:8]}...")

        return jsonify({
            "success": True,
            "trades": formatted_trades,
            "total": len(formatted_trades)
        })

    except Exception as e:
        logger.error(f"❌ Error getting P2P history: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@p2p_bp.route('/debug-orders', methods=['GET'])
@p2p_auth_required
def debug_orders():
    """Debug endpoint to check orders in database"""
    try:
        if not p2p_trading_service.supabase:
            return jsonify({"success": False, "error": "Database not available"})

        # Get all orders
        all_orders = p2p_trading_service.supabase.table("p2p_orders").select("*").execute()

        # Get active orders
        active_orders = p2p_trading_service.supabase.table("p2p_orders").select("*").eq("status", "active").execute()

        return jsonify({
            "success": True,
            "total_orders": len(all_orders.data) if all_orders.data else 0,
            "active_orders": len(active_orders.data) if active_orders.data else 0,
            "all_orders": all_orders.data[:5] if all_orders.data else [],  # First 5 for debugging
            "active_orders_list": active_orders.data if active_orders.data else []
        })

    except Exception as e:
        logger.error(f"❌ Error debugging orders: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/fix-orders', methods=['POST'])
@p2p_auth_required
def fix_orders():
    """Fix order statuses and make them available"""
    try:
        if not p2p_trading_service.supabase:
            return jsonify({"success": False, "error": "Database not available"})

        # Get all orders
        all_orders = p2p_trading_service.supabase.table("p2p_orders").select("*").execute()
        
        if not all_orders.data:
            return jsonify({"success": False, "error": "No orders found"})

        fixed_orders = []
        
        for order in all_orders.data:
            # Check if order has any completed trades
            trades = p2p_trading_service.supabase.table("p2p_trades")\
                .select("*")\
                .eq("order_id", order["order_id"])\
                .execute()
            
            # If no trades or no completed trades, make order active
            has_completed_trade = any(trade.get("status") == "completed" for trade in (trades.data or []))
            
            if not has_completed_trade and order.get("status") != "active":
                # Fix the order status
                update_result = p2p_trading_service.supabase.table("p2p_orders")\
                    .update({"status": "active"})\
                    .eq("id", order["id"])\
                    .execute()
                
                if update_result.data:
                    fixed_orders.append(order["order_id"])
                    logger.info(f"✅ Fixed order {order['order_id']} - set to active")

        return jsonify({
            "success": True,
            "message": f"Fixed {len(fixed_orders)} orders",
            "fixed_orders": fixed_orders
        })

    except Exception as e:
        logger.error(f"❌ Error fixing orders: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@p2p_bp.route('/create-test-order', methods=['POST'])
@p2p_auth_required
def create_test_order():
    """Create test order for debugging"""
    try:
        wallet = session.get("wallet")

        # Create a test sell order
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                p2p_trading_service.create_sell_order(
                    seller_wallet="0x742d35Cc6634C0532925a3b8D7389Fa63B1F5a6f",  # Different wallet for testing
                    g_dollar_amount=100.0,
                    g_dollar_price_usd=0.001,  # Add missing required field
                    fiat_amount=50.0,
                    fiat_currency="USD",
                    payment_method="PayPal",
                    description="Test order for debugging"
                )
            )
        finally:
            loop.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error creating test order: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
