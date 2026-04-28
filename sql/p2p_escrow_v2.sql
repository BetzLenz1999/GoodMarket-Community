-- Schema for the trustless GoodMarketP2PEscrow integration.
--
-- These tables back the user-pays-gas P2P trading flow:
--   * Sellers create an "ad" (sell offer) by calling openAd() on-chain.
--     The off-chain row in p2p_orders mirrors the on-chain Ad struct plus
--     the human-readable fields (payment method, fiat currency, etc.) that
--     stay off-chain.
--   * Buyers take part of an ad with placeOrder(). Each on-chain Trade
--     gets a row in p2p_trades with the off-chain payment-proof URLs.
--   * The indexer (p2p_trading/indexer.py) writes back to these tables as
--     events arrive on-chain.
--
-- Safe to run multiple times in Supabase SQL Editor.

BEGIN;

-- ──────────────────────────────────────────────────────────────────────
-- p2p_orders
-- ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.p2p_orders (
    id              bigserial PRIMARY KEY,
    order_id        text UNIQUE NOT NULL,
    seller_wallet   text NOT NULL,
    g_dollar_amount numeric(20, 6),
    fiat_amount     numeric(20, 6),
    fiat_currency   text,
    payment_method  text,
    payment_details text,
    rate            numeric(20, 6),
    description     text,
    status          text NOT NULL DEFAULT 'draft',
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Backfill base columns when the table already existed from the legacy schema.
-- (CREATE TABLE IF NOT EXISTS above is a no-op if the table is already there,
-- so we have to ADD COLUMN IF NOT EXISTS for any columns later code/indexes
-- depend on.)
ALTER TABLE public.p2p_orders
    ADD COLUMN IF NOT EXISTS order_id        text,
    ADD COLUMN IF NOT EXISTS seller_wallet   text,
    ADD COLUMN IF NOT EXISTS g_dollar_amount numeric(20, 6),
    ADD COLUMN IF NOT EXISTS fiat_amount     numeric(20, 6),
    ADD COLUMN IF NOT EXISTS fiat_currency   text,
    ADD COLUMN IF NOT EXISTS payment_method  text,
    ADD COLUMN IF NOT EXISTS payment_details text,
    ADD COLUMN IF NOT EXISTS rate            numeric(20, 6),
    ADD COLUMN IF NOT EXISTS description     text,
    ADD COLUMN IF NOT EXISTS status          text DEFAULT 'draft',
    ADD COLUMN IF NOT EXISTS created_at      timestamptz DEFAULT now();

ALTER TABLE public.p2p_orders
    ADD COLUMN IF NOT EXISTS ad_id_onchain          text,
    ADD COLUMN IF NOT EXISTS contract_address       text,
    ADD COLUMN IF NOT EXISTS chain_id               bigint,
    ADD COLUMN IF NOT EXISTS total_locked_gd        numeric(30, 8),
    ADD COLUMN IF NOT EXISTS remaining_amount_gd    numeric(30, 8),
    ADD COLUMN IF NOT EXISTS min_order_gd           numeric(30, 8),
    ADD COLUMN IF NOT EXISTS max_order_gd           numeric(30, 8),
    ADD COLUMN IF NOT EXISTS active_trade_count     int DEFAULT 0,
    ADD COLUMN IF NOT EXISTS onchain_status         text,
    ADD COLUMN IF NOT EXISTS ad_open_tx             text,
    ADD COLUMN IF NOT EXISTS ad_open_block          bigint,
    ADD COLUMN IF NOT EXISTS ad_close_tx            text,
    ADD COLUMN IF NOT EXISTS ad_close_block         bigint,
    ADD COLUMN IF NOT EXISTS refunded_amount_gd     numeric(30, 8),
    ADD COLUMN IF NOT EXISTS onchain_confirmed_at   timestamptz,
    ADD COLUMN IF NOT EXISTS closed_at              timestamptz,
    ADD COLUMN IF NOT EXISTS exhausted_at           timestamptz,
    ADD COLUMN IF NOT EXISTS price_gd_usd           numeric(20, 6),
    ADD COLUMN IF NOT EXISTS updated_at             timestamptz DEFAULT now();

-- Enforce uniqueness on order_id even on legacy tables where the column was
-- added via ALTER TABLE (which doesn't carry the original UNIQUE constraint).
CREATE UNIQUE INDEX IF NOT EXISTS p2p_orders_order_id_uq
    ON public.p2p_orders (order_id)
    WHERE order_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS p2p_orders_ad_id_onchain_uq
    ON public.p2p_orders (ad_id_onchain)
    WHERE ad_id_onchain IS NOT NULL;

CREATE INDEX IF NOT EXISTS p2p_orders_seller_wallet_idx
    ON public.p2p_orders (lower(seller_wallet));

CREATE INDEX IF NOT EXISTS p2p_orders_onchain_status_idx
    ON public.p2p_orders (onchain_status);

-- ──────────────────────────────────────────────────────────────────────
-- p2p_trades
-- ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.p2p_trades (
    id                 bigserial PRIMARY KEY,
    trade_id           text UNIQUE NOT NULL,
    order_id           text,
    buyer_wallet       text NOT NULL,
    seller_wallet      text NOT NULL,
    g_dollar_amount    numeric(20, 6),
    fiat_amount        numeric(20, 6),
    fiat_currency      text,
    payment_method     text,
    rate               numeric(20, 6),
    status             text NOT NULL DEFAULT 'draft',
    timeout_at         timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    payment_proof_url  text,
    payment_proof_uploaded_at timestamptz,
    buyer_paid_at      timestamptz
);

-- Backfill base columns when the table already existed from the legacy schema.
ALTER TABLE public.p2p_trades
    ADD COLUMN IF NOT EXISTS trade_id           text,
    ADD COLUMN IF NOT EXISTS order_id           text,
    ADD COLUMN IF NOT EXISTS buyer_wallet       text,
    ADD COLUMN IF NOT EXISTS seller_wallet      text,
    ADD COLUMN IF NOT EXISTS g_dollar_amount    numeric(20, 6),
    ADD COLUMN IF NOT EXISTS fiat_amount        numeric(20, 6),
    ADD COLUMN IF NOT EXISTS fiat_currency      text,
    ADD COLUMN IF NOT EXISTS payment_method     text,
    ADD COLUMN IF NOT EXISTS rate               numeric(20, 6),
    ADD COLUMN IF NOT EXISTS status             text DEFAULT 'draft',
    ADD COLUMN IF NOT EXISTS timeout_at         timestamptz,
    ADD COLUMN IF NOT EXISTS created_at         timestamptz DEFAULT now(),
    ADD COLUMN IF NOT EXISTS payment_proof_url  text,
    ADD COLUMN IF NOT EXISTS payment_proof_uploaded_at timestamptz,
    ADD COLUMN IF NOT EXISTS buyer_paid_at      timestamptz;

ALTER TABLE public.p2p_trades
    ADD COLUMN IF NOT EXISTS trade_id_onchain         text,
    ADD COLUMN IF NOT EXISTS ad_id_onchain            text,
    ADD COLUMN IF NOT EXISTS contract_address         text,
    ADD COLUMN IF NOT EXISTS chain_id                 bigint,
    ADD COLUMN IF NOT EXISTS payment_deadline         bigint,  -- epoch seconds
    ADD COLUMN IF NOT EXISTS onchain_status           text,
    ADD COLUMN IF NOT EXISTS onchain_confirmed_at     timestamptz,
    ADD COLUMN IF NOT EXISTS place_order_tx           text,
    ADD COLUMN IF NOT EXISTS place_order_block        bigint,
    ADD COLUMN IF NOT EXISTS cancel_tx                text,
    ADD COLUMN IF NOT EXISTS cancel_block             bigint,
    ADD COLUMN IF NOT EXISTS cancelled_at             timestamptz,
    ADD COLUMN IF NOT EXISTS cancelled_by             text,
    ADD COLUMN IF NOT EXISTS expire_tx                text,
    ADD COLUMN IF NOT EXISTS expire_block             bigint,
    ADD COLUMN IF NOT EXISTS expired_at               timestamptz,
    ADD COLUMN IF NOT EXISTS mark_paid_tx             text,
    ADD COLUMN IF NOT EXISTS mark_paid_block          bigint,
    ADD COLUMN IF NOT EXISTS release_tx               text,
    ADD COLUMN IF NOT EXISTS release_block            bigint,
    ADD COLUMN IF NOT EXISTS released_at              timestamptz,
    ADD COLUMN IF NOT EXISTS released_to              text,
    ADD COLUMN IF NOT EXISTS released_amount_gd       numeric(30, 8),
    ADD COLUMN IF NOT EXISTS auto_released            boolean DEFAULT false,
    ADD COLUMN IF NOT EXISTS auto_released_at         timestamptz,
    ADD COLUMN IF NOT EXISTS dispute_tx               text,
    ADD COLUMN IF NOT EXISTS dispute_block            bigint,
    ADD COLUMN IF NOT EXISTS disputed_at              timestamptz,
    ADD COLUMN IF NOT EXISTS disputed_by              text,
    ADD COLUMN IF NOT EXISTS dispute_resolve_tx       text,
    ADD COLUMN IF NOT EXISTS dispute_resolve_block    bigint,
    ADD COLUMN IF NOT EXISTS dispute_resolved_at      timestamptz,
    ADD COLUMN IF NOT EXISTS dispute_buyer_wins       boolean,
    ADD COLUMN IF NOT EXISTS dispute_winner           text,
    ADD COLUMN IF NOT EXISTS updated_at               timestamptz DEFAULT now();

-- Enforce uniqueness on trade_id even on legacy tables where the column was
-- added via ALTER TABLE (which doesn't carry the original UNIQUE constraint).
CREATE UNIQUE INDEX IF NOT EXISTS p2p_trades_trade_id_uq
    ON public.p2p_trades (trade_id)
    WHERE trade_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS p2p_trades_trade_id_onchain_uq
    ON public.p2p_trades (trade_id_onchain)
    WHERE trade_id_onchain IS NOT NULL;

CREATE INDEX IF NOT EXISTS p2p_trades_ad_id_onchain_idx
    ON public.p2p_trades (ad_id_onchain);

CREATE INDEX IF NOT EXISTS p2p_trades_buyer_wallet_idx
    ON public.p2p_trades (lower(buyer_wallet));

CREATE INDEX IF NOT EXISTS p2p_trades_seller_wallet_idx
    ON public.p2p_trades (lower(seller_wallet));

CREATE INDEX IF NOT EXISTS p2p_trades_onchain_status_idx
    ON public.p2p_trades (onchain_status);

-- ──────────────────────────────────────────────────────────────────────
-- p2p_escrow_logs (events / audit trail)
-- ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.p2p_escrow_logs (
    id           bigserial PRIMARY KEY,
    trade_id     text,
    order_id     text,
    actor        text,
    action       text NOT NULL,
    tx_hash      text,
    block_number bigint,
    amount_gd    numeric(30, 8),
    notes        text,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Backfill columns when the legacy p2p_escrow_logs table already exists.
-- The old schema only had (trade_id, action, g_dollar_amount, transaction_hash,
-- timestamp), so order_id / actor / tx_hash / amount_gd / notes / block_number
-- need to be added before the indexes and inserts below can succeed.
ALTER TABLE public.p2p_escrow_logs
    ADD COLUMN IF NOT EXISTS trade_id     text,
    ADD COLUMN IF NOT EXISTS order_id     text,
    ADD COLUMN IF NOT EXISTS actor        text,
    ADD COLUMN IF NOT EXISTS action       text,
    ADD COLUMN IF NOT EXISTS tx_hash      text,
    ADD COLUMN IF NOT EXISTS block_number bigint,
    ADD COLUMN IF NOT EXISTS amount_gd    numeric(30, 8),
    ADD COLUMN IF NOT EXISTS notes        text,
    ADD COLUMN IF NOT EXISTS created_at   timestamptz DEFAULT now();

CREATE INDEX IF NOT EXISTS p2p_escrow_logs_trade_id_idx
    ON public.p2p_escrow_logs (trade_id);

CREATE INDEX IF NOT EXISTS p2p_escrow_logs_order_id_idx
    ON public.p2p_escrow_logs (order_id);

-- ──────────────────────────────────────────────────────────────────────
-- p2p_indexer_state — last block scanned per contract address
-- ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.p2p_indexer_state (
    contract_address text PRIMARY KEY,
    last_block       bigint NOT NULL,
    updated_at       timestamptz NOT NULL DEFAULT now()
);

-- ──────────────────────────────────────────────────────────────────────
-- p2p_ratings (kept for back-compat with the legacy module — unchanged shape)
-- ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.p2p_ratings (
    id            bigserial PRIMARY KEY,
    rated_wallet  text NOT NULL,
    rater_wallet  text NOT NULL,
    trade_id      text,
    rating        smallint CHECK (rating BETWEEN 1 AND 5),
    comment       text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS p2p_ratings_rated_wallet_idx
    ON public.p2p_ratings (lower(rated_wallet));

-- ──────────────────────────────────────────────────────────────────────
-- updated_at trigger fn (idempotent)
-- ──────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public._p2p_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS p2p_orders_set_updated_at ON public.p2p_orders;
CREATE TRIGGER p2p_orders_set_updated_at
    BEFORE UPDATE ON public.p2p_orders
    FOR EACH ROW EXECUTE FUNCTION public._p2p_set_updated_at();

DROP TRIGGER IF EXISTS p2p_trades_set_updated_at ON public.p2p_trades;
CREATE TRIGGER p2p_trades_set_updated_at
    BEFORE UPDATE ON public.p2p_trades
    FOR EACH ROW EXECUTE FUNCTION public._p2p_set_updated_at();

COMMIT;
