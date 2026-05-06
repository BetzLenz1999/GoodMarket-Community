# GoodDollar Faucet Flow Fix - Implementation Summary

**Status**: Complete
**Date**: May 5, 2026

## Problem Statement

The gas faucet system was draining the TOPWALLET_KEY CELO balance rapidly because:
1. Frontend was automatically retrying with `force_onchain=true` when API cooldown was triggered
2. No rate limiting on `force_onchain` attempts, allowing spam/repeated TOPWALLET_KEY usage
3. Cooldown was not being enforced when `force_onchain=true` was explicitly passed

## Solution Implemented

### Backend Changes (routes.py)

#### 1. **Strict Cooldown Enforcement** (Lines 8151-8176)
- **Before**: `if recent_refill and not force_onchain` - cooldown was bypassable with `force_onchain=true`
- **After**: `if recent_refill:` - cooldown is now enforced REGARDLESS of the flag
- Logs error when `force_onchain` attempt is made during cooldown period
- Returns 200 with `status: "recent_refill"` blocking both API and on-chain paths

**Impact**: TOPWALLET_KEY can no longer be used as a bypass mechanism for cooldown protection.

#### 2. **Rate Limiting for force_onchain** (Lines 7542-7549, 7731-7769, 8178-8194)
- Added new state tracking: `_force_onchain_attempts` dict to track attempts per wallet per hour
- Environment variable: `FAUCET_FORCE_ONCHAIN_MAX_PER_HOUR` (default: 2)
- New functions:
  - `_check_force_onchain_rate_limit()`: Checks if wallet exceeded limit
  - `_record_force_onchain_attempt()`: Records each force_onchain call
- Rate limit returns HTTP 429 with retry-after hint
- Cleaned up old attempts automatically (outside 1-hour window)

**Impact**: Even with `force_onchain=true`, users can only use on-chain fallback max 2 times per hour, preventing CELO drainage from spam.

#### 3. **Enhanced Logging** (Lines 8154-8158, 8185-8193)
- Error logs when cooldown is breached: `"❌ Faucet cooldown breach attempt"`
- Error logs when rate limit exceeded: `"❌ Faucet force_onchain rate limit exceeded"`
- Includes wallet address, cooldown remaining, rate limit details, and correlation ID for audit trail
- Diagnostics include `force_onchain_attempts_remaining` and `force_onchain_rate_limit_max`

### Frontend Changes (templates/wallet.html)

#### 1. **Removed Automatic force_onchain Retry** (Lines 3760-3761, 3889-3890)
- **Before**: If API returned `recent_refill`, frontend auto-retried with `force_onchain=true`
- **After**: Frontend shows cooldown error and lets user retry manually after cooldown expires
- Applies to both CELO (`/api/faucet/gas`) and XDC (`/api/xdc/faucet/gas`)

**Impact**: No more silent bypass of rate limiting; users must wait for cooldown instead of forcing on-chain.

#### 2. **Added Cooldown Countdown UI** (Lines 3757-3773, 3892-3910)
- Shows remaining cooldown seconds in error message
- Starts countdown timer if `appendStatusLine()` UI exists
- Updates UI every 1 second with countdown
- Informs user when cooldown expires: "Cooldown expired. You can retry now."

**Impact**: Better UX - users see exactly how long they need to wait before retrying.

### Testing

#### New Test Cases Added (tests/test_faucet_flow.py)
1. **test_cooldown_enforced_even_with_force_onchain**: Verifies cooldown blocks even with `force_onchain=true`
   - Confirms `debug["force_onchain_blocked"]` is set to true
   - No API or on-chain attempts made

2. **test_force_onchain_rate_limit_exceeded**: Verifies rate limiting works
   - Makes 2 force_onchain calls (within limit) - succeed
   - Makes 3rd call (exceeds limit) - returns 429 with `status: "force_onchain_rate_limited"`
   - Includes retry-after hint in response

## Configuration

### Environment Variables
```bash
# New variables:
FAUCET_FORCE_ONCHAIN_MAX_PER_HOUR=2        # Default: max 2 force_onchain per hour per wallet
FAUCET_FORCE_ONCHAIN_HOUR_WINDOW=3600      # 1 hour window (3600 seconds)

# Existing variables (unchanged):
FAUCET_DUPLICATE_WINDOW_MIN=30             # Cooldown between any refills
FAUCET_MIN_CELO=0.1                        # Min CELO threshold
```

### Rate Limiting Strategy
- **Per Wallet**: Each wallet has its own force_onchain attempt counter
- **Per Hour**: Attempts are counted in 1-hour rolling windows
- **Auto-cleanup**: Old attempts outside window are automatically cleaned
- **Persistent During Session**: Stored in-memory per Python process

## Alignment with GoodDollar

This fix aligns perfectly with GoodDollar's design:
- ✓ **API Faucet First**: GoodDollar API is now the actual primary method, not bypassed
- ✓ **On-Chain Fallback**: TOPWALLET_KEY is only used when API genuinely fails
- ✓ **Cooldown Respect**: Rate limiting honored at all times, preventing abuse
- ✓ **No Token Loss**: No G$ tokens are lost, just gas cost optimization
- ✓ **Better Audit Trail**: All force_onchain attempts are logged for monitoring

## Impact Analysis

### TOPWALLET_KEY CELO Balance
- **Before**: Rapidly depleted due to frequent force_onchain retries
- **After**: Only used for genuine API failures + rate-limited to max 2/hour
- **Expected Result**: CELO balance stabilizes and drains at natural rate

### User Experience
- **Before**: Silent bypass, users don't know why gas requests fail
- **After**: Clear cooldown message with countdown timer
- **Better**: Users understand the rate limit and plan accordingly

### System Reliability
- **Before**: Frontend could spam on-chain calls, potentially causing RPC issues
- **After**: Rate-limited on-chain calls, backend logs all attempts for monitoring

## Files Modified

1. `/vercel/share/v0-project/routes.py` (Backend)
   - Added `_force_onchain_attempts` dict for tracking
   - Added `FAUCET_FORCE_ONCHAIN_MAX_PER_HOUR` config
   - Added `_check_force_onchain_rate_limit()` function
   - Added `_record_force_onchain_attempt()` function
   - Modified cooldown check to enforce regardless of `force_onchain` flag
   - Added rate limit check in faucet_gas endpoint
   - Enhanced logging with error messages and diagnostics

2. `/vercel/share/v0-project/templates/wallet.html` (Frontend)
   - Removed auto-retry logic on recent_refill for CELO gas
   - Removed auto-retry logic on recent_refill for XDC gas
   - Added countdown timer UI for CELO cooldown
   - Added countdown timer UI for XDC cooldown

3. `/vercel/share/v0-project/tests/test_faucet_flow.py` (Tests)
   - Added test_cooldown_enforced_even_with_force_onchain
   - Added test_force_onchain_rate_limit_exceeded
   - Added test_xdc_cooldown_enforced_even_with_force_onchain (XDC parity)
   - Added test_xdc_force_onchain_rate_limit_exceeded (XDC parity)

## XDC Parity (added later)

The original May 5 fix only covered the Celo route (`/api/faucet/gas`). The XDC route (`/api/xdc/faucet/gas`) still allowed `force_onchain=true` to bypass cooldown and was not subject to the per-hour rate limit, so the same drain pattern was reachable by hitting the XDC endpoint instead of the Celo one. The XDC route now applies the same two protections:

1. Strict cooldown — `if recent_refill:` (no `and not force_onchain`); when `force_onchain=true` is sent during cooldown the breach is logged with `network=xdc`.
2. `_check_force_onchain_rate_limit` / `_record_force_onchain_attempt` are called before the on-chain fallback. The same in-memory state is shared across Celo and XDC, so a single wallet's per-hour limit applies to both networks combined.

The `topWallet(address)` selector and the `GOODDOLLAR_XDC_FAUCET_CONTRACT` (`0x7344Da1Be296f03fbb8082aDaC5696058B5a9bd9`, deployed by the GoodDollar Deployer on XDC) are unchanged.

## Verification Steps

1. **Cooldown Enforcement**: Test that `force_onchain=true` is rejected during cooldown
   - Endpoint: `/api/faucet/gas` with `{"force_onchain": true, "wallet": "0x..."}`
   - During cooldown period
   - Expected: Returns 200 with `status: "recent_refill"` (not 429)

2. **Rate Limiting**: Test that 3rd force_onchain exceeds limit
   - Make 3 consecutive force_onchain requests within 1 hour
   - Expected: 1st and 2nd succeed, 3rd returns 429

3. **Frontend Countdown**: Test that UI shows countdown timer
   - Trigger cooldown error on frontend
   - Verify countdown timer appears in status line
   - Verify countdown decrements every second

4. **API Fallback Path**: Verify API is still tried first when no cooldown
   - Make request without cooldown
   - Monitor logs to confirm API attempt before on-chain fallback

## Rollback Plan (if needed)

If issues arise:
1. Revert `routes.py` changes to remove rate limiting (git revert)
2. Frontend will handle 429 responses by trying alternative approach
3. Or revert `wallet.html` changes to restore auto-retry (temporary workaround)

## Future Improvements

1. **Persistent Rate Limiting**: Move `_force_onchain_attempts` to Redis/database for multi-process deployments
2. **Dynamic Limits**: Adjust `FAUCET_FORCE_ONCHAIN_MAX_PER_HOUR` based on system load
3. **Metrics Dashboard**: Track force_onchain usage, cooldown breaches, CELO balance trends
4. **User Notifications**: Notify users when approaching rate limit threshold
5. **Admin Override**: Add admin endpoint to bypass rate limits for support cases

## Notes

- All changes respect GoodDollar's API-first architecture
- No changes to smart contract interactions or G$ token flows
- Backward compatible: Old clients without rate limit awareness still work
- Rate limiting is permissive (2/hour) to allow legitimate use cases
- Cooldown enforcement prevents most abuse without explicit rate limiting
