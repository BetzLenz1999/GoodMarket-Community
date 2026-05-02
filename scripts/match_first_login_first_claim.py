#!/usr/bin/env python3
"""
Fast audit: for each user_data row whose `first_login` falls inside [--from, --to],
fetch the wallet's UBI claims around that date from a Celo RPC and report:

  - first_login_date_utc : calendar date of first_login (UTC)
  - claim_on_same_date   : was there a UBI claim on that same UTC date?
  - same_date_claim_tx   : tx hash of that claim
  - earlier_claim_exists : did the wallet have ANY UBI claim on a DATE BEFORE first_login_date?
  - match                : TRUE only if claim_on_same_date AND NOT earlier_claim_exists

Strategy (FAST - ~30s for 22 wallets):
  - Per-wallet narrow eth_getLogs (Transfer from=UBI_PROXY topic2=wallet) over
    just the calendar day of first_login (~17,280 blocks => 4 chunks of 5k).
  - If a same-date claim is found, do a backwards walk in widening windows
    (30d, 90d, 365d, 5y) to detect any earlier claim.

Usage:
  uv run python scripts/match_first_login_first_claim.py --from 2026-04-23 --to 2026-05-01
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from supabase import create_client


# ----------------------------- Configuration -----------------------------

CELO_RPC = os.getenv("CELO_RPC_URL", "https://forno.celo.org")
CHAIN_ID = int(os.getenv("CHAIN_ID", "42220"))

UBI_PROXY = os.getenv(
    "UBI_PROXY_CONTRACT", "0x43d72Ff17701B2DA814620735C39C620Ce0ea4A1"
).lower()
GOODDOLLAR_TOKEN = os.getenv(
    "GOODDOLLAR_TOKEN_CONTRACT", "0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A"
).lower()

# ERC20 Transfer(address indexed from, address indexed to, uint256)
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

LOG_RANGE_CHUNK = int(os.getenv("LOG_RANGE_CHUNK", "5000"))

SESSION = requests.Session()


# ----------------------------- RPC helpers -----------------------------

_rpc_id = 0


def _rpc(method: str, params: List[Any]) -> Any:
    global _rpc_id
    _rpc_id += 1
    payload = {"jsonrpc": "2.0", "id": _rpc_id, "method": method, "params": params}
    last_err: Optional[Exception] = None
    for attempt in range(5):
        try:
            r = SESSION.post(CELO_RPC, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                err = data["error"]
                msg = str(err.get("message", err))
                # rate-limit / range errors -> retry
                if any(s in msg.lower() for s in ("rate", "limit", "range", "size", "many", "timeout")):
                    raise RuntimeError(f"rpc_retryable: {msg}")
                raise RuntimeError(f"rpc_error: {msg}")
            return data["result"]
        except (requests.RequestException, RuntimeError) as e:
            last_err = e
            time.sleep(0.5 * (attempt + 1))
    raise last_err  # type: ignore[misc]


def latest_block() -> int:
    return int(_rpc("eth_blockNumber", []), 16)


def block_timestamp(block_no: int) -> int:
    blk = _rpc("eth_getBlockByNumber", [hex(block_no), False])
    if not blk:
        raise RuntimeError(f"block {block_no} not found")
    return int(blk["timestamp"], 16)


def addr_topic(addr: str) -> str:
    a = addr.lower().replace("0x", "")
    return "0x" + a.rjust(64, "0")


def get_logs_chunk(from_block: int, to_block: int, topics: List[Any]) -> List[Dict]:
    params = {
        "address": GOODDOLLAR_TOKEN,
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
        "topics": topics,
    }
    try:
        return _rpc("eth_getLogs", [params]) or []
    except RuntimeError as e:
        msg = str(e).lower()
        if any(s in msg for s in ("range", "limit", "too", "size", "many")):
            if from_block >= to_block:
                raise
            mid = (from_block + to_block) // 2
            return get_logs_chunk(from_block, mid, topics) + get_logs_chunk(mid + 1, to_block, topics)
        raise


def chunked_get_logs(
    from_block: int, to_block: int, topics: List[Any], chunk_size: int = LOG_RANGE_CHUNK
) -> List[Dict]:
    out: List[Dict] = []
    cur = from_block
    while cur <= to_block:
        end = min(cur + chunk_size - 1, to_block)
        logs = get_logs_chunk(cur, end, topics)
        if logs:
            out.extend(logs)
        cur = end + 1
    return out


# ----------------------- Block <-> timestamp resolver -----------------------

def find_block_at_or_after(target_ts: int, latest_no: int, latest_ts: int) -> int:
    """Binary search lowest block with timestamp >= target_ts. Returns latest_no+1
    if target_ts is in the future."""
    if target_ts <= 0:
        return 0
    if target_ts > latest_ts:
        return latest_no + 1
    lo, hi = 0, latest_no
    while lo < hi:
        mid = (lo + hi) // 2
        ts = block_timestamp(mid)
        if ts < target_ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


# ----------------------------- Supabase -----------------------------

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
    print(f"[info] supabase using {'SERVICE_ROLE' if is_service else 'ANON'} key", flush=True)
    return create_client(url, key)


def fetch_users(sb, start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    page = 0
    while True:
        res = (
            sb.table("user_data")
            .select(
                "id,wallet_address,first_login,verified_after_goodmarket,verification_timestamp,username"
            )
            .gte("first_login", start_iso)
            .lte("first_login", end_iso)
            .not_.is_("wallet_address", None)
            .order("first_login")
            .range(page * 1000, (page + 1) * 1000 - 1)
            .execute()
        )
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < 1000:
            break
        page += 1
    return rows


# ----------------------------- Audit -----------------------------

def parse_iso_to_dt(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def audit_wallet(
    *,
    wallet: str,
    first_login_dt: datetime,
    latest_no: int,
    latest_ts: int,
) -> Dict[str, Any]:
    wallet_topic = addr_topic(wallet)
    ubi_topic = addr_topic(UBI_PROXY)

    fl_date = first_login_dt.astimezone(timezone.utc).date()
    day_start_ts = int(datetime(fl_date.year, fl_date.month, fl_date.day, tzinfo=timezone.utc).timestamp())
    day_end_ts = day_start_ts + 86400 - 1

    start_block = find_block_at_or_after(day_start_ts, latest_no, latest_ts)
    end_block_excl = find_block_at_or_after(day_end_ts + 1, latest_no, latest_ts)
    end_block = max(start_block, end_block_excl - 1)

    topics = [TRANSFER_TOPIC, ubi_topic, wallet_topic]

    # 1) Same-date claim?
    same_date_logs: List[Dict] = []
    if start_block <= latest_no and start_block <= end_block:
        same_date_logs = chunked_get_logs(start_block, min(end_block, latest_no), topics)
    same_date_logs.sort(key=lambda l: (int(l["blockNumber"], 16), int(l["logIndex"], 16)))

    # 2) Earlier claim? Widening backward search.
    earlier_exists = False
    earlier_block: Optional[int] = None
    earlier_tx: Optional[str] = None
    earlier_ts: Optional[int] = None

    if start_block > 0:
        prior_end = start_block - 1
        for wnd_days in (30, 90, 365, 365 * 5):
            wnd_start_ts = day_start_ts - (wnd_days * 86400)
            prior_start = find_block_at_or_after(wnd_start_ts, latest_no, latest_ts)
            if prior_start > prior_end:
                break
            logs = chunked_get_logs(prior_start, prior_end, topics)
            if logs:
                logs.sort(key=lambda l: (int(l["blockNumber"], 16), int(l["logIndex"], 16)))
                first = logs[0]
                earlier_exists = True
                earlier_block = int(first["blockNumber"], 16)
                earlier_tx = first["transactionHash"]
                earlier_ts = block_timestamp(earlier_block)
                break
            if prior_start == 0:
                break
            prior_end = prior_start - 1

    same_date_tx = same_date_logs[0]["transactionHash"] if same_date_logs else ""
    same_date_block = int(same_date_logs[0]["blockNumber"], 16) if same_date_logs else None
    same_date_ts = block_timestamp(same_date_block) if same_date_block else None

    same_date_iso = (
        datetime.fromtimestamp(same_date_ts, tz=timezone.utc).isoformat() if same_date_ts else ""
    )
    earlier_iso = (
        datetime.fromtimestamp(earlier_ts, tz=timezone.utc).isoformat() if earlier_ts else ""
    )
    earlier_date = (
        datetime.fromtimestamp(earlier_ts, tz=timezone.utc).date().isoformat() if earlier_ts else ""
    )

    is_match = bool(same_date_logs) and not earlier_exists

    return {
        "first_login_date_utc": fl_date.isoformat(),
        "claim_on_same_date": "TRUE" if same_date_logs else "FALSE",
        "same_date_claim_count": len(same_date_logs),
        "same_date_first_claim_ts_utc": same_date_iso,
        "same_date_first_claim_tx": same_date_tx,
        "earlier_claim_exists": "TRUE" if earlier_exists else "FALSE",
        "earlier_first_claim_date_utc": earlier_date,
        "earlier_first_claim_ts_utc": earlier_iso,
        "earlier_first_claim_tx": earlier_tx or "",
        "match": "TRUE" if is_match else "FALSE",
        "celoscan_url": (f"https://celoscan.io/tx/{same_date_tx}" if same_date_tx else ""),
    }


# ----------------------------- Main -----------------------------

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="d_from", default="2026-04-23")
    p.add_argument("--to", dest="d_to", default="2026-05-01")
    p.add_argument("--out", default="audit_first_login_vs_first_claim.csv")
    args = p.parse_args()

    start_dt = datetime.strptime(args.d_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(args.d_to, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )

    print(f"[info] window:        {start_dt.isoformat()} -> {end_dt.isoformat()}", flush=True)
    print(f"[info] RPC:           {CELO_RPC} (chain_id={CHAIN_ID})", flush=True)
    print(f"[info] UBI_PROXY:     {UBI_PROXY}", flush=True)
    print(f"[info] GD_TOKEN:      {GOODDOLLAR_TOKEN}", flush=True)

    sb = supabase_client()
    rows = fetch_users(sb, start_dt.isoformat(), end_dt.isoformat())
    print(f"[info] user_data rows in window: {len(rows)}", flush=True)
    if not rows:
        print("[done] no users in window")
        return

    # Dedup wallets keeping earliest first_login
    by_wallet: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        w = (r.get("wallet_address") or "").lower().strip()
        if not w:
            continue
        if w not in by_wallet:
            by_wallet[w] = r
    wallets = sorted(by_wallet.keys())
    print(f"[info] unique wallets: {len(wallets)}", flush=True)

    latest_no = latest_block()
    latest_ts = block_timestamp(latest_no)
    print(
        f"[rpc] latest block={latest_no:,} ts={datetime.fromtimestamp(latest_ts, tz=timezone.utc).isoformat()}",
        flush=True,
    )

    out_rows: List[Dict[str, Any]] = []
    matches: List[Dict[str, Any]] = []
    t0 = time.time()
    for i, wallet in enumerate(wallets, start=1):
        r = by_wallet[wallet]
        fl = parse_iso_to_dt(r.get("first_login"))
        username = r.get("username") or ""
        verified = bool(r.get("verified_after_goodmarket"))
        ver_ts = parse_iso_to_dt(r.get("verification_timestamp"))

        print(
            f"[{i}/{len(wallets)}] wallet={wallet} first_login={fl.isoformat() if fl else '?'} username={username}",
            flush=True,
        )

        try:
            audit = audit_wallet(
                wallet=wallet,
                first_login_dt=fl,  # type: ignore[arg-type]
                latest_no=latest_no,
                latest_ts=latest_ts,
            )
        except Exception as e:  # noqa: BLE001
            print(f"  [error] {e}", flush=True)
            audit = {
                "first_login_date_utc": fl.date().isoformat() if fl else "",
                "claim_on_same_date": "ERROR",
                "same_date_claim_count": 0,
                "same_date_first_claim_ts_utc": "",
                "same_date_first_claim_tx": "",
                "earlier_claim_exists": "ERROR",
                "earlier_first_claim_date_utc": "",
                "earlier_first_claim_ts_utc": "",
                "earlier_first_claim_tx": "",
                "match": "ERROR",
                "celoscan_url": "",
                "error": str(e),
            }

        row = {
            "user_data_id": r.get("id"),
            "username": username,
            "wallet_address": wallet,
            "first_login_utc": fl.isoformat() if fl else "",
            "verified_after_goodmarket": "TRUE" if verified else "FALSE",
            "verification_timestamp_utc": ver_ts.isoformat() if ver_ts else "",
            **audit,
        }
        out_rows.append(row)
        if audit.get("match") == "TRUE":
            matches.append(row)

        print(
            "  -> match={m}  same_date_claim={s} (tx={st})  earlier_claim={e} (date={ed})".format(
                m=audit["match"],
                s=audit["claim_on_same_date"],
                st=audit.get("same_date_first_claim_tx") or "-",
                e=audit["earlier_claim_exists"],
                ed=audit.get("earlier_first_claim_date_utc") or "-",
            ),
            flush=True,
        )

    headers = [
        "user_data_id", "username", "wallet_address",
        "first_login_utc", "first_login_date_utc",
        "verified_after_goodmarket", "verification_timestamp_utc",
        "claim_on_same_date", "same_date_claim_count",
        "same_date_first_claim_ts_utc", "same_date_first_claim_tx",
        "earlier_claim_exists", "earlier_first_claim_date_utc",
        "earlier_first_claim_ts_utc", "earlier_first_claim_tx",
        "match", "celoscan_url", "error",
    ]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        for row in out_rows:
            w.writerow(row)

    elapsed = time.time() - t0
    print("\n" + "=" * 78, flush=True)
    print(f"[done] wrote {len(out_rows)} rows -> {args.out}  ({elapsed:.1f}s)", flush=True)

    same = [r for r in out_rows if r.get("claim_on_same_date") == "TRUE"]
    earlier = [r for r in out_rows if r.get("earlier_claim_exists") == "TRUE"]
    no_claim = [r for r in out_rows if r.get("claim_on_same_date") == "FALSE"]
    err = [r for r in out_rows if r.get("match") == "ERROR"]
    print(f"[summary] window           : {args.d_from}  ..  {args.d_to}")
    print(f"[summary] total wallets    : {len(out_rows)}")
    print(f"[summary] same-date claim  : {len(same)}")
    print(f"[summary] earlier claim too: {len(earlier)}")
    print(f"[summary] NO claim on date : {len(no_claim)}")
    print(f"[summary] errors           : {len(err)}")
    print(f"[summary] FULL MATCH (first claim == first login date AND no earlier): {len(matches)}")
    print("=" * 78)
    if matches:
        print("\nMATCHED:")
        for m in matches:
            uname = f"  ({m['username']})" if m["username"] else ""
            print(
                f"  {m['wallet_address']}{uname}\n"
                f"    login : {m['first_login_utc']}\n"
                f"    claim : {m['same_date_first_claim_ts_utc']}\n"
                f"    tx    : {m['celoscan_url']}\n"
            )
    else:
        print("\nNo wallets had first_claim on the same UTC date as first_login (with no earlier claim).")


if __name__ == "__main__":
    main()
