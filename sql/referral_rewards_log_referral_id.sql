-- Add an exact referral-row link to each reward log so retries can disburse
-- the referrer/referee legs for one referral without confusing reused codes.
-- Run in Supabase SQL Editor before deploying code that writes referral_id.

ALTER TABLE referral_rewards_log
ADD COLUMN IF NOT EXISTS referral_id INTEGER REFERENCES referrals(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_referral_rewards_referral_id
ON referral_rewards_log(referral_id);

-- Best-effort backfill for existing rows. Referee rewards can be linked exactly
-- because referrals.referee_wallet is unique. Referrer rewards can only be
-- linked when there is exactly one matching referral for that code+referrer.
UPDATE referral_rewards_log rrl
SET referral_id = r.id
FROM referrals r
WHERE rrl.referral_id IS NULL
  AND rrl.reward_type = 'referee'
  AND rrl.referral_code = r.referral_code
  AND LOWER(rrl.wallet_address) = LOWER(r.referee_wallet);

WITH unique_referrer_rewards AS (
    SELECT
        rrl.id AS reward_log_id,
        MIN(r.id) AS referral_id,
        COUNT(*) AS matches
    FROM referral_rewards_log rrl
    JOIN referrals r
      ON rrl.referral_code = r.referral_code
     AND LOWER(rrl.wallet_address) = LOWER(r.referrer_wallet)
    WHERE rrl.referral_id IS NULL
      AND rrl.reward_type = 'referrer'
    GROUP BY rrl.id
)
UPDATE referral_rewards_log rrl
SET referral_id = urr.referral_id
FROM unique_referrer_rewards urr
WHERE rrl.id = urr.reward_log_id
  AND urr.matches = 1;
