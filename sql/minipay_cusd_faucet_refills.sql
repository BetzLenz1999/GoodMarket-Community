-- Persist MiniPay cUSD faucet cooldowns so the 48-hour limit survives
-- application restarts and works consistently across multiple workers.
CREATE TABLE IF NOT EXISTS minipay_cusd_faucet_refills (
    id SERIAL PRIMARY KEY,
    wallet_address VARCHAR(42) UNIQUE NOT NULL,
    last_refill_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    tx_hash VARCHAR(66),
    amount_cusd NUMERIC(18,8) NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_minipay_cusd_faucet_refills_wallet
    ON minipay_cusd_faucet_refills(wallet_address);
CREATE INDEX IF NOT EXISTS idx_minipay_cusd_faucet_refills_last_refill
    ON minipay_cusd_faucet_refills(last_refill_at DESC);

ALTER TABLE minipay_cusd_faucet_refills ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow all operations on minipay_cusd_faucet_refills"
    ON minipay_cusd_faucet_refills FOR ALL USING (true);

DROP TRIGGER IF EXISTS update_minipay_cusd_faucet_refills_updated_at
    ON minipay_cusd_faucet_refills;
CREATE TRIGGER update_minipay_cusd_faucet_refills_updated_at
    BEFORE UPDATE ON minipay_cusd_faucet_refills
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
