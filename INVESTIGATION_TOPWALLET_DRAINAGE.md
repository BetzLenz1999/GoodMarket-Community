# TOPWALLET_KEY CELO Balance Drainage - Investigation Report

## Problem Summary
Your CELO balance sa TOPWALLET_KEY ay mabilis na naubos. You suspected na ang system ay gumagamit ng TOPWALLET_KEY para sa gas/claiming, pero dapat ang API FAUCET ang priority.

## Current Architecture (WHAT I FOUND)

### 1. **Gas Faucet Flow** (`/api/faucet/gas` endpoint - routes.py:8066-8265)
**Priority is CORRECT** ✅
- **Step A**: Check if user already has enough gas (`gas_ready`)
- **Step B**: Try API FAUCET FIRST (lines 8141-8174)
  - Calls GoodDollar API: `GOODDOLLAR_FAUCET_API_URL`
  - If success → Return immediately (user gets gas from API)
  - If API fails → Continue to Step C
- **Step C**: On-chain fallback using TOPWALLET_KEY (lines 8230-8265)
  - Only if API fails AND `force_onchain` is true
  - Uses TOPWALLET_KEY to sign `topWallet(user_address)` transaction on-chain

**Logging shows**:
- Line 8090: `source=api+fallback` 
- Line 8069: Comment says "API faucet first, then TOPWALLET_KEY on-chain fallback"

### 2. **XDC Gas Faucet Flow** (`/api/xdc/faucet/gas` - routes.py:8338-8490)
Same priority structure as CELO ✅

### 3. **Reward Disbursement** (Multiple blockchain services)
FOUND IN:
- `twitter_task/blockchain.py` - Disburse Twitter rewards
- `telegram_task/blockchain.py` - Disburse Telegram rewards  
- `learn_and_earn/blockchain.py` - Disburse Learn & Earn rewards
- `referral_program/blockchain.py` - Disburse Referral rewards
- `minigames/blockchain.py` - Disburse Minigame rewards
- `discourse_task/blockchain.py` - Disburse Discourse rewards
- `community_stories/blockchain.py` - Disburse Community Story rewards

**CRITICAL**: These might be using TOPWALLET_KEY as a USER SIGNER (not just for gas)!

## ROOT CAUSE FOUND! 🎯

**The culprit is NOT TOPWALLET_KEY for gas faucet - it's `DAILYTASK_KEY` used for REWARD DISBURSEMENT!**

### The Real Issue: DAILYTASK_KEY Fallback for Task Rewards

When users claim rewards from tasks (Twitter, Telegram, Learn & Earn, etc.), the system:

1. **Primary**: Tries to disburse via DailyTaskRewards contract
2. **Fallback**: If the contract has insufficient balance, it uses `DAILYTASK_KEY` to directly transfer G$ tokens to the user

**This is where the bleeding happens!** 

Files affected:
- `telegram_task/blockchain.py` (line 318-490)
- `twitter_task/blockchain.py` (line 305+)
- Similar pattern in other task services

**Example flow** (telegram_task/blockchain.py:166-186):
```python
if contract_balance < reward_amount:
    logger.warning(f"Attempting DAILYTASK_KEY fallback (direct G$ transfer).")
    fallback_result = self._disburse_via_fallback_key(
        wallet_address=wallet_address,
        reward_amount_wei=reward_amount,
        task_id=task_id,
    )
```

### Why This Drains Quickly

Every time a user claims a reward AND the contract is low on funds:
- `DAILYTASK_KEY` signs a G$ transfer transaction
- This costs CELO gas (depletes CELO balance)
- **But you mistook this for TOPWALLET_KEY!**

**They might be the SAME KEY!** Check if:
- `DAILYTASK_KEY` environment variable
- `TOPWALLET_KEY` environment variable
- Are they pointing to the same wallet address?

### Secondary Issue: API FAUCET for Gas

The gas faucet is correctly prioritized (API first), BUT:
- If API FAUCET is down → falls back to TOPWALLET_KEY for gas top-ups
- This is a legitimate fallback, but you need API working properly

## Action Items

1. **Check Environment Variables** 🔍
   ```bash
   # Which keys exist and do they have the same address?
   echo $DAILYTASK_KEY    # Used for reward disbursement fallback
   echo $TOPWALLET_KEY    # Used for gas faucet fallback
   echo $TASK_KEY         # Used for contract calls (should have G$ or be funded differently)
   ```

2. **Disable or Improve DAILYTASK_KEY Fallback**
   - Option A: Don't use DAILYTASK_KEY direct transfer (requires funded contract)
   - Option B: Use a separate, cheaper mechanism for fallback
   - Option C: Add balance monitoring to prevent over-use

3. **Monitor Gas vs Reward Drain**
   - Log which system is using CELO (gas vs rewards)
   - Alert when CELO balance drops below threshold

## Next Steps for Investigation

### 1. Check API FAUCET Status
```bash
# Is GOODDOLLAR_FAUCET_API_URL accessible?
curl -X POST $GOODDOLLAR_FAUCET_API_URL -H "Content-Type: application/json" \
  -d '{"chainId": 42220, "account": "0xYourTestWallet"}'
```

### 2. Check Logs for Fallback Usage
Search logs for:
- `"source=onchain"` - Uses TOPWALLET_KEY
- `"onchain_fallback_reason"` - Why was fallback triggered
- `"signer_insufficient_funds"` - TOPWALLET_KEY ran out

### 3. Audit Reward Disbursement Code
Check each `*/blockchain.py` file to see:
- Is TOPWALLET_KEY used as signer for user transfers?
- OR is it only used to subsidize gas fees?

### 4. Add Monitoring/Logging
Recommend adding:
- Alert when TOPWALLET_KEY balance drops below threshold
- Log every TOPWALLET_KEY usage with reason (gas vs transfer)
- Track which service drained the most

## What I CAN Help You Fix

Once you identify the root cause:

✅ **If API is down**: 
- Configure fallback API endpoint
- Add retry logic with exponential backoff

✅ **If rewards use TOPWALLET_KEY as signer**:
- Migrate to dedicated signer per service
- OR use contract allowance mechanism instead

✅ **If frontend forces on-chain**:
- Remove `force_onchain=true` from default requests
- Add smarter detection logic

## Files To Review

High Priority:
- `telegram_task/blockchain.py` - Line 612-618 disbursement
- `twitter_task/blockchain.py` - Equivalent to telegram
- Check if these use TOPWALLET_KEY for signing user transfers

Medium Priority:
- Frontend code calling `/api/faucet/gas`
- `routes.py` lines 8141-8174 (API call logic)

---

**ACTION REQUIRED**: Tell me which direction you think is the issue (API down, rewards using TOPWALLET, or frontend issue) and I'll dive deeper! 🔍
