"""
Match first_login (user_data) with first GoodDollar UBI claim on Celo.

Window: April 23, 2026 -> May 1, 2026 (UTC, inclusive).

Approach:
  1. Pull user_data rows where first_login is in window.
  2. For each wallet, query Celo RPC (eth_getLogs) on GoodDollar token contract
     for Transfer events from UBI_PROXY -> wallet.
       - First scan a slightly larger window (April 22 -> May 2) to catch the
         claim that lines up with the first_login date.
       - Then verify it is truly the FIRST EVER claim by scanning earlier
         blocks (from a safe early block up to the first hit's block) for any
         earlier UBI Transfer to that wallet. If an earlier claim exists, the
         match is invalidated (first_claim != first_login date).
  3. Compare calendar date (UTC) of first_login vs first_claim.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from supabase import create_client  # type: ignore
except Exception as exc:
    print(f"[error] supabase python client not available: {exc}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CELO_RPC = os.getenv("CELO_RPC_URL", "https://forno.celo.org")
CHAIN_ID = int(os.getenv("CHAIN_ID", "42220"))

UBI_PROXY = os.getenv(
    "UBI_PROXY_CONTRACT", "0x43d72Ff17701B2DA814620735C39C620Ce0ea4A1"
).lower()
GOODDOLLAR_TOKEN = os.getenv(
    "GOODDOLLAR_TOKEN_CONTRACT", "0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A"
).lower()

# ERC20 Transfer(address indexed from, address indexed to, uint256)
TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)

# Reasonable lower bound: GoodDollar UBIScheme proxy was deployed long ago.
# Pick a conservative early Celo block (Sept 2020-ish) to cover all history.
HISTORY_FLOOR_BLOCK = int(os.getenv("HISTORY_FLOOR_BLOCK", "2000000"))

# Forno allows up to ~10k blocks per eth_getLogs filter.
LOG_RANGE_CHUNK = int(os.getenv("LOG_RANGE_CHUNK", "9000"))

SESSION = requests.Session()


# ---------------------------------------------------------------------------
# RPC helpers
# ---------------------------------------------------------------------------

_rpc_id = 0


def _rpc(method: str, params: List[Any]) -> Any:
    global _rpc_id
    _rpc_id += 1
    payload = {"jsonrpc": "2.0", "id": _rpc_id, "method": method, "params": params}
    for attempt in range(5):
        try:
            r = SESSION.post(CELO_RPC, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                err = data["error"]
                # Some "range too large" errors -> raise to caller
                msg = str(err.get("message", err))
                raise RuntimeError(f"rpc_error: {msg}")
            return data["result"]
        except requests.RequestException as e:
            if attempt == 4:
                raise
            time.sleep(1 + attempt)
    raise RuntimeError("unreachable")


def block_by_number(num_hex: str) -> Optional[Dict[str, Any]]:
    return _rpc("eth_getBlockByNumber", [num_hex, False])


def latest_block() -> int:
    return int(_rpc("eth_blockNumber", []), 16)


def find_block_at_or_after(ts: int, lo: int, hi: int) -> int:
    """Binary search lowest block whose timestamp >= ts."""
    while lo < hi:
        mid = (lo + hi) // 2
        b = block_by_number(hex(mid))
        if not b:
            lo = mid + 1
            continue
        bts = int(b["timestamp"], 16)
        if bts >= ts:
            hi = mid
        else:
            lo = mid + 1
    return lo


def find_block_at_or_before(ts: int, lo: int, hi: int) -> int:
    """Binary search highest block whose timestamp <= ts."""
    res = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        b = block_by_number(hex(mid))
        if not b:
            break
        bts = int(b["timestamp"], 16)
        if bts <= ts:
            res = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return res


def addr_topic(addr: str) -> str:
    a = addr.lower().replace("0x", "")
    return "0x" + a.rjust(64, "0")


def get_logs(from_block: int, to_block: int, topics: List[Any]) -> List[Dict]:
    """Chunked eth_getLogs scan."""
    out: List[Dict] = []
    cur = from_block
    while cur <= to_block:
        end = min(cur + LOG_RANGE_CHUNK - 1, to_block)
        params = {
            "address": GOODDOLLAR_TOKEN,
            "fromBlock": hex(cur),
            "toBlock": hex(end),
            "topics": topics,
        }
        try:
            res = _rpc("eth_getLogs", [params]) or []
        except RuntimeError as e:
            # If range too large, halve the chunk and retry once
            msg = str(e)
            if "range" in msg.lower() or "limit" in msg.lower() or "too" in msg.lower():
                mid = (cur + end) // 2
                left = get_logs(cur, mid, topics)
                right = get_logs(mid + 1, end, topics)
                out.extend(left)
                out.extend(right)
                cur = end + 1
                continue
            raise
        out.extend(res)
        cur = end + 1
    return out


# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------


def supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
    )
    if not url or not key:
        print("[error] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
        sys.exit(1)
    is_service = bool(
        os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    )
    print(f"[info] supabase using {'SERVICE_ROLE' if is_service else 'ANON'} key")
    return create_client(url, key)


def fetch_users(sb, start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    page = 0
    while True:
        q = (
            sb.table("user_data")
            .select(
                "id,wallet_address,first_login,verified_after_goodmarket,verified_at_goodmarket_at,profile_username"
            )
            .gte("first_login", start_iso)
            .lte("first_login", end_iso)
            .order("first_login")
            .range(page * 1000, (page + 1) * 1000 - 1)
        )
        res = q.execute()
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < 1000:
            break
        page += 1
    return rows


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def parse_iso_to_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def find_first_claim_for_wallet(
    wallet: str,
    window_from_block: int,
    window_to_block: int,
) -> Optional[Tuple[int, int, str]]:
    """
    Returns (block_number, timestamp, tx_hash) of FIRST EVER UBI claim
    (Transfer from UBI_PROXY to wallet on GoodDollar token), or None.
    """
    topics = [TRANSFER_TOPIC, addr_topic(UBI_PROXY), addr_topic(wallet)]

    # Step 1: scan history up to and including window_to_block.
    logs = get_logs(HISTORY_FLOOR_BLOCK, window_to_block, topics)
    if not logs:
        return None

    # First log in ascending order
    logs.sort(key=lambda l: (int(l["blockNumber"], 16), int(l["logIndex"], 16)))
    first = logs[0]
    bn = int(first["blockNumber"], 16)
    tx = first["transactionHash"]
    block = block_by_number(hex(bn))
    if not block:
        return None
    ts = int(block["timestamp"], 16)
    return (bn, ts, tx)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="d_from", default="2026-04-23")
    p.add_argument("--to", dest="d_to", default="2026-05-01")
    p.add_argument(
        "--out", default="audit_first_login_vs_first_claim.csv", help="output csv path"
    )
    args = p.parse_args()

    start_dt = datetime.strptime(args.d_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(args.d_to, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )

    print(f"[info] window: {start_dt.isoformat()} -> {end_dt.isoformat()}")
    print(f"[info] RPC: {CELO_RPC} (chain_id={CHAIN_ID})")
    print(f"[info] UBI_PROXY: {UBI_PROXY}")
    print(f"[info] GOODDOLLAR_TOKEN: {GOODDOLLAR_TOKEN}")

    # 1) Pull users
    sb = supabase_client()
    rows = fetch_users(
        sb,
        start_dt.isoformat(),
        end_dt.isoformat(),
    )
    print(f"[info] user_data rows in window: {len(rows)}")

    # filter: must have wallet
    rows = [r for r in rows if r.get("wallet_address")]
    print(f"[info] with wallet_address: {len(rows)}")

    if not rows:
        print("[done] no users in window with wallet address.")
        return

    # 2) Resolve block range (with buffer) for the window
    #    buffer = +/- 1 day so we comfortably cover same-date matches.
    buf_from_ts = int((start_dt - timedelta(days=1)).timestamp())
    buf_to_ts = int((end_dt + timedelta(days=1)).timestamp())
    tip = latest_block()
    print(f"[info] latest block: {tip}")
    print("[info] resolving window block range (binary search)...")
    win_from_block = find_block_at_or_after(buf_from_ts, HISTORY_FLOOR_BLOCK, tip)
    win_to_block = find_block_at_or_before(buf_to_ts, win_from_block, tip)
    print(
        f"[info] window blocks: {win_from_block} -> {win_to_block} "
        f"({win_to_block - win_from_block:,} blocks)"
    )

    # 3) Per-wallet first claim lookup
    out_rows = []
    matches = []
    for i, r in enumerate(rows, 1):
        wallet = (r["wallet_address"] or "").strip()
        first_login = parse_iso_to_dt(r.get("first_login"))
        verified_via_gm = r.get("verified_after_goodmarket")
        v_at = parse_iso_to_dt(r.get("verified_at_goodmarket_at"))
        username = r.get("profile_username") or ""

        print(
            f"[{i}/{len(rows)}] {wallet}  first_login={first_login.isoformat() if first_login else '-'}"
        )

        try:
            res = find_first_claim_for_wallet(wallet, win_from_block, win_to_block)
        except Exception as e:
            print(f"    [warn] rpc error: {e}")
            res = None

        if res is None:
            first_claim_dt = None
            first_claim_tx = ""
            first_claim_block = ""
        else:
            bn, ts, tx = res
            first_claim_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            first_claim_tx = tx
            first_claim_block = bn

        same_date = False
        delta_seconds = ""
        if first_login and first_claim_dt:
            same_date = first_login.date() == first_claim_dt.date()
            delta_seconds = int(
                (first_claim_dt - first_login).total_seconds()
            )

        out_rows.append(
            {
                "wallet_address": wallet,
                "username": username,
                "first_login_utc": first_login.isoformat() if first_login else "",
                "first_claim_utc": first_claim_dt.isoformat() if first_claim_dt else "",
                "same_calendar_date_utc": "YES" if same_date else "NO",
                "delta_seconds_claim_minus_login": delta_seconds,
                "first_claim_tx": first_claim_tx,
                "first_claim_block": first_claim_block,
                "verified_after_goodmarket": bool(verified_via_gm),
                "verified_at_goodmarket_at_utc": v_at.isoformat() if v_at else "",
                "celoscan_url": (
                    f"https://celoscan.io/tx/{first_claim_tx}" if first_claim_tx else ""
                ),
            }
        )
        if same_date:
            matches.append(out_rows[-1])

        # be polite with public RPC
        time.sleep(0.15)

    # 4) Write CSV
    out_path = args.out
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n[done] wrote {len(out_rows)} rows -> {out_path}")
    print(f"[summary] same-date matches: {len(matches)} / {len(out_rows)}")
    if matches:
        print("[summary] matched wallets:")
        for m in matches:
            print(
                f"  - {m['wallet_address']}  login={m['first_login_utc']}  "
                f"claim={m['first_claim_utc']}  tx={m['first_claim_tx']}"
            )


if __name__ == "__main__":
    main()
