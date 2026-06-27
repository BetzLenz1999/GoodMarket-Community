-- Migration: Add missing columns to referrals table
-- Run this in Supabase SQL Editor to fix the referral disbursement bug

-- Add missing columns if they don't exist
ALTER TABLE referrals ADD COLUMN IF NOT EXISTS onchain_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE referrals ADD COLUMN IF NOT EXISTS admin_verified_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE referrals ADD COLUMN IF NOT EXISTS approved_by_wallet VARCHAR(42);
ALTER TABLE referrals ADD COLUMN IF NOT EXISTS approved_by_ip VARCHAR(45);

-- Verify the columns were added
SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'referrals' ORDER BY ordinal_position;
