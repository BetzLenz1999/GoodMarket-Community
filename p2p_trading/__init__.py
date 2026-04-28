"""
Trustless P2P escrow module.

Public surface (everything else is internal):

* ``p2p_bp``           — Flask blueprint with the API + HTML routes.
* ``init_p2p_trading`` — Helper that registers ``p2p_bp`` and (optionally)
                         starts the on-chain event indexer thread.
* ``escrow_service``   — Singleton orchestration object used by the routes
                         (and exposed for ad-hoc scripts).
* ``get_contract``     — Lazy accessor for the Web3 contract wrapper.
* ``get_indexer``      — Lazy accessor for the background event indexer.

The legacy custodial implementation that used ``MERCHANT_KEY`` to relay G$
transfers has been replaced by direct user-signed calls into
``GoodMarketP2PEscrow``. See ``contracts/P2P_ESCROW_README.md`` for the
contract architecture.
"""

from .contract import get_contract
from .escrow_service import escrow_service
from .indexer import get_indexer
from .routes import init_p2p_trading, p2p_bp

__all__ = [
    "p2p_bp",
    "init_p2p_trading",
    "escrow_service",
    "get_contract",
    "get_indexer",
]
