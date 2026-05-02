# 📱 Referral Program - Quick Reference Card

## The Problem (Fixed ✅)

The referral program had a **broken retry loop**:
- When REFERRAL_KEY balance was low, rewards marked as `'pending_disbursed'`
- But retry logic only looked for `'pending'` status
- Result: **Rewards never disbursed when balance was topped up**

---

## The Solution (Implemented ✅)

### 3 Code Changes:
1. **main.py** - Proper status differentiation (pending vs pending_disbursed vs failed)
2. **referral_service.py** - Retry loop now handles both 'pending' AND 'pending_disbursed'
3. **routes.py** - New admin endpoint to check REFERRAL_KEY balance

### 3 Monitoring Tools:
1. `/api/admin/referral/key-balance` - Check balance & pending queue
2. `/api/admin/referral/process-pending` - Retry all pending disbursements
3. `get_pending_disbursement_summary()` - See exactly which rewards are waiting

---

## Quick Commands

### Check Status
```bash
curl -X GET "https://goodmarket.live/api/admin/referral/key-balance" \
  --cookie "session=YOUR_COOKIE" | jq
```

### Process Pending
```bash
curl -X POST "https://goodmarket.live/api/admin/referral/process-pending" \
  --cookie "session=YOUR_COOKIE" | jq
```

### Check Specific Referral
```bash
curl "https://goodmarket.live/api/referral/check/ABC12345"
```

---

## Status Values Explained

| Status | Meaning | Next Step |
|--------|---------|-----------|
| `pending_face_verification` | Waiting for user to verify face | User completes face verification |
| `pending_disbursed` | ⚠️ Low balance, waiting for top-up | Top up REFERRAL_KEY, call process-pending |
| `disbursing` | Currently processing | Wait for completion |
| `completed` | ✅ Rewards sent successfully | Done! |
| `failed` | ❌ Failed (unrecoverable) | Manual review needed |

---

## Admin Checklist

### Daily (2 minutes)
- [ ] Check balance: `curl ...key-balance... | jq`
- [ ] Is `can_process: true`? ✅ Good
- [ ] Is `pending_disbursements_count: 0`? ✅ Good

### If Pending Count > 0
- [ ] Check if `can_process: false`
- [ ] If yes: Top up REFERRAL_KEY wallet
- [ ] Call process-pending
- [ ] Check balance again

### Monthly
- [ ] Review total G$ disbursed
- [ ] Check top referrers
- [ ] Rotate REFERRAL_KEY (security)

---

## Database Queries

### See Pending Rewards
```sql
SELECT wallet_address, reward_amount, reward_type, status 
FROM referral_rewards_log 
WHERE status = 'pending_disbursed'
ORDER BY created_at ASC;
```

### Count by Status
```sql
SELECT status, COUNT(*) 
FROM referral_rewards_log 
GROUP BY status;
```

### Total Disbursed
```sql
SELECT SUM(reward_amount) as total 
FROM referral_rewards_log 
WHERE status = 'completed';
```

---

## Common Issues & Fixes

| Issue | Check | Fix |
|-------|-------|-----|
| `pending_disbursements_count` not 0 | Balance sufficient? | Top up REFERRAL_KEY |
| API returns 401 | Admin logged in? | Need admin session cookie |
| API returns "REFERRAL_KEY not configured" | Env var set? | Add REFERRAL_KEY to Vercel |
| Rewards show as 'failed' | Check logs | Investigate error in logs |

---

## Environment Setup

### Required Environment Variables

```
REFERRAL_KEY = 0x... (private key)
CELO_RPC_URL = https://forno.celo.org
CHAIN_ID = 42220
GOODDOLLAR_TOKEN_CONTRACT = 0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A
```

### Verify Setup
```bash
# Check if env var is set (should not show empty)
curl -X GET "https://goodmarket.live/api/admin/referral/key-balance" \
  --cookie "session=..." 
# Should NOT return error "REFERRAL_KEY not configured"
```

---

## Monitoring Thresholds

```
✅ Healthy:
   - pending_disbursements_count = 0
   - balance > 1500 G$
   - can_process = true

⚠️ Warning:
   - pending_disbursements_count > 3
   - balance < 1000 G$
   - Process pending returns still_pending > 0

🚨 Critical:
   - pending_disbursements_count > 10
   - balance < 500 G$
   - process-pending returns failed > 0
```

---

## What Changed in Code

### File 1: main.py
```python
# BEFORE: All failures → 'pending'
status = 'completed' if success else 'pending'

# AFTER: Proper differentiation
status = 'completed' if success else (
    'pending_disbursed' if pending_flag else 'failed'
)
```

### File 2: referral_service.py
```python
# BEFORE: Only 'pending'
.eq('status', 'pending')

# AFTER: Both 'pending' and 'pending_disbursed'
.in_('status', ['pending', 'pending_disbursed'])
```

### File 3: routes.py
```python
# NEW: Added endpoint to check REFERRAL_KEY
@routes.route("/api/admin/referral/key-balance", methods=["GET"])
```

---

## Testing Flow

### Test 1: Normal Operation (Balance Sufficient)
1. Top up REFERRAL_KEY with 2000+ G$
2. New user joins with referral code
3. User completes face verification
4. ✅ Should see rewards 'completed' in DB immediately

### Test 2: Insufficient Balance
1. Empty REFERRAL_KEY (send G$ elsewhere)
2. New user joins with referral code
3. User completes face verification
4. ✅ Should see rewards 'pending_disbursed' in DB
5. Top up REFERRAL_KEY with 1500+ G$
6. Call `/api/admin/referral/process-pending`
7. ✅ Should see rewards 'completed' in DB

### Test 3: Admin Visibility
1. Call `/api/admin/referral/key-balance`
2. ✅ Should return balance, pending count, total amount

---

## Documentation Files

| File | Purpose | Read When |
|------|---------|-----------|
| REFERRAL_PROGRAM_AUDIT.md | Complete audit of issues | Understanding what was fixed |
| REFERRAL_ADMIN_GUIDE.md | Admin operations guide | Managing the system |
| REFERRAL_FIXES_SUMMARY.md | Code changes summary | Deploying changes |
| REFERRAL_FLOW_DIAGRAM.md | Visual flow diagrams | Understanding the flow |
| REFERRAL_QUICK_REFERENCE.md | This file | Quick lookup |

---

## Key Takeaway

**Before Fix:**
```
Low balance → pending_disbursed (orphaned)
Admin tops up → Retry looks for 'pending' only
❌ STUCK FOREVER
```

**After Fix:**
```
Low balance → pending_disbursed (tracked)
Admin tops up → Retry looks for 'pending_disbursed' too
✅ AUTOMATICALLY RETRIES
```

---

## Support

**Can't disburse?**
1. Check `/api/admin/referral/key-balance`
2. Read REFERRAL_ADMIN_GUIDE.md troubleshooting section
3. Check logs: `grep -i referral /var/log/app.log`

**Need details?**
Read REFERRAL_PROGRAM_AUDIT.md

**Need to understand flow?**
Read REFERRAL_FLOW_DIAGRAM.md

**Need to deploy?**
Follow REFERRAL_FIXES_SUMMARY.md checklist

---

**System Status:** ✅ Fixed and Production Ready  
**Last Updated:** 2026-05-02  
**Tested:** Yes
