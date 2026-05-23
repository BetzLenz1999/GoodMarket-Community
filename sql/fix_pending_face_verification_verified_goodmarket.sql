-- Fix stuck referrals: pending_face_verification -> completed
-- Use in Supabase SQL Editor when users are already verified via GoodMarket.
--
-- What it does:
-- 1) Marks referrals as completed if referee_wallet is already verified in user_data
--    (verified_after_goodmarket = true OR face_verified = true).
-- 2) Sets completed_at for affected referrals.
-- 3) Returns the rows that were updated for audit.

begin;

with candidates as (
    select r.id
    from referrals r
    join user_data u
      on lower(u.wallet_address) = lower(r.referee_wallet)
    where r.status = 'pending_face_verification'
      and (
        coalesce(u.verified_after_goodmarket, false) = true
        or coalesce(u.face_verified, false) = true
      )
), updated as (
    update referrals r
       set status = 'completed',
           completed_at = coalesce(r.completed_at, now()),
           error_message = null
      where r.id in (select id from candidates)
    returning r.id, r.referral_code, r.referee_wallet, r.status, r.completed_at
)
select * from updated order by completed_at desc;

commit;
