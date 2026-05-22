#!/usr/bin/env python3
"""Admin utility to force referrals from pending_face_verification to completed.

Use this only for manual recovery when face verification already happened but
callback/reconciliation did not update the referral row.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from supabase_client import get_supabase_admin_client


PENDING_STATUS = "pending_face_verification"
COMPLETED_STATUS = "completed"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Force update referral status from pending_face_verification to completed "
            "so pending rewards can be processed by admin dashboard."
        )
    )
    parser.add_argument(
        "--referee-wallet",
        help="Only update one referral row by referee_wallet.",
    )
    parser.add_argument(
        "--referral-code",
        help="Only update rows for a specific referral_code.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Maximum rows to update when no wallet/code filter is provided (default: 200).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview matching rows without applying updates.",
    )
    return parser


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    args = _build_parser().parse_args()

    supabase = get_supabase_admin_client()
    if not supabase:
        _print({
            "success": False,
            "error": "Supabase admin client unavailable. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.",
        })
        return 1

    query = (
        supabase.table("referrals")
        .select("id,referral_code,referee_wallet,status,created_at")
        .eq("status", PENDING_STATUS)
        .order("created_at", desc=False)
    )

    if args.referee_wallet:
        query = query.eq("referee_wallet", args.referee_wallet)
    if args.referral_code:
        query = query.eq("referral_code", args.referral_code)
    if not args.referee_wallet and not args.referral_code:
        query = query.limit(args.limit)

    result = query.execute()
    rows = result.data or []

    if args.dry_run:
        _print({
            "success": True,
            "dry_run": True,
            "matches": len(rows),
            "rows": rows,
        })
        return 0

    if not rows:
        _print({"success": True, "updated": 0, "message": "No pending_face_verification rows matched."})
        return 0

    updated = []
    for row in rows:
        row_id = row["id"]
        resp = (
            supabase.table("referrals")
            .update({"status": COMPLETED_STATUS})
            .eq("id", row_id)
            .eq("status", PENDING_STATUS)
            .execute()
        )
        if resp.data:
            updated.append(row)

    _print(
        {
            "success": True,
            "updated": len(updated),
            "requested": len(rows),
            "status_from": PENDING_STATUS,
            "status_to": COMPLETED_STATUS,
            "updated_rows": updated,
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
