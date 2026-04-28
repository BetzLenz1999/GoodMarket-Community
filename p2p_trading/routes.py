"""
Flask routes for the trustless P2P escrow flow.

Every route here either:
* returns an **unsigned** transaction payload that the user's wallet (the
  browser via WalletConnect / MiniPay) is expected to sign and broadcast,
  *or*
* returns read-only state combined from the on-chain contract and the
  Supabase mirror.

The only route that touches a private key on the server side is
``/p2p/admin/resolve-dispute``, which uses the ADMIN_KEY set on the
environment for arbiter actions.
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Dict

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .escrow_service import escrow_service
from .indexer import get_indexer

logger = logging.getLogger(__name__)

p2p_bp = Blueprint("p2p", __name__)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _wallet_from_session() -> str:
    return (session.get("wallet") or session.get("wallet_address") or "").lower()


def _is_admin(wallet: str) -> bool:
    """Return True if the connected wallet is the contract arbiter (ADMIN_KEY).

    Falls back to any address listed in the ``P2P_ADMIN_WALLETS`` env var
    (comma-separated) so we can support multiple admin reviewers without
    sharing the ADMIN_KEY.
    """
    import os

    if not wallet:
        return False
    wallet = wallet.lower()
    admin_addr = (escrow_service.contract.admin_address or "").lower()
    if wallet == admin_addr:
        return True
    extras = os.getenv("P2P_ADMIN_WALLETS", "")
    for addr in (a.strip().lower() for a in extras.split(",")):
        if addr and addr == wallet:
            return True
    return False


def p2p_auth_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("verified") or not _wallet_from_session():
            if request.is_json or request.path.startswith("/p2p/api/"):
                return jsonify(
                    {"success": False, "error": "Authentication required"}
                ), 401
            return redirect(url_for("home"))
        return f(*args, **kwargs)

    return wrapper


def p2p_terms_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("verified") or not _wallet_from_session():
            if request.is_json or request.path.startswith("/p2p/api/"):
                return jsonify(
                    {"success": False, "error": "Authentication required"}
                ), 401
            return redirect(url_for("home"))
        if not session.get("p2p_terms_accepted"):
            if request.is_json or request.path.startswith("/p2p/api/"):
                return jsonify(
                    {
                        "success": False,
                        "error": "P2P terms acceptance required",
                        "redirect": url_for("p2p.p2p_terms"),
                    }
                ), 403
            return redirect(url_for("p2p.p2p_terms"))
        return f(*args, **kwargs)

    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        wallet = _wallet_from_session()
        if not wallet or not session.get("verified"):
            return jsonify(
                {"success": False, "error": "Authentication required"}
            ), 401
        if not _is_admin(wallet):
            return jsonify({"success": False, "error": "Forbidden"}), 403
        return f(*args, **kwargs)

    return wrapper


def _json_body() -> Dict[str, Any]:
    return request.get_json(silent=True) or {}


# ---------------------------------------------------------------------------
# HTML pages
# ---------------------------------------------------------------------------


@p2p_bp.route("/terms")
@p2p_auth_required
def p2p_terms():
    return render_template("p2p_terms.html", wallet=_wallet_from_session())


@p2p_bp.route("/accept-terms", methods=["POST"])
@p2p_auth_required
def accept_p2p_terms():
    session["p2p_terms_accepted"] = True
    session.permanent = True
    return jsonify(
        {
            "success": True,
            "message": "P2P Trading terms accepted",
            "redirect_to": "/p2p/",
        }
    )


@p2p_bp.route("/")
@p2p_terms_required
def p2p_dashboard():
    wallet = _wallet_from_session()
    return render_template(
        "p2p_trading.html",
        wallet=wallet,
        contract=escrow_service.contract_status(),
        payment_methods=escrow_service.payment_methods,
        fiat_currencies=escrow_service.fiat_currencies,
        is_admin=_is_admin(wallet),
    )


# ---------------------------------------------------------------------------
# Contract / config endpoints
# ---------------------------------------------------------------------------


@p2p_bp.route("/api/contract")
@p2p_auth_required
def api_contract_info():
    return jsonify({"success": True, **escrow_service.contract_status()})


@p2p_bp.route("/api/config")
@p2p_auth_required
def api_config():
    return jsonify(
        {
            "success": True,
            "payment_methods": escrow_service.payment_methods,
            "fiat_currencies": escrow_service.fiat_currencies,
            "min_ad_amount_gd": 20_000,
            "default_payment_window_seconds": (
                escrow_service.DEFAULT_PAYMENT_WINDOW_SECONDS
            ),
        }
    )


# ---------------------------------------------------------------------------
# Browse / read APIs
# ---------------------------------------------------------------------------


@p2p_bp.route("/api/ads")
@p2p_terms_required
def api_list_ads():
    wallet = _wallet_from_session()
    fiat = request.args.get("fiat_currency")
    method = request.args.get("payment_method")
    limit = min(int(request.args.get("limit", 50)), 200)
    ads = escrow_service.list_open_ads(
        viewer_wallet=wallet,
        fiat_currency=fiat,
        payment_method=method,
        limit=limit,
    )
    return jsonify({"success": True, "ads": ads, "count": len(ads)})


@p2p_bp.route("/api/ads/mine")
@p2p_terms_required
def api_my_ads():
    wallet = _wallet_from_session()
    ads = escrow_service.get_my_ads(wallet)
    return jsonify({"success": True, "ads": ads, "count": len(ads)})


@p2p_bp.route("/api/trades/mine")
@p2p_terms_required
def api_my_trades():
    wallet = _wallet_from_session()
    limit = min(int(request.args.get("limit", 50)), 200)
    trades = escrow_service.get_my_trades(wallet, limit=limit)
    return jsonify({"success": True, "trades": trades, "count": len(trades)})


@p2p_bp.route("/api/orders/<order_id>")
@p2p_terms_required
def api_get_order(order_id: str):
    order = escrow_service.get_order(order_id)
    if not order:
        return jsonify({"success": False, "error": "Order not found"}), 404
    return jsonify({"success": True, "order": order})


@p2p_bp.route("/api/trades/<trade_id>")
@p2p_terms_required
def api_get_trade(trade_id: str):
    trade = escrow_service.get_trade(trade_id)
    if not trade:
        return jsonify({"success": False, "error": "Trade not found"}), 404
    wallet = _wallet_from_session()
    if (
        wallet
        and wallet not in (
            (trade.get("buyer_wallet") or "").lower(),
            (trade.get("seller_wallet") or "").lower(),
        )
        and not _is_admin(wallet)
    ):
        return jsonify({"success": False, "error": "Forbidden"}), 403
    return jsonify({"success": True, "trade": trade})


# ---------------------------------------------------------------------------
# Tx-prep endpoints — return unsigned transactions for wallet signing
# ---------------------------------------------------------------------------


@p2p_bp.route("/api/ads/prepare-open", methods=["POST"])
@p2p_terms_required
def api_prepare_open_ad():
    wallet = _wallet_from_session()
    body = _json_body()
    try:
        result = escrow_service.prepare_open_ad(
            seller_wallet=wallet,
            total_g_dollar=float(body.get("total_g_dollar")),
            min_order_g_dollar=float(body.get("min_order_g_dollar")),
            max_order_g_dollar=float(body.get("max_order_g_dollar")),
            fiat_amount=float(body.get("fiat_amount")),
            fiat_currency=body.get("fiat_currency"),
            payment_method=body.get("payment_method"),
            payment_details=body.get("payment_details", ""),
            description=body.get("description", ""),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": f"Invalid input: {exc}"}), 400
    return jsonify(result), (200 if result.get("success") else 400)


@p2p_bp.route("/api/ads/<order_id>/prepare-close", methods=["POST"])
@p2p_terms_required
def api_prepare_close_ad(order_id: str):
    wallet = _wallet_from_session()
    result = escrow_service.prepare_close_ad(wallet, order_id)
    return jsonify(result), (200 if result.get("success") else 400)


@p2p_bp.route("/api/orders/<order_id>/prepare-place", methods=["POST"])
@p2p_terms_required
def api_prepare_place_order(order_id: str):
    wallet = _wallet_from_session()
    body = _json_body()
    try:
        amount = float(body.get("amount_g_dollar"))
    except (TypeError, ValueError):
        return jsonify(
            {"success": False, "error": "Missing/invalid amount_g_dollar"}
        ), 400
    window = body.get("payment_window_seconds")
    try:
        window = int(window) if window is not None else None
    except (TypeError, ValueError):
        return jsonify(
            {"success": False, "error": "Invalid payment_window_seconds"}
        ), 400
    result = escrow_service.prepare_place_order(
        buyer_wallet=wallet,
        order_id=order_id,
        amount_g_dollar=amount,
        payment_window_seconds=window,
    )
    return jsonify(result), (200 if result.get("success") else 400)


@p2p_bp.route("/api/trades/<trade_id>/upload-proof", methods=["POST"])
@p2p_terms_required
def api_upload_proof(trade_id: str):
    wallet = _wallet_from_session()
    body = _json_body()
    proof_url = (body.get("proof_url") or "").strip()
    result = escrow_service.upload_payment_proof(wallet, trade_id, proof_url)
    return jsonify(result), (200 if result.get("success") else 400)


@p2p_bp.route("/api/trades/<trade_id>/prepare-mark-paid", methods=["POST"])
@p2p_terms_required
def api_prepare_mark_paid(trade_id: str):
    wallet = _wallet_from_session()
    result = escrow_service.prepare_mark_paid(wallet, trade_id)
    return jsonify(result), (200 if result.get("success") else 400)


@p2p_bp.route("/api/trades/<trade_id>/prepare-release", methods=["POST"])
@p2p_terms_required
def api_prepare_release(trade_id: str):
    wallet = _wallet_from_session()
    result = escrow_service.prepare_release(wallet, trade_id)
    return jsonify(result), (200 if result.get("success") else 400)


@p2p_bp.route("/api/trades/<trade_id>/prepare-cancel", methods=["POST"])
@p2p_terms_required
def api_prepare_cancel(trade_id: str):
    wallet = _wallet_from_session()
    result = escrow_service.prepare_cancel_order(wallet, trade_id)
    return jsonify(result), (200 if result.get("success") else 400)


@p2p_bp.route("/api/trades/<trade_id>/prepare-dispute", methods=["POST"])
@p2p_terms_required
def api_prepare_dispute(trade_id: str):
    wallet = _wallet_from_session()
    result = escrow_service.prepare_dispute(wallet, trade_id)
    return jsonify(result), (200 if result.get("success") else 400)


@p2p_bp.route("/api/tx-submitted", methods=["POST"])
@p2p_terms_required
def api_tx_submitted():
    wallet = _wallet_from_session()
    body = _json_body()
    kind = body.get("kind")
    identifier = body.get("identifier")
    tx_hash = body.get("tx_hash")
    if kind not in ("ad", "trade") or not identifier or not tx_hash:
        return jsonify(
            {"success": False, "error": "kind, identifier, tx_hash required"}
        ), 400
    result = escrow_service.record_tx_submitted(
        kind, identifier, tx_hash, wallet
    )
    return jsonify(result), (200 if result.get("success") else 400)


# ---------------------------------------------------------------------------
# Admin / arbiter endpoints
# ---------------------------------------------------------------------------


@p2p_bp.route("/api/admin/disputes")
@admin_required
def api_admin_list_disputes():
    disputes = escrow_service.get_disputes()
    return jsonify({"success": True, "disputes": disputes})


@p2p_bp.route("/api/admin/disputes/<trade_id>/resolve", methods=["POST"])
@admin_required
def api_admin_resolve_dispute(trade_id: str):
    body = _json_body()
    buyer_wins = bool(body.get("buyer_wins"))
    arbiter = _wallet_from_session()
    result = escrow_service.resolve_dispute(trade_id, buyer_wins, arbiter)
    return jsonify(result), (200 if result.get("success") else 400)


# ---------------------------------------------------------------------------
# Indexer / health endpoints
# ---------------------------------------------------------------------------


@p2p_bp.route("/api/indexer/poll", methods=["POST"])
@admin_required
def api_indexer_poll():
    counts = get_indexer().poll_once()
    last = get_indexer().get_last_indexed_block()
    return jsonify(
        {"success": True, "events": counts, "last_indexed_block": last}
    )


@p2p_bp.route("/api/indexer/state")
@admin_required
def api_indexer_state():
    indexer = get_indexer()
    return jsonify(
        {
            "success": True,
            "last_indexed_block": indexer.get_last_indexed_block(),
            "head_block": indexer.w3.eth.block_number
            if indexer.w3.is_connected()
            else None,
            "contract_address": indexer.contract.address,
            "deployed_block": indexer.contract.deployed_block,
        }
    )


# ---------------------------------------------------------------------------
# Module init helper, called from main.py
# ---------------------------------------------------------------------------


def init_p2p_trading(app) -> None:
    """Register the blueprint and (optionally) start the background indexer.

    The indexer is opt-in via the ``P2P_INDEXER_ENABLED`` env var so unit
    tests and short-lived workers don't spin up background threads.
    """
    import os

    app.register_blueprint(p2p_bp, url_prefix="/p2p")
    if os.getenv("P2P_INDEXER_ENABLED", "").lower() in ("1", "true", "yes"):
        try:
            get_indexer().start()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to start P2P escrow indexer: %s", exc)
