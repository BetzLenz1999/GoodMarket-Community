# Learn & Earn Streaming Payout Implementation Plan

## Goal
Implement asynchronous, auto-stopped reward streaming (e.g., 700 G$ over 1 day) using GoodDollar on Celo, while preserving existing instant payout path.

## Why no full restructure is needed
The current Learn & Earn flow can remain as-is for quiz completion and reward computation. We only add a payout orchestration layer:
- stream job creation,
- stream lifecycle tracking,
- automated stop worker,
- admin observability.

## Core concepts
- **User wallet**: recipient address.
- **Sender wallet**: treasury/hot wallet used by backend.
- **Stream token**: GoodDollar streamable token contract (SuperToken-compatible token on Celo).
- **Auto-stop**: requires a transaction; implemented by scheduled worker, not manual operations.

## Data model
Apply migration in `sql/learn_earn_streaming_payouts.sql`.

Primary table: `learn_earn_streams`
- `status`: `pending_start`, `active`, `pending_stop`, `stopped`, `start_failed`, `stop_failed`
- `idempotency_key`: prevents duplicate creation
- `retry_count` + `last_error`: resilient retries
- `create_tx_hash` / `stop_tx_hash`: explorer traceability

Audit table: `learn_earn_stream_events`
- append-only events for debugging and support.

## Recommended worker lifecycle
1. Completion creates row in `learn_earn_streams` as `pending_start`.
2. Start worker computes flow rate and submits create-flow transaction.
3. On success, row becomes `active` with `start_at` and `end_at`.
4. Stop scheduler runs every 1-5 minutes, picks overdue active streams (`end_at <= now()`).
5. Stop worker submits stop-flow transaction and marks `stopped`.
6. Failed actions move to `*_failed` and retry with backoff.

## Flow-rate math
For amount `A` and duration `D` seconds:

`flow_rate = A / D`

Example: `700 G$` over `1 day`:
- `D = 86400`
- `rate ≈ 0.00810185185 G$/sec`

Production code should compute in integer wei-like units to avoid floating-point precision issues.

## User transparency UX
Expose in Learn & Earn history card:
- total reward,
- stream rate,
- started at / ends at,
- status,
- start tx link,
- stop tx link.

This avoids confusion when explorer does not show per-second transfers like regular ERC20 sends.

## Suggested file-level implementation sequence
1. `sql/learn_earn_streaming_payouts.sql` (done)
2. `learn_and_earn/blockchain.py` (create/stop wrappers + flow-rate helper)
3. `learn_and_earn/learn_and_earn.py` (enqueue stream jobs / fallback behavior)
4. `maintenance_service.py` (scheduler for due stream stops)
5. `templates/learn_and_earn.html` (stream tracking card)

## Safety checks before stream creation
- valid recipient wallet,
- non-duplicate idempotency key,
- sender has enough G$ and CELO gas buffer,
- configured stream token contract address present,
- reward still unpaid.
