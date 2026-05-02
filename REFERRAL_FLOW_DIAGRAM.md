# 🔄 Referral Program Flow Diagram

## User Referral Journey

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        NEW USER JOINS WITH REFERRAL CODE                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  /verify-identity endpoint    │
                    │  - Wallet address             │
                    │  - Referral code (optional)   │
                    └───────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │ Has referral_code?            │
                    └───────────────┬───────────────┘
                         │          │
                    ┌────▼──┐   ┌───▼────┐
                    │  Yes  │   │  No    │
                    └────┬──┘   └───┬────┘
                         │          │
                    ┌────▼────────────▼──────┐
                    │ Validate code exists   │
                    │ Check code is valid    │
                    └────┬───────────────────┘
                         │
            ┌────────────┬┴────────────┐
            │            │             │
        ┌───▼────┐   ┌───▼────┐   ┌──▼───┐
        │ Valid  │   │Invalid │   │ None │
        └───┬────┘   └───┬────┘   └──┬───┘
            │            │            │
        ┌───▼──────────────────────────▼───┐
        │  Is user NEW + UNVERIFIED?       │
        │  (first_seen_unverified = NULL)  │
        └───┬──────────────────────────────┘
            │
        ┌───┴────────────────┐
        │                    │
    ┌───▼──┐            ┌───▼──┐
    │ Yes  │            │  No  │
    └───┬──┘            └──┬───┘
        │                   │
    ┌───▼──────────────┐   │
    │ Record Referral: │   │
    │ status =         │   │
    │ pending_face_    │   │
    │ verification     │   │
    └───┬──────────────┘   │
        │                   │
        │ ┌─────────────────┘
        │ │
        │ ▼
    ┌───────────────────────────┐
    │  User completes face      │
    │  verification on GoodDollar│
    └───┬───────────────────────┘
        │
        ▼
    ┌────────────────────────────────────┐
    │  /fv-callback or verify-identity   │
    │  triggers referral disbursement    │
    └───┬─────────────────────────────────┘
        │
        ▼
    ┌──────────────────────────────────────┐
    │ claim_pending_referral_for_          │
    │ disbursement (atomic lock)           │
    │ - Prevents double-disbursement       │
    └───┬───────────────────────────────────┘
        │
        ▼
    ┌───────────────────────────────────────┐
    │ _process_referral_disbursement()      │
    │ - Disburse referrer (1000 G$)         │
    │ - Disburse referee (500 G$)           │
    └───┬───────────────────────────────────┘
        │
        ▼
    ┌────────────────────────────┐
    │ Check REFERRAL_KEY balance │
    └───┬─────────────────────────┘
        │
    ┌───┴──────────────────────────┐
    │                              │
┌──▼──────┐              ┌────────▼──┐
│Sufficient│              │Insufficient│
│Balance   │              │Balance    │
└──┬──────┘              └────────┬──┘
   │                             │
   ▼                             ▼
┌─────────────────┐    ┌──────────────────────────┐
│ Send G$ on-chain│    │ Log reward as            │
│ referrer + fee  │    │ 'pending_disbursed'     │
│                 │    │ (waiting for balance)   │
│ Set status =    │    │                         │
│ 'completed'     │    │ Set status =            │
└────┬────────────┘    │ 'pending_disbursed'    │
     │                 └──────┬──────────────────┘
     │                        │
     ▼                        ▼
┌──────────────────────────────────┐
│ Referral Complete!               │
│ User sees rewards               │
│ Referrer sees stats updated     │
└──────────────────────────────────┘
```

---

## Admin Retry Flow

```
┌──────────────────────────────────────┐
│ REFERRAL_KEY balance is low          │
│ Pending disbursements exist          │
└──────────────────┬───────────────────┘
                   │
                   ▼
          ┌────────────────────┐
          │ Admin tops up      │
          │ REFERRAL_KEY wallet│
          │ with more G$       │
          └────────┬───────────┘
                   │
                   ▼
          ┌────────────────────┐
          │ Admin calls        │
          │ /api/admin/referral│
          │ /process-pending   │
          │ (POST)            │
          └────────┬───────────┘
                   │
                   ▼
        ┌──────────────────────────┐
        │ process_pending_          │
        │ disbursements()           │
        │                           │
        │ Fetch rewards with:       │
        │ status IN                 │
        │ ('pending',              │
        │ 'pending_disbursed')     │
        └────────┬─────────────────┘
                 │
        ┌────────▼─────────────┐
        │ For each reward:      │
        │ Try to disburse       │
        └────────┬─────────────┘
                 │
        ┌────────┴────────────────┐
        │                         │
    ┌───▼──────┐            ┌────▼────┐
    │Success   │            │Pending  │
    │(send G$) │            │(balance)│
    └───┬──────┘            └────┬────┘
        │                        │
    ┌───▼────────────────────────▼──┐
    │ Update reward status to        │
    │ 'completed'                    │
    │ (or keep as 'pending_disbursed'│
    │  if still insufficient)        │
    └───┬─────────────────────────────┘
        │
        ▼
    ┌──────────────────────────────────┐
    │ Return summary:                  │
    │ - processed: 5                   │
    │ - failed: 0                      │
    │ - still_pending: 0               │
    └──────────────────────────────────┘
```

---

## Database Status Tracking

### Referrals Table (User Journey)

```
┌──────────────────────────────────────────────────┐
│ referrals table                                  │
├──────────────────────────────────────────────────┤
│ Status Flow:                                     │
│                                                  │
│ [1] pending_face_verification                   │
│     ↓ (user verified face on GoodDollar)       │
│ [2] disbursing (atomic claim)                   │
│     ↓ (rewards processed)                       │
│ [3] completed                                   │
└──────────────────────────────────────────────────┘
```

### Referral Rewards Log (Disbursement Tracking)

```
┌────────────────────────────────────────────────────┐
│ referral_rewards_log table                         │
├────────────────────────────────────────────────────┤
│ Status Flow:                                       │
│                                                    │
│ [1] pending                                        │
│     ├─→ (user completes face verification)       │
│     └─→ [2a] completed (sufficient balance)      │
│         OR                                         │
│         [2b] pending_disbursed (low balance)      │
│             ↓ (admin tops up REFERRAL_KEY)       │
│             [3] completed                         │
│                                                    │
│ Alternative paths:                                │
│ pending → failed (permanent error)                │
│ pending_disbursed → failed (after retries)       │
└────────────────────────────────────────────────────┘
```

---

## Concurrency & Lock Safety

```
┌────────────────────────────────────────────────────────┐
│ Race Condition Prevention                               │
├────────────────────────────────────────────────────────┤
│                                                         │
│ Scenario: Two requests fire simultaneously             │
│ - /verify-identity calls disburse                      │
│ - /fv-callback also calls disburse                     │
│                                                         │
│ Solution: claim_pending_referral_for_disbursement()    │
│                                                         │
│ ┌─────────────────────────────────────┐              │
│ │ ATOMIC UPDATE:                      │              │
│ │ UPDATE referrals                    │              │
│ │ SET status = 'disbursing'          │              │
│ │ WHERE status = 'pending_face_...'   │              │
│ │   AND id = X                        │              │
│ └─────────────────────────────────────┘              │
│                                                         │
│ Only ONE request will succeed (database enforces)      │
│ Other gets {"claimed": false}                          │
│                                                         │
│ Winner disburses, loser aborts                         │
│ Result: NEVER double-pay ✓                            │
└────────────────────────────────────────────────────────┘
```

---

## Admin Visibility Flow

```
┌─────────────────────────────────────────┐
│ Admin calls /api/admin/referral/        │
│ key-balance                             │
└──────────────┬──────────────────────────┘
               │
               ▼
    ┌──────────────────────────┐
    │ Check REFERRAL_KEY wallet│
    │ on Celo blockchain       │
    │ balanceOf(REFERRAL_KEY)  │
    └──────────┬───────────────┘
               │
               ▼
    ┌──────────────────────────┐
    │ Query database for       │
    │ pending_disbursed count  │
    │ and total amount         │
    └──────────┬───────────────┘
               │
               ▼
    ┌──────────────────────────┐
    │ Return JSON:             │
    │ {                        │
    │   balance: 5000 G$      │
    │   pending_count: 3      │
    │   pending_total: 1500 G$│
    │   can_process: true     │
    │ }                        │
    └──────────┬───────────────┘
               │
               ▼
    ┌──────────────────────────┐
    │ Admin can decide:        │
    │ - Top up balance if low  │
    │ - Call process-pending   │
    │ - Monitor progress       │
    └──────────────────────────┘
```

---

## Fixed vs Broken System Comparison

### ❌ BEFORE (Broken)

```
Referral recorded
        ↓
User completes verification
        ↓
Disburse (insufficient balance)
        ↓
Status = 'pending' ← Wrong! Mixed status
        ↓
Admin tops up REFERRAL_KEY
        ↓
Call process-pending
        ↓
Looks for status = 'pending' ONLY
        ↓
Doesn't find status = 'pending_disbursed'
        ↓
❌ REWARDS NEVER DISBURSE
```

---

### ✅ AFTER (Fixed)

```
Referral recorded
        ↓
User completes verification
        ↓
Disburse (insufficient balance)
        ↓
Status = 'pending_disbursed' ← Correct! Clear status
        ↓
Admin tops up REFERRAL_KEY
        ↓
Call process-pending
        ↓
Looks for status IN ('pending', 'pending_disbursed')
        ↓
FINDS pending_disbursed records
        ↓
Retries disbursement
        ↓
✅ REWARDS SUCCESSFULLY DISBURSE
```

---

## Key State Transitions

| Event | Table | Old Status | New Status | Reason |
|-------|-------|-----------|------------|--------|
| New user signs up with code | referrals | - | pending_face_verification | Waiting for verification |
| User face-verifies | referrals | pending_face_verification | disbursing | Attempting disbursement |
| Disburse succeeds | referrals | disbursing | completed | Rewards sent |
| Disburse fails (low balance) | referral_rewards_log | pending | pending_disbursed | Waiting for balance |
| Admin tops up & retries | referral_rewards_log | pending_disbursed | completed | Retry succeeded |
| Disburse fails (other error) | referral_rewards_log | pending | failed | Unrecoverable error |

---

**System Status:** ✅ All flows fixed and properly tracked  
**Last Updated:** 2026-05-02
