# REFERRAL_KEY: Gas Fees & Balance Management

## Visual: How Gas Fees Work

```
┌─────────────────────────────────────────────────────────────────────┐
│                    REFERRAL DISBURSEMENT FLOW                        │
└─────────────────────────────────────────────────────────────────────┘

BEFORE:
┌──────────────────────────────┐
│   REFERRAL_KEY Wallet        │
│                              │
│   Balance: 5000 G$           │
│                              │
│   ├─ 1000 G$ (referrer)      │
│   ├─ 500 G$ (referee)        │
│   ├─ 0.001 G$ (gas fee) ⬅ User pays? NO! REFERRAL_KEY pays!
│   └─ ...                     │
└──────────────────────────────┘
            │
            ├─ Create TX on blockchain
            ├─ Estimate gas needed
            ├─ Get current gas_price from network
            ├─ Calculate: gas_fee = gas_limit × gas_price
            └─ Sign TX with REFERRAL_KEY (private key required)
            
AFTER TRANSACTION:
┌──────────────────────────────┐
│   REFERRAL_KEY Wallet        │
│                              │
│   Balance: 3499.999 G$       │
│                              │
│   -1000.000 G$ (to referrer) │
│   -500.000 G$ (to referee)   │
│   -0.001 G$ (gas fee)        │
└──────────────────────────────┘

User A receives: 1000 G$ ✓
User B receives: 500 G$ ✓
Gas paid from: REFERRAL_KEY ✓
```

## Detailed Breakdown

### What is "Gas"?
**Gas** = Cost to execute a transaction on blockchain

Think of it like:
```
Regular world:        Blockchain:
┌──────────────┐      ┌──────────────┐
│ Gas station  │      │ Blockchain   │
│ Pump gas     │      │ Execute TX   │
│ Pay money    │      │ Pay gas fee  │
└──────────────┘      └──────────────┘
```

### How Much Gas?

**Standard G$ Transfer:** ~250,000 gas units

**Gas Price on Celo Network:**
- Cheap times: 0.1-0.5 Gwei per gas unit
- Normal times: 0.5-1 Gwei per gas unit
- Busy times: 1-5 Gwei per gas unit

**Calculation:**
```
Gas Fee = Gas Units × Gas Price Per Unit

Example 1 (Cheap):
Gas Fee = 250,000 units × 0.1 Gwei = 25,000 Gwei = 0.000025 CELO

Example 2 (Normal):
Gas Fee = 250,000 units × 1 Gwei = 250,000 Gwei = 0.00025 CELO

Example 3 (Expensive):
Gas Fee = 250,000 units × 5 Gwei = 1,250,000 Gwei = 0.00125 CELO
```

### Why REFERRAL_KEY Pays?

```
┌──────────────────────────────────────────────────┐
│  WHO PAYS FOR BLOCKCHAIN OPERATIONS?             │
├──────────────────────────────────────────────────┤
│                                                   │
│  The account that SENDS the transaction          │
│  pays the gas fee.                               │
│                                                   │
│  In our case:                                    │
│  REFERRAL_KEY sends G$ to users                  │
│  └─> REFERRAL_KEY pays the gas fee               │
│                                                   │
│  NOT the user who receives the G$                │
│                                                   │
└──────────────────────────────────────────────────┘
```

## Code: Where Gas Fee is Paid

### blockchain.py - Line 124-135

```python
# Step 1: Get current gas price from Celo network
gas_price = int(self.w3.eth.gas_price * 1.2)  # Add 20% buffer

# Step 2: Build the transaction
txn = contract.functions.transfer(
    Web3.to_checksum_address(wallet_address),  # WHO gets G$
    amount_wei                                   # HOW MUCH G$
).build_transaction({
    'chainId': self.chain_id,
    'gas': 250000,        # Gas units allowed
    'gasPrice': gas_price, # Gas price from network
    'nonce': nonce,
    'from': referral_account.address  # WHO pays gas? ← REFERRAL_KEY!
})

# Step 3: Sign with REFERRAL_KEY's private key
signed_txn = self.w3.eth.account.sign_transaction(txn, key)

# Step 4: Send to blockchain
tx_hash = self.w3.eth.send_raw_transaction(signed_txn.raw_transaction)
```

## Impact: How Much Does It Cost?

### Real Math

```
Scenario: REFERRAL_KEY disburses to 1000 users

Per User:
  G$ sent:        1000 + 500 = 1500 G$
  Gas fee:        0.001 G$ (approx)
  Total:          1500.001 G$ per user

For 1000 users:
  Total G$ sent:  1500 × 1000 = 1,500,000 G$
  Total gas:      0.001 × 1000 = 1 G$ (negligible!)
  Total cost:     1,500,001 G$

REFERRAL_KEY needed: 1,500,010 G$ (with buffer)
```

### Cost Comparison

```
Scenario: Low balance situation

Available: 800 G$
Need to send referrer: 1000 G$
Enough? NO → Mark as "pending_disbursed"

Later: Admin tops up to 5000 G$
Need to send referrer: 1000.001 G$ (with gas)
Enough? YES → Disburse!
```

## Balance Requirements Table

| Scenario | Recommended Balance | Why |
|----------|-------------------|-----|
| **Just testing** | 100 G$ | Enough for ~66 disbursements |
| **Small deployment** | 500 G$ | Enough for ~333 disbursements |
| **Normal operation** | 2000 G$ | Enough for ~1333 disbursements |
| **High volume** | 5000+ G$ | Buffer for spikes + gas price changes |
| **Enterprise** | 10,000+ G$ | Run continuously without topping up |

## Low Balance Scenario - DETAILED FLOW

```
┌─────────────────────────────────────────────────────────────────┐
│                      SCENARIO: Low Balance                       │
└─────────────────────────────────────────────────────────────────┘

Step 1: User Refers Friend
┌──────────────────────┐
│ REFERRAL_KEY Balance: 800 G$ │
└──────────────────────┘
           │
           └─> New referral completes
               Need to disburse: 1500 G$
               Available: 800 G$
               
Step 2: Check Balance in blockchain.py
┌──────────────────────────────────────────┐
│ balance_wei = 800 × 10^18                 │
│ amount_wei = 1500 × 10^18                 │
│                                          │
│ if balance_wei < amount_wei:              │
│     # INSUFFICIENT BALANCE!               │
│     return {                              │
│         "success": False,                 │
│         "pending": True,  ← IMPORTANT!    │
│         "error": "insufficient_balance",  │
│         "balance_available": 800,         │
│         "balance_required": 1500          │
│     }                                     │
└──────────────────────────────────────────┘
           │
           └─> main.py receives response
               
Step 3: main.py Updates Database
┌──────────────────────────────────────────┐
│ referral_rewards_log table:              │
│                                          │
│ wallet: 0xuser_referrer                 │
│ amount: 1000                             │
│ status: "pending_disbursed" ← MARKED!    │
│ error: "Insufficient REFERRAL_KEY balance"
│                                          │
│ wallet: 0xuser_referee                  │
│ amount: 500                              │
│ status: "pending_disbursed" ← MARKED!    │
└──────────────────────────────────────────┘
           │
           └─> Admin sees problem
               
Step 4: Admin Checks Health
┌──────────────────────────────────────────┐
│ GET /api/admin/referral/key-balance      │
│                                          │
│ Response:                                │
│ {                                        │
│   "balance_g": 800,                      │
│   "pending_disbursements_count": 2,      │
│   "total_pending_amount_g": 1500,        │
│   "can_process": false ← ALERT!          │
│ }                                        │
└──────────────────────────────────────────┘
           │
           └─> Admin tops up REFERRAL_KEY to 2000 G$
               (Transfer 1200 G$ to wallet)
               
Step 5: REFERRAL_KEY Now Has Balance
┌──────────────────────────────────────────┐
│ REFERRAL_KEY Balance: 2000 G$ ✓          │
│ Pending needed: 1500 G$ ✓                │
│ Can disburse? YES ✓                      │
└──────────────────────────────────────────┘
           │
           └─> Admin calls: POST /api/admin/referral/process-pending
               
Step 6: process_pending_disbursements() Runs
┌──────────────────────────────────────────┐
│ Find ALL rewards with status:             │
│ - "pending" (awaiting verification)      │
│ - "pending_disbursed" (awaiting balance) │
│                                          │
│ For each pending reward:                 │
│   └─> Retry disbursement                 │
│       └─> Check balance: 2000 G$ > 1500 G$ ✓
│       └─> Send transaction ✓             │
│       └─> Update status to "completed" ✓ │
└──────────────────────────────────────────┘
           │
           └─> Users receive G$ ✓
           
Final State:
┌──────────────────────────────────────────┐
│ REFERRAL_KEY Balance: 499.999 G$         │
│ Pending count: 0                         │
│ Status: ALL DISBURSED ✓                  │
└──────────────────────────────────────────┘
```

## Admin Dashboard Must Show

To properly manage REFERRAL_KEY, admin dashboard should display:

```
┌─────────────────────────────────────────────────────────────┐
│                  ADMIN DASHBOARD - REFERRAL TAB             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  REFERRAL_KEY HEALTH CHECK                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Current Balance: 1200.50 G$                          │   │
│  │ ████████████████░░░░░░░░░░░░░░░░░░░░░ 24% of max   │   │
│  │                                                      │   │
│  │ ⚠️ WARNING: Low balance detected                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
│  PENDING DISBURSEMENTS                                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Count: 45 rewards waiting                           │   │
│  │ Total Owed: 45,000 G$                               │   │
│  │                                                      │   │
│  │ ⛔ CRITICAL: Balance < Amount Owed                  │   │
│  │    Need to top up at least 46,000 G$                │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
│  PENDING REWARDS LIST                                       │
│  ┌────────────────────────────────────────────────────┐    │
│  │ Wallet          │ Amount │ Type  │ Date            │    │
│  │─────────────────┼────────┼───────┼─────────────────│    │
│  │ 0xuser1...      │ 1000 G │ ref   │ 2026-05-01 10:30│   │
│  │ 0xuser2...      │  500 G │ fee   │ 2026-05-01 10:31│   │
│  │ 0xuser3...      │ 1000 G │ ref   │ 2026-05-01 10:32│   │
│  │ ...             │ ...    │ ...   │ ...             │   │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
│  ACTIONS                                                     │
│  [Top Up Instructions] [Retry Now] [View Logs]             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Key Takeaways

1. **REFERRAL_KEY pays the gas fee** - Not the users
2. **Gas is dynamic** - Changes based on network congestion
3. **Must have buffer** - Balance > Total rewards + gas buffer
4. **Low balance triggers pending state** - Auto-retries when topped up
5. **Admin visibility is critical** - Dashboard endpoint shows health

Your system now:
- ✓ Gracefully handles low balance
- ✓ Automatically retries when balance tops up
- ✓ Provides admin visibility into pending queue
- ✓ Tracks gas costs properly

Perfect for production! 🚀
