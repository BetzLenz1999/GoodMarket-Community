"""
Audit: For users in `user_data` whose first_login is between --from and --to (UTC),
use the Celoscan API (account.tokentx) to find each wallet's FIRST GoodDollar UBI
claim, and report whether that first claim happened on the SAME calendar date as
the user's first_login.

A "claim" = ERC-20 Transfer of G$ where:
  contract = GoodDollar token (0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A)
  from     = UBI Scheme proxy (0x43d72Ff17701B2DA814620735C39C620Ce0ea4A1)
  to       = the user's wallet

Read-only. Only writes a CSV report locally; nothing is modified in Supabase or onchain.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from supabase import create_client


UBI_PROXY = "0x43d72Ff17701B2DA814620735C39C620Ce0ea4A1".lower()
GOODDOLLAR_TOKEN = "0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A".lower()
CELOSCAN_API = "https://api.celoscan.io/api"


def env(name: str, *fallbacks: str) -> str:
    for n in (name, *fallbacks):
        v = os.getenv(n)
        if v:
            return v
    return ""


def get_supabase():
    url = env("SUPABASE_URL")
    key = env(
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_SERVICE_KEY",
        "SUPABASE_KEY",
        "SUPABASE_ANON_KEY",
    )
    if not url or not key:
        sys.exit("ERROR: SUPABASE_URL and a Supabase key must be set.")
    using = (
        "service_role"
        if (env("SUPABASE_SERVICE_ROLE_KEY") or env("SUPABASE_SERVICE_KEY"))
        else "anon"
    )
    print(f"[supabase] using {using} key", flush=True)
    return create_client(url, key)


def parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            return None


def date_str(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d") if dt else ""


def fetch_first_ubi_claim(wallet: str, api_key: str = "") -> Optional[dict]:
    """Return the wallet's first incoming G$ Transfer where from == UBI proxy, or None."""
    params = {
        "module": "account",
        "action": "tokentx",
        "contractaddress": GOODDOLLAR_TOKEN,
        "address": wallet,
        "page": 1,
        "offset": 1000,
        "startblock": 0,
        "endblock": 99999999,
        "sort": "asc",
    }
    if api_key:
        params["apikey"] = api_key

    backoff = 5.0
    for _ in range(6):
        try:
            r = requests.get(CELOSCAN_API, params=params, timeout=30)
            data = r.json()
        except Exception as e:
            print(f"  ! request error ({e}); sleeping {backoff:.0f}s", flush=True)
            time.sleep(backoff)
            backoff *= 1.5
            continue

        status = str(data.get("status", "0"))
        message = data.get("message", "")
        result = data.get("result")

        if status == "1" and isinstance(result, list):
            for tx in result:
                if (tx.get("from") or "").lower() == UBI_PROXY:
                    return tx
            return None

        if status == "0" and message == "No transactions found":
            return None

        # Rate limit / NOTOK
        result_str = str(result) if not isinstance(result, list) else ""
        if (
            "rate limit" in result_str.lower()
            or "max rate" in result_str.lower()
            or message == "NOTOK"
        ):
            print(f"  ! rate limited; sleeping {backoff:.0f}s", flush=True)
            time.sleep(backoff)
            backoff *= 1.5
            continue

        print(
            f"  ! unexpected response status={status} message={message} result={result_str[:120]}",
            flush=True,
        )
        time.sleep(backoff)
        backoff *= 1.5

    return None


def fetch_user_rows(sb, start_iso: str, end_iso: str) -> list[dict]:
    rows: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            sb.table("user_data")
            .select(
                "id,wallet_address,first_login,verified_after_goodmarket,verification_timestamp,username"
            )
            .gte("first_login", start_iso)
            .lte("first_login", end_iso)
            .not_.is_("wallet_address", None)
            .order("first_login", desc=False)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", required=True, help="UTC start date YYYY-MM-DD (inclusive)")
    ap.add_argument("--to", dest="date_to", required=True, help="UTC end date YYYY-MM-DD (inclusive)")
    ap.add_argument("--out", dest="out_csv", default="audit_first_login_vs_first_claim.csv")
    ap.add_argument(
        "--sleep",
        type=float,
        default=5.2,
        help="Seconds between Celoscan calls. Free tier (no API key) is ~1 req / 5s.",
    )
    args = ap.parse_args()

    start_iso = f"{args.date_from}T00:00:00+00:00"
    end_iso = f"{args.date_to}T23:59:59+00:00"
    api_key = env("CELOSCAN_API_KEY", "ETHERSCAN_API_KEY")
    if api_key:
        print("[celoscan] using API key", flush=True)
        if args.sleep > 0.25:
            args.sleep = 0.25
    else:
        print("[celoscan] no API key; using public rate limits (~1 req / 5s)", flush=True)

    sb = get_supabase()

    print(
        f"[supabase] fetching user_data with first_login in [{start_iso} .. {end_iso}]",
        flush=True,
    )
    rows = fetch_user_rows(sb, start_iso, end_iso)
    print(f"[supabase] {len(rows)} candidate users", flush=True)
    if not rows:
        print("No candidate users in window; exiting.")
        return 0

    out_path = os.path.abspath(args.out_csv)
    fieldnames = [
        "username",
        "wallet_address",
        "first_login_utc",
        "first_login_date",
        "verified_after_goodmarket",
        "verification_timestamp_utc",
        "first_claim_tx",
        "first_claim_block",
        "first_claim_utc",
        "first_claim_date",
        "first_claim_amount_g$",
        "same_date_match",
        "match_status",
        "celoscan_url",
    ]

    matches = 0
    has_claim_count = 0
    no_claim_count = 0
    out_rows: list[dict] = []

    for i, r in enumerate(rows, start=1):
        wallet_raw = (r.get("wallet_address") or "").strip()
        wallet = wallet_raw.lower()
        username = r.get("username") or ""
        fl = parse_iso(r.get("first_login"))
        v_at = parse_iso(r.get("verification_timestamp"))

        if not wallet.startswith("0x") or len(wallet) != 42:
            print(f"[{i:>3}/{len(rows)}] {wallet_raw} - SKIP (invalid wallet)", flush=True)
            continue

        print(
            f"[{i:>3}/{len(rows)}] {wallet} ({username or '-'}) first_login={date_str(fl)}",
            flush=True,
        )

        tx = fetch_first_ubi_claim(wallet, api_key)
        time.sleep(args.sleep)

        first_claim_dt: Optional[datetime] = None
        first_claim_tx_hash = ""
        first_claim_block = ""
        first_claim_amount = ""

        if tx:
            try:
                ts = int(tx.get("timeStamp", 0))
                first_claim_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                first_claim_dt = None
            first_claim_tx_hash = tx.get("hash", "")
            first_claim_block = str(tx.get("blockNumber", ""))
            try:
                decimals = int(tx.get("tokenDecimal", 18))
                value = int(tx.get("value", 0))
                first_claim_amount = f"{value / (10 ** decimals):.8f}"
            except Exception:
                first_claim_amount = tx.get("value", "")

        if first_claim_dt:
            has_claim_count += 1
        else:
            no_claim_count += 1

        same_date = bool(
            fl and first_claim_dt and date_str(fl) == date_str(first_claim_dt)
        )
        if same_date:
            matches += 1
            status = "MATCH"
        elif first_claim_dt and fl:
            status = f"DIFF (login={date_str(fl)} claim={date_str(first_claim_dt)})"
        elif fl and not first_claim_dt:
            status = "NO_CLAIM_FOUND"
        else:
            status = "MISSING_LOGIN"

        celoscan_url = f"https://celoscan.io/tx/{first_claim_tx_hash}" if first_claim_tx_hash else ""

        print(
            f"      first_claim={date_str(first_claim_dt) or '-'} "
            f"amount={first_claim_amount or '-'} -> {status}",
            flush=True,
        )

        out_rows.append(
            {
                "username": username,
                "wallet_address": wallet,
                "first_login_utc": fl.isoformat() if fl else "",
                "first_login_date": date_str(fl),
                "verified_after_goodmarket": r.get("verified_after_goodmarket"),
                "verification_timestamp_utc": v_at.isoformat() if v_at else "",
                "first_claim_tx": first_claim_tx_hash,
                "first_claim_block": first_claim_block,
                "first_claim_utc": first_claim_dt.isoformat() if first_claim_dt else "",
                "first_claim_date": date_str(first_claim_dt),
                "first_claim_amount_g$": first_claim_amount,
                "same_date_match": "YES" if same_date else "NO",
                "match_status": status,
                "celoscan_url": celoscan_url,
            }
        )

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    print("\n=== SUMMARY ===", flush=True)
    print(f"window:                 {args.date_from} .. {args.date_to}  (UTC)", flush=True)
    print(f"candidate users:        {len(rows)}", flush=True)
    print(f"with first claim found: {has_claim_count}", flush=True)
    print(f"no UBI claim ever:      {no_claim_count}", flush=True)
    print(f"same-date matches:      {matches}", flush=True)
    print(f"CSV:                    {out_path}", flush=True)

    if matches:
        print("\n=== MATCHES (first_login date == first UBI claim date) ===", flush=True)
        print(f"{'username':<22} {'wallet':<44} {'date':<12} tx", flush=True)
        for row in out_rows:
            if row["same_date_match"] == "YES":
                print(
                    f"{(row['username'] or '-'):<22} "
                    f"{row['wallet_address']:<44} "
                    f"{row['first_login_date']:<12} "
                    f"{row['celoscan_url']}",
                    flush=True,
                )

    return 0


if __name__ == "__main__":
    sys.exit(main())
