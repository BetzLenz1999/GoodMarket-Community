-- p2p_trade_chat: 1:N messages per trade between buyer / seller / arbiter.
--
-- This table is auth-gated at the API layer (see p2p_trading/routes.py) — only
-- the buyer, seller, or an arbiter of the referenced trade can read or write.
-- Messages are stored as plaintext; if you need privacy from the platform
-- itself, switch to client-side end-to-end encryption (separate work).
--
-- Run this once in the Supabase SQL editor before deploying the chat feature.
--
-- Note: the project already has a legacy ``p2p_chat_messages`` table with a
-- different (sender/receiver-style) shape that was never wired up to the UI;
-- this new feature uses ``p2p_trade_chat`` to avoid colliding with it. The
-- legacy table can be dropped once you've confirmed nothing else depends on
-- it.

CREATE TABLE IF NOT EXISTS public.p2p_trade_chat (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_id        text NOT NULL,
    sender_wallet   text NOT NULL,
    sender_role     text NOT NULL
        CHECK (sender_role IN ('buyer', 'seller', 'arbiter')),
    body            text,
    attachment_bucket text,
    attachment_path text,
    attachment_mime text,
    attachment_size bigint,
    created_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz,
    CONSTRAINT p2p_trade_chat_body_or_attachment CHECK (
        (body IS NOT NULL AND length(trim(body)) > 0)
        OR attachment_path IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS p2p_trade_chat_trade_id_idx
    ON public.p2p_trade_chat (trade_id, created_at)
    WHERE deleted_at IS NULL;

-- Wallets are always lowercased before insert in chat_service.send(), and
-- queried with PostgREST's plain ``.eq("sender_wallet", value.lower())``,
-- so a plain B-tree index is what the planner can actually use here.
CREATE INDEX IF NOT EXISTS p2p_trade_chat_sender_idx
    ON public.p2p_trade_chat (sender_wallet);
