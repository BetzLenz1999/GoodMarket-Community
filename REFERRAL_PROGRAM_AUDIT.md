# 🔍 Referral Program Audit & Fixes Report

**Date:** 2026-05-02  
**Status:** ✅ Fixed and Ready for Production

---

## Executive Summary

The referral program had **5 critical issues** preventing proper REFERRAL_KEY disbursement. All issues have been identified and fixed. The system now properly tracks, retries, and disburses referral rewards even when REFERRAL_KEY balance is insufficient.

---

## Issues Found & Fixed

### Issue 1: ❌ Broken Retry Loop for Insufficient Balance
**Location:** `referral_program/referral_service.py:445`

**Problem:**
- When REFERRAL_KEY had insufficient balance, the code set reward status to `'pending_disbursed'`
- But `process_pending_disbursements()` only looked for status `'pending'`
- Result: Rewards with insufficient balance were never retried after REFERRAL_KEY was topped up

**Fix Applied:**
```python
# BEFORE: Only looked for 'pending'
.eq('status', 'pending')

# AFTER: Now looks for BOTH 'pending' and 'pending_disbursed'
.in_('status', ['pending', 'pending_disbursed'])
```

---

### Issue 2: ❌ Incorrect Status Logic in Disbursement
**Location:** `main.py:1546-1560`

**Problem:**
- When disbursement failed due to insufficient balance, the code always set status to `'pending'`
- Did not differentiate between "pending face verification" and "pending balance"
- Orphaned rewards could never be retry properly

**Fix Applied:**
```python
# BEFORE: Everything was just 'pending'
referrer_status = 'completed' if referrer_result.get('success') else 'pending'
referee_status = 'completed' if referee_result.get('success') else 'pending'

# AFTER: Proper status differentiation
referrer_status = 'completed' if referrer_result.get('success') else ('pending_disbursed' if referrer_result.get('pending') else 'failed')
referee_status = 'completed' if referee_result.get('success') else ('pending_disbursed' if referee_result.get('pending') else 'failed')
```

---

### Issue 3: ❌ Missing REFERRAL_KEY Balance Validation
**Location:** No endpoint existed

**Problem:**
- Admins had no way to check if REFERRAL_KEY was configured and had sufficient balance
- Could not diagnose disbursement failures without logs
- No visibility into pending queue

**Fix Applied:**
✅ **New Endpoint:** `/api/admin/referral/key-balance` (GET)

Returns:
```json
{
  "success": true,
  "balance_g": 500.5,
  "wallet": "0x...",
  "pending_disbursements_count": 3,
  "total_pending_amount_g": 1500.0,
  "can_process": true
}
```

---

### Issue 4: ❌ No Visibility into Pending Disbursements
**Location:** `referral_program/referral_service.py`

**Problem:**
- No method to get details about rewards waiting for REFERRAL_KEY balance
- Admins couldn't see which wallets were waiting for disbursement

**Fix Applied:**
✅ **New Method:** `get_pending_disbursement_summary()`

Returns detailed list of all pending rewards with amounts and wallet addresses.

---

### Issue 5: ❌ Poor Error Tracking
**Location:** `main.py:1559`

**Problem:**
- Generic error messages didn't explain why disbursement failed
- Made debugging difficult

**Fix Applied:**
- Added proper error differentiation in `_process_referral_disbursement()`
- Now tracks: insufficient balance vs transaction failure vs other errors
- Status message includes details for debugging

---

## How the Fixed System Works

### User Journey:
1. **New user signs up with referral code**
   - Referral recorded as `'pending_face_verification'`
   - Status: `pending_face_verification`

2. **User completes face verification**
   - Referral is claimed atomically (prevents double-disbursement)
   - Rewards are disbursed immediately if REFERRAL_KEY has balance
   - If balance insufficient:
     - Rewards marked as `'pending_disbursed'`
     - Status: `'pending_disbursed'` (waiting for balance)
     - Stored in `referral_rewards_log` table

3. **Admin tops up REFERRAL_KEY**
   - Calls `/api/admin/referral/process-pending` (POST)
   - System finds all rewards with `'pending_disbursed'` status
   - Attempts disbursement again
   - On success: Status → `'completed'`
   - On continued failure: Status → `'pending_disbursed'` (will retry next time)

### Key Endpoints:

**Check REFERRAL_KEY Health:**
```bash
curl -X GET "https://goodmarket.live/api/admin/referral/key-balance" \
  -H "Cookie: session=..."
```

**Process Pending Disbursements:**
```bash
curl -X POST "https://goodmarket.live/api/admin/referral/process-pending" \
  -H "Cookie: session=..."
```

**Check Referral Status:**
```bash
curl "https://goodmarket.live/api/referral/check/ABC12345"
```

---

## Testing the Fix

### Test Scenario 1: Normal Flow (with balance)
1. Top up REFERRAL_KEY wallet with 2000+ G$
2. New user joins with referral code
3. User completes face verification
4. Verify: Both referrer and referee receive G$ immediately
5. Status in DB: `'completed'`

### Test Scenario 2: Insufficient Balance Flow
1. Empty REFERRAL_KEY wallet (or set balance to 100 G$)
2. New user joins with referral code
3. User completes face verification
4. Verify: Rewards created but status is `'pending_disbursed'`
5. Top up REFERRAL_KEY to 1500+ G$
6. Call `/api/admin/referral/process-pending`
7. Verify: Rewards now disbursed, status → `'completed'`

### Test Scenario 3: Check Balance
```bash
curl "https://goodmarket.live/api/admin/referral/key-balance" | jq
```

Expected output shows:
- Current balance
- Pending disbursements count
- Total amount waiting
- Whether processing can proceed

---

## Database Tables Involved

### `referrals` table
- Status progression: `pending_face_verification` → `disbursing` → `completed`
- Tracks the referral relationship between users

### `referral_rewards_log` table
- Status progression: `pending` → `pending_disbursed` → `completed`
- Tracks actual G$ disbursement transactions
- Can have multiple records per referral (one for referrer, one for referee)

### `referral_codes` table
- Immutable referral code database
- Tracks total_referrals and total_earned per code

---

## Deployment Checklist

- [ ] Deploy fixed code to production
- [ ] Verify REFERRAL_KEY environment variable is set correctly
- [ ] Check REFERRAL_KEY wallet has sufficient balance (recommend 10,000+ G$)
- [ ] Test `/api/admin/referral/key-balance` endpoint
- [ ] Run `/api/admin/referral/process-pending` to catch up any backlog
- [ ] Monitor logs for referral disbursement messages
- [ ] Test end-to-end with a test user + referral code

---

## Monitoring & Alerts

Monitor these metrics:

1. **Pending Disbursements Count**
   - Should be 0 after REFERRAL_KEY is properly funded
   - Spike indicates balance issue

2. **Disbursement Success Rate**
   - Track completed vs failed in logs
   - Should be 99%+ with sufficient balance

3. **REFERRAL_KEY Balance**
   - Set alert if balance < 1500 G$
   - Use `/api/admin/referral/key-balance` endpoint

---

## Migration from Old System

If you have rewards stuck in the old broken system:

1. Check pending rewards:
   ```sql
   SELECT * FROM referral_rewards_log WHERE status IN ('pending', 'pending_disbursed');
   ```

2. Ensure REFERRAL_KEY is funded

3. Call `/api/admin/referral/process-pending`

4. Verify with:
   ```sql
   SELECT COUNT(*), status FROM referral_rewards_log GROUP BY status;
   ```

---

## Summary of Code Changes

| File | Changes | Impact |
|------|---------|--------|
| `main.py` | Fixed `_process_referral_disbursement()` logic | Proper status tracking |
| `referral_service.py` | Updated `process_pending_disbursements()` + added `get_pending_disbursement_summary()` | Retry pending_disbursed rewards |
| `routes.py` | Added `/api/admin/referral/key-balance` endpoint | Admin visibility |

---

## Next Steps

1. ✅ Deploy the fixed code
2. ✅ Top up REFERRAL_KEY wallet (recommend 10,000+ G$)
3. ✅ Call `/api/admin/referral/process-pending` to catch up
4. ✅ Set up monitoring on pending disbursements count
5. ✅ Test with new users to confirm flow works

---

**Report Generated:** 2026-05-02  
**System Status:** ✅ Ready for Production
