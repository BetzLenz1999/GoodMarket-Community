-- Hotfix: ensure collaboration_submissions has payment metadata columns
-- Safe to run multiple times in Supabase SQL Editor.

BEGIN;

ALTER TABLE public.collaboration_submissions
  ADD COLUMN IF NOT EXISTS tx_hash text,
  ADD COLUMN IF NOT EXISTS paid_amount_gd numeric(20, 6),
  ADD COLUMN IF NOT EXISTS rejection_reason text,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();

-- Keep updated_at consistent for existing rows
UPDATE public.collaboration_submissions
SET updated_at = COALESCE(updated_at, created_at, now())
WHERE updated_at IS NULL;

-- If a row already has payment proof, normalize status from awaiting_payment/draft -> paid
UPDATE public.collaboration_submissions
SET status = 'paid',
    updated_at = now()
WHERE COALESCE(status, '') IN ('awaiting_payment', 'draft')
  AND (
    NULLIF(TRIM(COALESCE(tx_hash, '')), '') IS NOT NULL
    OR COALESCE(paid_amount_gd, 0) > 0
  );

-- Optional backfill from sponsorship_log using full OR masked wallet + timestamp.
-- Runs only when public.sponsorship_log exists.
DO $$
BEGIN
  IF to_regclass('public.sponsorship_log') IS NOT NULL THEN
    WITH candidates AS (
      SELECT
        cs.id,
        sl.tx_hash,
        sl.amount_gd,
        sl.created_at,
        ROW_NUMBER() OVER (
          PARTITION BY cs.id
          ORDER BY sl.created_at ASC
        ) AS rn
      FROM public.collaboration_submissions cs
      JOIN public.sponsorship_log sl
        ON (
             LOWER(sl.wallet_address) = LOWER(cs.wallet_address)
             OR LOWER(sl.wallet_address) = LOWER(
               CASE
                 WHEN LENGTH(COALESCE(cs.wallet_address, '')) > 10
                   THEN SUBSTRING(cs.wallet_address FROM 1 FOR 6) || '...' || RIGHT(cs.wallet_address, 4)
                 ELSE COALESCE(cs.wallet_address, '')
               END
             )
           )
       AND sl.created_at >= cs.created_at
      WHERE (cs.tx_hash IS NULL OR TRIM(cs.tx_hash) = '')
        AND COALESCE(cs.paid_amount_gd, 0) <= 0
        AND NULLIF(TRIM(COALESCE(sl.tx_hash, '')), '') IS NOT NULL
        AND COALESCE(sl.amount_gd, 0) > 0
    )
    UPDATE public.collaboration_submissions cs
    SET tx_hash = c.tx_hash,
        paid_amount_gd = c.amount_gd,
        status = CASE
          WHEN COALESCE(cs.status, '') IN ('awaiting_payment', 'draft') THEN 'paid'
          ELSE cs.status
        END,
        updated_at = now()
    FROM candidates c
    WHERE cs.id = c.id
      AND c.rn = 1;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_collab_submissions_status_created_at
  ON public.collaboration_submissions (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_collab_submissions_tx_hash
  ON public.collaboration_submissions (tx_hash)
  WHERE tx_hash IS NOT NULL;

COMMIT;
