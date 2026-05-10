-- Run this once in the Supabase SQL Editor before/with deploying the
-- 48-hour GoodDollar Celo gas faucet cooldown.
--
-- Background: every successful claim flow that needs gas first calls
-- /api/faucet/gas, which routes to the GoodDollar Celo faucet
-- (https://goodserver.gooddollar.org/verify/topWallet). That faucet sends
-- ~0.3 CELO per wallet, which is enough to cover roughly 3 days of
-- claims at typical Celo gas prices.
--
-- Without persistence, a user who already received the GoodDollar refill
-- could pull GoodMarket's TOPWALLET_KEY on-chain fallback within minutes
-- (the in-memory dedup window is only 30 minutes by default), draining
-- our top-wallet treasury. This table persists per-wallet GoodDollar
-- refill timestamps so the 48-hour cooldown survives application
-- restarts and works consistently across multiple workers.
--
-- The cooldown is enforced for both the GoodDollar API path and the
-- TOPWALLET_KEY (force_onchain) fallback. Users keep their 0.3 CELO
-- coverage; if they spend it sooner, they top up on their own or wait
-- out the cooldown.
CREATE TABLE IF NOT EXISTS celo_gas_faucet_refills (
    id SERIAL PRIMARY KEY,
    wallet_address VARCHAR(42) UNIQUE NOT NULL,
    last_refill_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    tx_hash VARCHAR(66),
    source VARCHAR(32) NOT NULL DEFAULT 'api',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_celo_gas_faucet_refills_wallet
    ON celo_gas_faucet_refills(wallet_address);
CREATE INDEX IF NOT EXISTS idx_celo_gas_faucet_refills_last_refill
    ON celo_gas_faucet_refills(last_refill_at DESC);

ALTER TABLE celo_gas_faucet_refills ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow all operations on celo_gas_faucet_refills"
    ON celo_gas_faucet_refills;
CREATE POLICY "Allow all operations on celo_gas_faucet_refills"
    ON celo_gas_faucet_refills FOR ALL USING (true);

-- Keep this standalone for SQL Editor use, even if the shared schema function
-- has not been created yet in this Supabase project.
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_celo_gas_faucet_refills_updated_at
    ON celo_gas_faucet_refills;
CREATE TRIGGER update_celo_gas_faucet_refills_updated_at
    BEFORE UPDATE ON celo_gas_faucet_refills
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
