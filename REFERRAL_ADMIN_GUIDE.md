# 📋 Referral Program Admin Guide

## Quick Start - Managing REFERRAL_KEY Disbursement

### 1️⃣ Check REFERRAL_KEY Status

**Endpoint:** `GET /api/admin/referral/key-balance`

```bash
curl -X GET "https://goodmarket.live/api/admin/referral/key-balance" \
  --cookie "session=YOUR_SESSION_COOKIE"
```

**Response:**
```json
{
  "success": true,
  "balance_g": 5000.5,
  "balance_wei": "5000500000000000000000",
  "wallet": "0xABCD1234...",
  "pending_disbursements_count": 3,
  "total_pending_amount_g": 1500.0,
  "can_process": true,
  "error": null
}
```

**What This Means:**
- `balance_g`: Current G$ in REFERRAL_KEY wallet
- `pending_disbursements_count`: Number of rewards waiting for balance
- `total_pending_amount_g`: Total G$ owed to users
- `can_process`: Whether we have enough balance to process all pending

---

### 2️⃣ Process Pending Disbursements

**When balance was insufficient, rewards are marked `'pending_disbursed'`.**  
**After topping up REFERRAL_KEY, run this to retry:**

**Endpoint:** `POST /api/admin/referral/process-pending`

```bash
curl -X POST "https://goodmarket.live/api/admin/referral/process-pending" \
  --cookie "session=YOUR_SESSION_COOKIE"
```

**Response:**
```json
{
  "success": true,
  "processed": 3,
  "failed": 0,
  "still_pending": 0,
  "message": "All pending rewards processed"
}
```

**What The Numbers Mean:**
- `processed`: Successfully disbursed
- `failed`: Failed (not due to balance)
- `still_pending`: Still waiting (usually due to insufficient balance)

---

### 3️⃣ Common Scenarios

#### Scenario A: Everything Works Fine
```
balance_g: 10000
pending_disbursements_count: 0
can_process: true
```
✅ **Action:** Nothing needed. System is healthy.

---

#### Scenario B: Pending Rewards (Low Balance)
```
balance_g: 200
pending_disbursements_count: 5
total_pending_amount_g: 7500
can_process: false
```
⚠️ **Action:** 
1. Top up REFERRAL_KEY with at least 7500 G$
2. Call `/api/admin/referral/process-pending`
3. Verify balance again

---

#### Scenario C: REFERRAL_KEY Not Configured
```
success: false
error: "REFERRAL_KEY not configured"
```
❌ **Action:**
1. Check that `REFERRAL_KEY` environment variable is set in Vercel
2. The key should be a valid private key (starting with `0x` or raw hex)
3. Restart the application
4. Try again

---

#### Scenario D: Insufficient Gas in REFERRAL_KEY Wallet
```
success: false
error: "The wallet has insufficient funds"
```
❌ **Action:**
1. Send some CELO to the REFERRAL_KEY wallet address
2. Minimum recommended: 0.5 CELO for gas
3. Retry balance check

---

## 🔧 Troubleshooting

### "Still pending after calling process-pending"

This means there's still insufficient balance. Check:

```bash
curl -X GET "https://goodmarket.live/api/admin/referral/key-balance" \
  --cookie "session=YOUR_SESSION_COOKIE"
```

If `can_process: false`, top up more G$ to the REFERRAL_KEY wallet.

---

### "Zero balance but should have G$"

Possible issues:

1. **Wrong network**: REFERRAL_KEY is on the wrong chain
   - Confirm it's on Celo mainnet
   - Check CELO_RPC_URL is correct

2. **Private key leaked**: If REFERRAL_KEY was exposed, rotate it immediately
   - Create new wallet
   - Update REFERRAL_KEY in Vercel
   - Restart application

3. **Transaction pending**: If you just sent G$, wait a few seconds
   - REFERRAL_KEY balance is checked on-chain in real-time
   - Celo has ~5 second block time

---

### "API returns 401"

You need admin authentication:

1. Log in to GoodMarket as an admin user
2. Copy your session cookie from browser DevTools
3. Pass it with `--cookie "session=YOUR_COOKIE"`

Or use cURL with authentication:
```bash
curl -X GET "https://goodmarket.live/api/admin/referral/key-balance" \
  -b "session=YOUR_SESSION_COOKIE"
```

---

### "Process-pending completed but didn't disburse all"

Check the response:
- If `still_pending > 0`: Balance insufficient, top up more
- If `failed > 0`: Some rewards failed (check logs)
- If `processed = 0` and `still_pending = 0`: No pending rewards to process

---

## 📊 Monitoring Dashboard

### Key Metrics to Watch

**1. Pending Disbursements Count**
```sql
SELECT COUNT(*) FROM referral_rewards_log WHERE status = 'pending_disbursed';
```
- Should be 0 in a healthy system
- Spike = balance issue

**2. Completed Disbursements**
```sql
SELECT COUNT(*) FROM referral_rewards_log WHERE status = 'completed';
```
- Should increase steadily when users verify

**3. REFERRAL_KEY Balance Over Time**
- Should stay above 1500 G$ (to handle peak load)
- Check daily using balance endpoint

**4. Failed Disbursements**
```sql
SELECT * FROM referral_rewards_log WHERE status = 'failed';
```
- Should be rare
- If you see failures, check logs for root cause

---

## 📈 Reporting & Analytics

### How Many Referrals Completed?
```sql
SELECT COUNT(*) FROM referrals WHERE status = 'completed';
```

### Total G$ Disbursed?
```sql
SELECT 
  SUM(reward_amount) as total,
  COUNT(*) as transaction_count
FROM referral_rewards_log 
WHERE status = 'completed';
```

### Top Referrer?
```sql
SELECT 
  wallet_address,
  SUM(reward_amount) as total_earned,
  COUNT(*) as disbursements
FROM referral_rewards_log 
WHERE reward_type = 'referrer' AND status = 'completed'
GROUP BY wallet_address
ORDER BY total_earned DESC
LIMIT 10;
```

---

## 🚨 Critical Events to Alert On

Set up monitoring for these conditions:

| Event | Threshold | Action |
|-------|-----------|--------|
| Pending Disbursements | > 5 | Check balance immediately |
| Failed Disbursements | > 0 | Check logs for root cause |
| REFERRAL_KEY Balance | < 1000 G$ | Top up before running low |
| Process-pending Failed | Any | Application may have crashed |

---

## 🔐 Security Best Practices

1. **Never Log REFERRAL_KEY**
   - Keep private key secure
   - Rotate regularly (monthly recommended)

2. **Monitor Access**
   - Only admins should call REFERRAL_KEY endpoints
   - Review admin access logs regularly

3. **Use Environment Secrets**
   - Store REFERRAL_KEY in Vercel Secrets, not code
   - Never commit to GitHub

4. **Balance Management**
   - Keep minimum 1500 G$ balance
   - Use separate cold storage for funds
   - Only fund REFERRAL_KEY wallet with what's needed

---

## 📞 Support & Debugging

### Enable Debug Logging

Add this to check detailed referral logs:
```bash
# View last 50 referral events
grep -i "referral\|disburse\|pending" /var/log/application.log | tail -50

# Check specific wallet referral history
curl "https://goodmarket.live/api/referral/check/WALLET_ADDRESS"
```

### Get Full Referral Stats for Admin
```bash
curl -X GET "https://goodmarket.live/api/admin/referral-stats" \
  --cookie "session=YOUR_SESSION_COOKIE" | jq
```

### Manual Database Inspection

Check referral table:
```sql
SELECT id, referral_code, referrer_wallet, referee_wallet, status, created_at 
FROM referrals 
WHERE status != 'completed' 
ORDER BY created_at DESC 
LIMIT 10;
```

Check rewards:
```sql
SELECT id, wallet_address, reward_amount, reward_type, status, tx_hash, created_at 
FROM referral_rewards_log 
WHERE status IN ('pending', 'pending_disbursed') 
ORDER BY created_at ASC;
```

---

## ✅ Maintenance Checklist

### Daily
- [ ] Check pending disbursements count (should be 0)
- [ ] Confirm REFERRAL_KEY balance is stable

### Weekly
- [ ] Review top referrers
- [ ] Check failed disbursements count
- [ ] Verify no orphaned rewards

### Monthly
- [ ] Rotate REFERRAL_KEY (create new wallet, update env var)
- [ ] Audit all completed disbursements
- [ ] Review spending trends

---

**Last Updated:** 2026-05-02  
**System Status:** ✅ Production Ready
