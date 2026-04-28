"""
Background indexer for GoodMarketP2PEscrow contract events.

The indexer is the *single source of truth* for translating on-chain state
into the rows that the API and UI read out of the ``p2p_orders`` and
``p2p_trades`` Supabase tables. The frontend sends user-signed transactions
directly to the contract; the indexer sees the resulting events and updates
the database accordingly.

Design choices:

* We poll ``eth_getLogs`` over a sliding block window rather than running
  ``eth_subscribe``: Forno (Celo's public RPC) doesn't expose websockets,
  and a polling indexer is much simpler to operate inside a Flask process.
* We persist the last-indexed block in the ``p2p_indexer_state`` table so
  restarts don't re-scan the chain from genesis.
* Each event handler is *idempotent*: it sets a target state and tx hash on
  the row, and it's safe to replay if the indexer falls behind or restarts
  mid-scan.
* The indexer never *creates* an order/trade row — it only updates rows
  that the API created when the user kicked off the flow. If we see an
  event for an unknown ad/trade id we log a warning but continue, so a
  tampered DB doesn't wedge the indexer.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from web3 import Web3

from .contract import P2PEscrowContract, _from_wei, get_contract

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hex_id(b: bytes) -> str:
    return "0x" + (b.hex() if isinstance(b, (bytes, bytearray)) else b)


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------


class P2PEscrowIndexer:
    """Polling indexer that reflects on-chain events into Supabase."""

    # How many blocks to scan per poll. Forno typically returns up to ~5,000
    # logs per call, and Celo blocks are ~5s, so 2000 blocks ≈ 2.7h of history.
    DEFAULT_BLOCK_WINDOW = 2_000

    # Sleep between polls (seconds). Celo blocks are ~5s, but for end-user UX
    # we don't need realtime — 15s gives ~3 confirmations of margin.
    DEFAULT_POLL_INTERVAL = 15

    # Minimum confirmation depth before we trust an event. Celo finality is
    # very fast but we still leave 2 blocks of margin to absorb reorgs.
    CONFIRMATION_DEPTH = 2

    def __init__(
        self,
        contract: Optional[P2PEscrowContract] = None,
        supabase: Any = None,
    ) -> None:
        self.contract = contract or get_contract()
        self.w3: Web3 = self.contract.w3
        self._supabase = supabase  # lazy-loaded if None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.poll_interval = int(
            os.getenv("P2P_INDEXER_POLL_INTERVAL", self.DEFAULT_POLL_INTERVAL)
        )
        self.block_window = int(
            os.getenv("P2P_INDEXER_BLOCK_WINDOW", self.DEFAULT_BLOCK_WINDOW)
        )

    # ---- supabase --------------------------------------------------------

    @property
    def supabase(self) -> Any:
        if self._supabase is None:
            from supabase_client import get_supabase_client  # local import

            self._supabase = get_supabase_client()
        return self._supabase

    # ---- state -----------------------------------------------------------

    def get_last_indexed_block(self) -> int:
        """Return the last block we successfully scanned through.

        Falls back to ``contract.deployed_block`` if no row exists yet.
        """
        if not self.supabase:
            return self.contract.deployed_block
        try:
            res = (
                self.supabase.table("p2p_indexer_state")
                .select("last_block")
                .eq("contract_address", self.contract.address.lower())
                .limit(1)
                .execute()
            )
            if res.data:
                return int(res.data[0]["last_block"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_last_indexed_block failed: %s", exc)
        return self.contract.deployed_block

    def set_last_indexed_block(self, block: int) -> None:
        if not self.supabase:
            return
        try:
            self.supabase.table("p2p_indexer_state").upsert(
                {
                    "contract_address": self.contract.address.lower(),
                    "last_block": block,
                    "updated_at": _utcnow_iso(),
                },
                on_conflict="contract_address",
            ).execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("set_last_indexed_block failed: %s", exc)

    # ---- main loop -------------------------------------------------------

    def start(self) -> None:
        """Start the indexer in a background daemon thread."""
        if self._thread and self._thread.is_alive():
            logger.info("P2PEscrowIndexer already running")
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_forever, name="p2p-escrow-indexer", daemon=True
        )
        self._thread.start()
        logger.info(
            "P2PEscrowIndexer started (poll=%ss, window=%s blocks)",
            self.poll_interval,
            self.block_window,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001
                logger.exception("indexer poll failed: %s", exc)
            self._stop.wait(self.poll_interval)

    def poll_once(self) -> Dict[str, int]:
        """Single poll iteration. Returns counts per event type processed."""
        if not self.w3.is_connected():
            logger.warning("RPC not connected; skipping poll")
            return {}

        latest = self.w3.eth.block_number
        safe_head = latest - self.CONFIRMATION_DEPTH
        from_block = self.get_last_indexed_block() + 1
        to_block = min(safe_head, from_block + self.block_window - 1)
        if to_block < from_block:
            return {}

        logger.debug(
            "indexer scanning blocks %s..%s (head=%s)",
            from_block,
            to_block,
            latest,
        )
        counts = self._scan_range(from_block, to_block)
        self.set_last_indexed_block(to_block)
        if counts:
            logger.info(
                "indexer processed %s events in [%s, %s]: %s",
                sum(counts.values()),
                from_block,
                to_block,
                counts,
            )
        return counts

    # ---- scanning --------------------------------------------------------

    def _scan_range(self, from_block: int, to_block: int) -> Dict[str, int]:
        events_to_handle = [
            ("AdOpened", self._on_ad_opened),
            ("AdClosed", self._on_ad_closed),
            ("AdExhausted", self._on_ad_exhausted),
            ("OrderPlaced", self._on_order_placed),
            ("OrderCancelled", self._on_order_cancelled),
            ("OrderExpired", self._on_order_expired),
            ("MarkedPaid", self._on_marked_paid),
            ("Released", self._on_released),
            ("AutoReleased", self._on_auto_released),
            ("Disputed", self._on_disputed),
            ("Resolved", self._on_resolved),
        ]
        counts: Dict[str, int] = {}
        for name, handler in events_to_handle:
            event = getattr(self.contract.contract.events, name, None)
            if event is None:
                continue
            try:
                logs = event.get_logs(from_block=from_block, to_block=to_block)
            except Exception as exc:  # noqa: BLE001
                logger.warning("get_logs(%s) failed: %s", name, exc)
                continue
            counts[name] = len(logs)
            for log in logs:
                try:
                    handler(log)
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "handler for %s failed on tx %s: %s",
                        name,
                        log.transactionHash.hex() if log.transactionHash else "?",
                        exc,
                    )
        # Drop zero counts so logs are tighter
        return {k: v for k, v in counts.items() if v}

    # ---- handlers --------------------------------------------------------

    def _tx_meta(self, log: Any) -> Dict[str, Any]:
        tx_hash = log.transactionHash
        if isinstance(tx_hash, (bytes, bytearray)):
            tx_hash = "0x" + tx_hash.hex()
        return {
            "tx_hash": tx_hash,
            "block_number": int(log.blockNumber),
        }

    def _update_order(
        self, ad_id: bytes, fields: Dict[str, Any]
    ) -> None:
        if not self.supabase:
            return
        ad_hex = _hex_id(ad_id)
        try:
            self.supabase.table("p2p_orders").update(fields).eq(
                "ad_id_onchain", ad_hex
            ).execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "update p2p_orders ad_id_onchain=%s failed: %s", ad_hex, exc
            )

    def _update_trade(
        self, trade_id: bytes, fields: Dict[str, Any]
    ) -> None:
        if not self.supabase:
            return
        trade_hex = _hex_id(trade_id)
        try:
            self.supabase.table("p2p_trades").update(fields).eq(
                "trade_id_onchain", trade_hex
            ).execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "update p2p_trades trade_id_onchain=%s failed: %s",
                trade_hex,
                exc,
            )

    def _refresh_ad_cache_for_trade(self, trade_id: bytes) -> None:
        """Re-read the chain to keep the ad row's cached counters coherent.

        Most trade-level events (cancel, release, expire, resolve, auto) don't
        carry the ad id, so we look up the trade then refresh the ad row.
        """
        trade = self.contract.get_trade(trade_id)
        if trade is None:
            return
        ad = self.contract.get_ad(trade.ad_id)
        if ad is None:
            return
        self._update_order(
            trade.ad_id,
            {
                "remaining_amount_gd": _from_wei(ad.remaining_amount),
                "active_trade_count": ad.active_trade_count,
                "onchain_status": "open" if ad.open else "closed",
            },
        )

    def _on_ad_opened(self, log: Any) -> None:
        # AdOpened(adId, seller, totalLocked, minOrder, maxOrder)
        args = log.args
        meta = self._tx_meta(log)
        self._update_order(
            args.adId,
            {
                "onchain_status": "open",
                "ad_open_tx": meta["tx_hash"],
                "ad_open_block": meta["block_number"],
                "total_locked_gd": _from_wei(int(args.totalLocked)),
                "remaining_amount_gd": _from_wei(int(args.totalLocked)),
                "min_order_gd": _from_wei(int(args.minOrder)),
                "max_order_gd": _from_wei(int(args.maxOrder)),
                "onchain_confirmed_at": _utcnow_iso(),
            },
        )

    def _on_ad_closed(self, log: Any) -> None:
        # AdClosed(adId, seller, refundedAmount)
        args = log.args
        meta = self._tx_meta(log)
        self._update_order(
            args.adId,
            {
                "onchain_status": "closed",
                "ad_close_tx": meta["tx_hash"],
                "ad_close_block": meta["block_number"],
                "refunded_amount_gd": _from_wei(int(args.refundedAmount)),
                "closed_at": _utcnow_iso(),
            },
        )

    def _on_ad_exhausted(self, log: Any) -> None:
        # AdExhausted(adId) — emitted when remainingAmount drops to 0.
        args = log.args
        self._update_order(
            args.adId,
            {"remaining_amount_gd": 0.0, "exhausted_at": _utcnow_iso()},
        )

    def _on_order_placed(self, log: Any) -> None:
        # OrderPlaced(tradeId, adId, buyer, amount, deadline)
        args = log.args
        meta = self._tx_meta(log)
        self._update_trade(
            args.tradeId,
            {
                "onchain_status": "payment_pending",
                "place_order_tx": meta["tx_hash"],
                "place_order_block": meta["block_number"],
                "g_dollar_amount": _from_wei(int(args.amount)),
                "payment_deadline": int(args.deadline),
                "onchain_confirmed_at": _utcnow_iso(),
            },
        )
        # Refresh ad cache directly via adId from the event.
        ad = self.contract.get_ad(args.adId)
        if ad is not None:
            self._update_order(
                args.adId,
                {
                    "remaining_amount_gd": _from_wei(ad.remaining_amount),
                    "active_trade_count": ad.active_trade_count,
                },
            )

    def _on_order_cancelled(self, log: Any) -> None:
        # OrderCancelled(tradeId, by)
        args = log.args
        meta = self._tx_meta(log)
        self._update_trade(
            args.tradeId,
            {
                "onchain_status": "cancelled",
                "cancel_tx": meta["tx_hash"],
                "cancel_block": meta["block_number"],
                "cancelled_at": _utcnow_iso(),
                "cancelled_by": str(args.by).lower(),
            },
        )
        self._refresh_ad_cache_for_trade(args.tradeId)

    def _on_order_expired(self, log: Any) -> None:
        # OrderExpired(tradeId)
        args = log.args
        meta = self._tx_meta(log)
        self._update_trade(
            args.tradeId,
            {
                "onchain_status": "expired",
                "expire_tx": meta["tx_hash"],
                "expire_block": meta["block_number"],
                "expired_at": _utcnow_iso(),
            },
        )
        self._refresh_ad_cache_for_trade(args.tradeId)

    def _on_marked_paid(self, log: Any) -> None:
        # MarkedPaid(tradeId)
        args = log.args
        meta = self._tx_meta(log)
        self._update_trade(
            args.tradeId,
            {
                "onchain_status": "awaiting_release",
                "mark_paid_tx": meta["tx_hash"],
                "mark_paid_block": meta["block_number"],
                "buyer_paid_at": _utcnow_iso(),
            },
        )

    def _on_released(self, log: Any) -> None:
        # Released(tradeId, buyer, amount)
        args = log.args
        meta = self._tx_meta(log)
        self._update_trade(
            args.tradeId,
            {
                "onchain_status": "completed",
                "release_tx": meta["tx_hash"],
                "release_block": meta["block_number"],
                "released_at": _utcnow_iso(),
                "released_to": str(args.buyer).lower(),
                "released_amount_gd": _from_wei(int(args.amount)),
            },
        )
        self._refresh_ad_cache_for_trade(args.tradeId)

    def _on_auto_released(self, log: Any) -> None:
        # AutoReleased(tradeId) — always co-emitted with Released, so we just
        # tag the row. The Released handler does the heavy lifting.
        args = log.args
        self._update_trade(
            args.tradeId,
            {"auto_released": True, "auto_released_at": _utcnow_iso()},
        )

    def _on_disputed(self, log: Any) -> None:
        # Disputed(tradeId, by)
        args = log.args
        meta = self._tx_meta(log)
        self._update_trade(
            args.tradeId,
            {
                "onchain_status": "disputed",
                "dispute_tx": meta["tx_hash"],
                "dispute_block": meta["block_number"],
                "disputed_at": _utcnow_iso(),
                "disputed_by": str(args.by).lower(),
            },
        )

    def _on_resolved(self, log: Any) -> None:
        # Resolved(tradeId, buyerWins, winner)
        args = log.args
        meta = self._tx_meta(log)
        buyer_wins = bool(args.buyerWins)
        self._update_trade(
            args.tradeId,
            {
                "onchain_status": "completed" if buyer_wins else "refunded",
                "dispute_resolve_tx": meta["tx_hash"],
                "dispute_resolve_block": meta["block_number"],
                "dispute_resolved_at": _utcnow_iso(),
                "dispute_buyer_wins": buyer_wins,
                "dispute_winner": str(args.winner).lower(),
            },
        )
        self._refresh_ad_cache_for_trade(args.tradeId)


# Lazy singleton ------------------------------------------------------------

# Threaded gunicorn means multiple workers can hit get_indexer() at once on
# first request; double-checked locking prevents two concurrent
# P2PEscrowIndexer instances (each spinning up their own polling thread).
_INDEXER: Optional[P2PEscrowIndexer] = None
_INDEXER_LOCK = threading.Lock()


def get_indexer() -> P2PEscrowIndexer:
    global _INDEXER
    if _INDEXER is None:
        with _INDEXER_LOCK:
            if _INDEXER is None:
                _INDEXER = P2PEscrowIndexer()
    return _INDEXER
