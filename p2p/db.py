"""
Supabase data-access helpers for P2P trading (offchain state).

Writes use the service-role (admin) client so RLS doesn't block the backend;
reads use the regular client. On-chain (P2PEscrow) remains the source of truth
for custody — these rows mirror it and hold price/chat/proof/dispute data.
"""
import logging
from datetime import datetime, timedelta, timezone

from supabase_client import get_supabase_client, get_supabase_admin_client

logger = logging.getLogger(__name__)


def _writer():
    return get_supabase_admin_client() or get_supabase_client()


def _reader():
    return get_supabase_client()


def _private_reader():
    """Read private P2P rows through the service-role client when available.

    P2P order, proof, chat, and dispute tables have RLS enabled because the
    parties are wallet-authenticated by Flask sessions rather than Supabase
    Auth users. Route handlers perform the wallet/party checks before returning
    rows, so these backend reads need to bypass Supabase RLS just like writes.
    """
    return get_supabase_admin_client() or get_supabase_client()


def _norm(addr):
    return (addr or "").strip().lower()


# ── Listings ────────────────────────────────────────────────────────────────
def create_listing(seller_wallet, total_gd, min_order_gd, price_usdt,
                   fiat_currency=None, fiat_rate=None, terms=None,
                   onchain_id=None, create_tx_hash=None):
    row = {
        "seller_wallet": _norm(seller_wallet),
        "total_gd": total_gd,
        "min_order_gd": min_order_gd,
        "price_usdt": price_usdt,
        "fiat_currency": fiat_currency,
        "fiat_rate": fiat_rate,
        "terms": terms,
        "status": "active",
        "onchain_id": onchain_id,
        "create_tx_hash": create_tx_hash,
    }
    res = _writer().table("p2p_listings").insert(row).execute()
    return res.data[0] if res.data else None


def update_listing(listing_id, fields):
    fields = {**fields, "updated_at": datetime.now(timezone.utc).isoformat()}
    res = _writer().table("p2p_listings").update(fields).eq("id", listing_id).execute()
    return res.data[0] if res.data else None


def list_active_listings(limit=100):
    res = (
        _reader()
        .table("p2p_listings")
        .select("*")
        .eq("status", "active")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []



def list_listings_for_seller(seller_wallet, limit=100):
    res = (
        _reader()
        .table("p2p_listings")
        .select("*")
        .eq("seller_wallet", _norm(seller_wallet))
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []

def get_listing_row(listing_id):
    res = _reader().table("p2p_listings").select("*").eq("id", listing_id).limit(1).execute()
    return res.data[0] if res.data else None


def get_listing_by_onchain(onchain_id):
    res = _reader().table("p2p_listings").select("*").eq("onchain_id", onchain_id).limit(1).execute()
    return res.data[0] if res.data else None


# ── Payment methods ─────────────────────────────────────────────────────────
def add_payment_method(seller_wallet, kind, label, details):
    row = {
        "seller_wallet": _norm(seller_wallet),
        "kind": kind,
        "label": label,
        "details": details or {},
        "active": True,
    }
    res = _writer().table("p2p_payment_methods").insert(row).execute()
    return res.data[0] if res.data else None


def list_payment_methods(seller_wallet):
    res = (
        _reader()
        .table("p2p_payment_methods")
        .select("*")
        .eq("seller_wallet", _norm(seller_wallet))
        .eq("active", True)
        .execute()
    )
    return res.data or []


def get_payment_method(payment_method_id):
    if not payment_method_id:
        return None
    res = (
        _reader()
        .table("p2p_payment_methods")
        .select("*")
        .eq("id", payment_method_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def _payment_method_label(payment_method):
    if not payment_method:
        return None
    label = payment_method.get("label") or payment_method.get("kind") or "payment_method"
    details = payment_method.get("details") or {}
    account = details.get("account") or details.get("address") or details.get("number")
    return f"{label}: {account}" if account else label


# ── Orders ──────────────────────────────────────────────────────────────────
def create_order(listing_row, buyer_wallet, amount_gd, pay_amount, pay_currency,
                payment_method_id=None, onchain_id=None, open_tx_hash=None,
                payment_window_seconds=1800):
    deadline = datetime.now(timezone.utc) + timedelta(seconds=payment_window_seconds)
    payment_method = get_payment_method(payment_method_id)
    if payment_method_id and (not payment_method or _norm(payment_method.get("seller_wallet")) != _norm(listing_row["seller_wallet"])):
        raise ValueError("Invalid payment method for this seller")
    if not payment_method:
        seller_methods = list_payment_methods(listing_row["seller_wallet"])
        payment_method = seller_methods[0] if seller_methods else None
        payment_method_id = payment_method.get("id") if payment_method else None
    payment_method_text = _payment_method_label(payment_method) or "Not specified"
    row = {
        "onchain_id": onchain_id,
        "listing_id": listing_row["id"],
        "listing_onchain_id": listing_row.get("onchain_id"),
        "buyer_wallet": _norm(buyer_wallet),
        "seller_wallet": _norm(listing_row["seller_wallet"]),
        "amount_gd": amount_gd,
        # Backward compatibility: some early P2P deployments created a
        # NOT NULL `g_dollar_amount` column before the current `amount_gd`
        # name was standardized. Supplying both keeps inserts working until
        # those databases are migrated.
        "g_dollar_amount": amount_gd,
        "pay_amount": pay_amount,
        # Backward compatibility: an early P2P order schema used a NOT NULL
        # `rate` column for the listing's USDT-per-G$ price. Current schemas
        # store that value on p2p_listings.price_usdt, but include it here so
        # legacy databases can still record the order mirror after the buyer
        # reserves funds on-chain.
        "rate": listing_row.get("price_usdt"),
        # Backward compatibility: some early P2P deployments used
        # `fiat_amount` for the off-chain payment total before the current
        # `pay_amount` name was standardized. Supplying both prevents legacy
        # NOT NULL constraints from rejecting new orders.
        "fiat_amount": pay_amount,
        "pay_currency": pay_currency,
        # Backward compatibility: some early P2P deployments used
        # `fiat_currency` for the order payment currency before the current
        # `pay_currency` name was standardized. Supplying both prevents
        # legacy NOT NULL constraints from rejecting new USDT orders.
        "fiat_currency": pay_currency,
        "payment_method_id": payment_method_id,
        # Backward compatibility: an early schema used a NOT NULL text
        # `payment_method` column instead of the current FK. Keep it filled
        # so old Supabase databases do not fail after the on-chain reserve.
        "payment_method": payment_method_text,
        "status": "open",
        "deadline": deadline.isoformat(),
        "open_tx_hash": open_tx_hash,
    }
    legacy_aliases = {
        "g_dollar_amount": "amount_gd",
        "fiat_amount": "pay_amount",
        "fiat_currency": "pay_currency",
        "payment_method": "payment_method_id",
        "rate": "price_usdt",
    }
    while True:
        try:
            res = _writer().table("p2p_orders").insert(row).execute()
            return res.data[0] if res.data else None
        except Exception as exc:
            message = str(exc)
            # Fresh/current schemas may not have one or more legacy alias
            # columns. Retry without only the missing alias named by the
            # PostgREST schema-cache error; legacy schemas with NOT NULL
            # aliases still succeed because those aliases remain populated.
            missing_alias = next(
                (alias for alias in legacy_aliases if alias in row and alias in message),
                None,
            )
            if not missing_alias or "schema cache" not in message.lower():
                raise
            logger.info("p2p_orders.%s not present; retrying order insert without legacy alias", missing_alias)
            row.pop(missing_alias, None)


def update_order(order_id, fields):
    fields = {**fields, "updated_at": datetime.now(timezone.utc).isoformat()}
    res = _writer().table("p2p_orders").update(fields).eq("id", order_id).execute()
    return res.data[0] if res.data else None


def get_order_row(order_id):
    res = _private_reader().table("p2p_orders").select("*").eq("id", order_id).limit(1).execute()
    return res.data[0] if res.data else None


def list_orders_for_wallet(wallet, role="buyer", limit=100):
    col = "seller_wallet" if role == "seller" else "buyer_wallet"
    res = (
        _private_reader()
        .table("p2p_orders")
        .select("*")
        .eq(col, _norm(wallet))
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def list_expired_open_orders(now_iso=None, limit=100):
    """Open orders whose payment deadline has already passed (candidates for
    auto-expiry/refund)."""
    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    res = (
        _private_reader()
        .table("p2p_orders")
        .select("*")
        .eq("status", "open")
        .lt("deadline", now_iso)
        .order("deadline", desc=False)
        .limit(limit)
        .execute()
    )
    return res.data or []


def list_open_or_paid_orders(limit=300):
    """Active orders (open|paid) used by the reconciler to sync on-chain state."""
    res = (
        _private_reader()
        .table("p2p_orders")
        .select("*")
        .in_("status", ["open", "paid"])
        .order("updated_at", desc=False)
        .limit(limit)
        .execute()
    )
    return res.data or []


def list_orders_by_status(statuses, limit=200):
    res = (
        _private_reader()
        .table("p2p_orders")
        .select("*")
        .in_("status", statuses)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


# ── Chat ────────────────────────────────────────────────────────────────────
def add_message(order_id, sender_wallet, body):
    row = {"order_id": order_id, "sender_wallet": _norm(sender_wallet), "body": body}
    res = _writer().table("p2p_messages").insert(row).execute()
    return res.data[0] if res.data else None


def list_messages(order_id, limit=500):
    res = (
        _private_reader()
        .table("p2p_messages")
        .select("*")
        .eq("order_id", order_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return res.data or []


# ── Proof of payment ────────────────────────────────────────────────────────
def add_proof(order_id, uploader_wallet, image_url, reference=None):
    row = {
        "order_id": order_id,
        "uploader_wallet": _norm(uploader_wallet),
        "image_url": image_url,
        "reference": reference,
    }
    res = _writer().table("p2p_proofs").insert(row).execute()
    return res.data[0] if res.data else None


def list_proofs(order_id):
    res = (
        _private_reader()
        .table("p2p_proofs")
        .select("*")
        .eq("order_id", order_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


# ── Disputes / admin review ─────────────────────────────────────────────────
def create_dispute(order_id, raised_by, reason=None):
    row = {"order_id": order_id, "raised_by": _norm(raised_by), "reason": reason, "status": "open"}
    res = _writer().table("p2p_disputes").insert(row).execute()
    return res.data[0] if res.data else None


def resolve_dispute_row(dispute_id, status, resolved_by, resolve_tx_hash=None):
    fields = {
        "status": status,
        "resolved_by": _norm(resolved_by),
        "resolve_tx_hash": resolve_tx_hash,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    res = _writer().table("p2p_disputes").update(fields).eq("id", dispute_id).execute()
    return res.data[0] if res.data else None


def get_open_dispute_for_order(order_id):
    res = (
        _private_reader()
        .table("p2p_disputes")
        .select("*")
        .eq("order_id", order_id)
        .eq("status", "open")
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None
