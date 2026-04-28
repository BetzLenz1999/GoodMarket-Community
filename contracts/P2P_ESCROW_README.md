# GoodMarketP2PEscrow

Trustless P2P escrow smart contract for trading G$ ↔ fiat off-platform on Celo.

## Overview

`GoodMarketP2PEscrow` is the on-chain settlement layer for GoodMarket's P2P trading
feature. It replaces the previous custodial database-driven escrow (where the
platform's merchant wallet held G$ on behalf of users) with a trustless,
non-custodial smart contract.

**Architecture: Hybrid pre-funded escrow.**

1. A seller "opens an ad" by depositing the full G$ amount they want to sell into
   the contract.
2. Buyers "place orders" against the ad, which locks a portion of the seller's
   deposit until the off-chain fiat payment is settled.
3. The seller approves and releases G$ to the buyer once they confirm fiat
   receipt — or opens a dispute if they did not.
4. Sellers can close their own ads anytime — provided no orders are currently
   active — and recover the unsold G$.

## Why a smart contract?

The previous implementation had several centralisation risks:

- A single merchant private key could drain all escrowed funds if compromised.
- Refund / release decisions depended on the platform staying online and honest.
- There was no on-chain proof of the trade lifecycle.

With the contract:

- Funds are held by the contract itself; **no admin can withdraw them**.
- All state transitions emit events (full on-chain audit trail).
- Users sign their own transactions — the platform cannot impersonate them.
- An admin (arbiter) is only involved when a dispute is explicitly opened.

## Trust model

| Role     | Power                                                                            |
|----------|----------------------------------------------------------------------------------|
| Seller   | Open / close own ad, approve trades, dispute trades, recover own dust.           |
| Buyer    | Place orders, cancel before paying, mark paid, dispute trades.                   |
| Arbiter  | Only resolve trades that are explicitly in the `Disputed` state.                  |
| Owner    | Pause / unpause the contract, change the arbiter, transfer ownership.             |
| Anyone   | `expirePendingOrder` after deadline; `autoReleaseAfterTimeout` after 48 h delay.  |

The contract is funded only by sellers' deposits. The owner cannot move funds
out of the contract; the arbiter can only resolve disputed trades to one of the
two legitimate parties.

## State machines

### Ad
```
                 ┌──────────────────────► Closed (seller calls closeAd)
                 │
   Open ─────────┼──────────────────────► Suspended (paused via owner)
                 │
                 └────► remaining < min ─► (still Open until seller closes; emits AdExhausted)
```

### Trade
```
   PaymentPending ──[markPaid]──► AwaitingRelease ──[release]──► Completed
                                                  │
                                                  ├─[disputeAsBuyer / disputeAsSeller]─► Disputed
                                                  │                                       │
                                                  │                                       ├─[arbiter: buyerWins]─► Completed
                                                  │                                       └─[arbiter: !buyerWins]─► Refunded
                                                  │
                                                  └─[48 h auto, no dispute]──────────────► Completed (AutoReleased)

   PaymentPending ──[buyer cancelOrder]──► Cancelled  → returns G$ to ad
   PaymentPending ──[deadline + expirePendingOrder]──► Expired → returns G$ to ad
```

## Key invariants

- `gDollar.balanceOf(contract)` ≥ Σ `ad.remainingAmount` + Σ `trade.amount` for
  every open trade. Tested by the suite.
- `ad.activeTradeCount > 0` ⇒ `closeAd` is impossible. Tested by the suite.
- Once `markPaid` has been called, `cancelOrder` is impossible. Tested by the
  suite. (This is the critical fix vs. the old DB escrow.)
- A `Disputed` trade cannot be `release`d, `autoReleaseAfterTimeout`d, or
  cancelled — only `resolveDispute` can move it to a final state.
- `release`, `cancelOrder`, `expirePendingOrder`, `autoReleaseAfterTimeout`,
  and `resolveDispute` all decrement `ad.activeTradeCount` exactly once.

## Configuration

| Constant            | Value         | Rationale                                                                  |
|---------------------|---------------|----------------------------------------------------------------------------|
| `MIN_AD_AMOUNT`     | 20 000 G$     | Per spec; filters out spammy listings; any minOrder must also be ≥ this.    |
| `MIN_PAYMENT_WINDOW`| 15 minutes    | Lower bound on how quickly a buyer must pay after placing the order.        |
| `MAX_PAYMENT_WINDOW`| 6 hours       | Upper bound; reduces capital lock-in risk for sellers.                      |
| `AUTO_RELEASE_DELAY`| 48 hours      | After buyer marks paid, anyone may force-release if seller is unresponsive. |

## Test coverage

`tests/test_p2p_escrow.py` runs an in-memory PyEVM chain and exercises every
state transition. Current status: **29 / 29 passing**.

The tests cover, among others:

- Happy path (open → place → markPaid → release).
- The two critical safety invariants:
  1. Seller cannot close an ad with active trades.
  2. Buyer cannot cancel an order after marking paid.
- Auto-release after 48 h timeout.
- Order expiry after deadline.
- Dispute resolution in both directions.
- Pause / unpause and access control.
- Multiple concurrent buyers against the same ad.
- Self-trade prevention.

Run them with:

```
python3 tests/test_p2p_escrow.py
```

## Off-chain responsibilities

The contract is intentionally minimal. The following live in the application
layer (Supabase + Flask backend):

- Fiat currency, payment method, payment instructions (e.g. GCash number).
- Payment proofs (multi-image upload to Supabase Storage).
- Buyer / seller chat, ratings, comments.
- Dispute reasons and the arbiter's investigation workflow (the contract only
  exposes `resolveDispute(tradeId, buyerWins)` once the arbiter has decided).

The backend listens to contract events (`AdOpened`, `OrderPlaced`,
`MarkedPaid`, `Released`, `Refunded`, `Disputed`, `Resolved`, etc.) and mirrors
them into the Supabase tables.

## Deployment

```
ADMIN_KEY=0x... python3 contracts/deploy_p2p_escrow.py
```

Requires:

- `ADMIN_KEY`: private key with at least 0.1 CELO. Becomes contract owner and
  default arbiter.
- `G_DOLLAR_TOKEN_ADDRESS`: defaults to mainnet G$
  (`0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A`).

For Alfajores testnet, override `CHAIN_ID=44787` and pass an Alfajores G$
address.

After deployment the script prints the contract address and writes a full
deployment artefact (including ABI) to `contracts/p2p_escrow_deployment.json`.

## Mainnet deployment

The contract is live on Celo mainnet at
[`0x2B9FA9b85BBB44b8FCBa550b6C9cA8792ce00f03`](https://celoscan.io/address/0x2B9FA9b85BBB44b8FCBa550b6C9cA8792ce00f03)
(deployed in tx
[`0x6c9fcc12...db1d7a`](https://celoscan.io/tx/0x6c9fcc123a7e0c818de48d62d672b89858f05b8f0a8eb4cca68f35a7f8db1d7a),
block 65,444,929).

This is the second deployment, replacing the original at
[`0x38Ba17dd...E9C85`](https://celoscan.io/address/0x38Ba17dd68C1A0B80C5E2e767e6053F8299E9C85).
The new bytecode includes the `placeOrder` deadline-check ordering fix (PR #259)
so that a past deadline reverts with the descriptive `"P2P: deadline in past"`
message instead of `Panic(0x11)`. The first deployment is no longer used by
the application; it has zero state and zero G$ escrowed.
