#!/usr/bin/env python3
"""Quick diagnostic for the user_data audit. Prints what env keys are visible
and various row counts so we can see WHY the window query returned 0 rows.

Usage:
    set -a && source .env.preview && set +a
    uv run python scripts/audit_diagnose.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

from supabase import create_client


def _env_status(name: str) -> str:
    v = os.getenv(name)
    if v is None:
        return f"{name}: <unset>"
    return f"{name}: <set, len={len(v)}>"


def main() -> int:
    print("--- env presence ---")
    for n in (
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_ANON_KEY",
        "SUPABASE_KEY",
        "CELOSCAN_API_KEY",
        "UBI_PROXY_CONTRACT",
    ):
        print(" ", _env_status(n))

    url = os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
    )
    if not url or not key:
        print("ERROR: missing supabase creds")
        return 2

    using = (
        "service_role"
        if os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        else ("supabase_key" if os.getenv("SUPABASE_KEY") else "anon")
    )
    print(f"  → using: {using}\n")

    sb = create_client(url, key)

    # Window we care about
    start = datetime(2026, 4, 23, tzinfo=timezone.utc)
    end_excl = datetime(2026, 5, 2, tzinfo=timezone.utc)  # may 1 inclusive
    print(f"--- window: {start.isoformat()}  →  {end_excl.isoformat()} (excl.) ---\n")

    def count(query_label, q):
        try:
            r = q.execute()
            n = r.count if r.count is not None else len(r.data or [])
            print(f"  {query_label}: {n}")
            return n, r.data
        except Exception as e:
            print(f"  {query_label}: ERROR {e}")
            return None, None

    # 1. total rows in user_data
    count(
        "user_data total rows                                    ",
        sb.table("user_data").select("wallet_address", count="exact").limit(1),
    )

    # 2. rows in window (no other filter)
    count(
        "user_data rows with first_login in [Apr23,May2)         ",
        sb.table("user_data")
          .select("wallet_address", count="exact")
          .gte("first_login", start.isoformat())
          .lt("first_login", end_excl.isoformat())
          .limit(1),
    )

    # 3. rows in window with verified_after_goodmarket = TRUE
    count(
        "user_data rows in window AND verified_after_goodmarket=T",
        sb.table("user_data")
          .select("wallet_address", count="exact")
          .gte("first_login", start.isoformat())
          .lt("first_login", end_excl.isoformat())
          .eq("verified_after_goodmarket", True)
          .limit(1),
    )

    # 4. rows in window with ubi_verified = TRUE (alt column)
    count(
        "user_data rows in window AND ubi_verified=T             ",
        sb.table("user_data")
          .select("wallet_address", count="exact")
          .gte("first_login", start.isoformat())
          .lt("first_login", end_excl.isoformat())
          .eq("ubi_verified", True)
          .limit(1),
    )

    # 5. total rows with verified_after_goodmarket=TRUE (any window)
    count(
        "user_data total verified_after_goodmarket=T (all-time)  ",
        sb.table("user_data")
          .select("wallet_address", count="exact")
          .eq("verified_after_goodmarket", True)
          .limit(1),
    )

    # 6. peek at MIN/MAX first_login overall (5 rows each end)
    print("\n--- earliest 5 first_login rows ---")
    try:
        r = (
            sb.table("user_data")
              .select("wallet_address, first_login, verified_after_goodmarket, ubi_verified")
              .order("first_login", desc=False)
              .limit(5)
              .execute()
        )
        for row in r.data or []:
            print(f"  {row['first_login']}  {row['wallet_address']}  "
                  f"vag={row.get('verified_after_goodmarket')}  ubi={row.get('ubi_verified')}")
    except Exception as e:
        print(f"  ERROR: {e}")

    print("\n--- latest 5 first_login rows ---")
    try:
        r = (
            sb.table("user_data")
              .select("wallet_address, first_login, verified_after_goodmarket, ubi_verified")
              .order("first_login", desc=True)
              .limit(5)
              .execute()
        )
        for row in r.data or []:
            print(f"  {row['first_login']}  {row['wallet_address']}  "
                  f"vag={row.get('verified_after_goodmarket')}  ubi={row.get('ubi_verified')}")
    except Exception as e:
        print(f"  ERROR: {e}")

    # 7. pull all rows with verified_after_goodmarket=TRUE (limit 50) regardless of window
    print("\n--- sample of verified_after_goodmarket=T rows (any date) ---")
    try:
        r = (
            sb.table("user_data")
              .select("wallet_address, first_login, verified_after_goodmarket, "
                      "ubi_verified, verification_timestamp")
              .eq("verified_after_goodmarket", True)
              .order("first_login", desc=False)
              .limit(50)
              .execute()
        )
        for row in r.data or []:
            print(f"  {row['first_login']}  {row['wallet_address']}  "
                  f"verif_ts={row.get('verification_timestamp')}")
    except Exception as e:
        print(f"  ERROR: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
