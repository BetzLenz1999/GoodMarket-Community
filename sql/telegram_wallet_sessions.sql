-- Telegram wallet-only login sessions for GoodMarket Learn & Earn.
-- Run this in Supabase before enabling the Telegram wallet capture flow.

CREATE TABLE IF NOT EXISTS telegram_wallet_sessions (
    id BIGSERIAL PRIMARY KEY,
    telegram_user_id TEXT UNIQUE NOT NULL,
    telegram_chat_id TEXT NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    wallet_address VARCHAR(42) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telegram_wallet_sessions_wallet
    ON telegram_wallet_sessions(wallet_address);

CREATE INDEX IF NOT EXISTS idx_telegram_wallet_sessions_last_seen
    ON telegram_wallet_sessions(last_seen_at DESC);
