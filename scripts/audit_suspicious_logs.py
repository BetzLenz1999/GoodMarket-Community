#!/usr/bin/env python3
"""
Audit production access logs for suspicious requests.

This script ingests an access log (gunicorn / nginx combined format, or any
log line that contains the request line and an HTTP status) and reports:

  - **CRITICAL**: any matching path with HTTP 200 status. This means
    something that *should* never have existed was actually served — a real
    incident worth investigating immediately.
  - **INFO**: counts of probes per path (all 404/403 hits). Useful for
    deciding what to add to the scanner-blocklist.

Usage:
    # Read from stdin (e.g. piped from `journalctl -u goodmarket | ...`)
    cat access.log | python scripts/audit_suspicious_logs.py

    # Read from one or more files
    python scripts/audit_suspicious_logs.py /var/log/goodmarket/*.log

    # Custom extra patterns
    python scripts/audit_suspicious_logs.py --pattern '/internal/' access.log

Exit codes:
    0 — no critical (200) hits found
    1 — at least one critical (200) hit was found
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

# Default suspicious path patterns. These mirror the in-app blocklist in
# main.py but include a few extra patterns that we want to monitor without
# necessarily blocking (e.g. anything matching "secret" or "password").
DEFAULT_PATTERNS = [
    r"\.env(\..*)?(\?|$|\s)",
    r"/\.git(/|\s|$)",
    r"/\.aws(/|\s|$)",
    r"/\.ssh(/|\s|$)",
    r"/\.circleci(/|\s|$)",
    r"/\.github(/|\s|$)",
    r"/\.vscode(/|\s|$)",
    r"/\.idea(/|\s|$)",
    r"/\.docker(/|\s|$)",
    r"/\.npmrc(\s|$)",
    r"/\.htaccess(\s|$)",
    r"/\.htpasswd(\s|$)",
    r"/\.DS_Store(\s|$)",
    r"/config/(secrets|aws|credentials|prod|dev|production)(/|\s|$)",
    r"/secrets?(/|\s|$)",
    r"/credentials?(/|\s|$)",
    r"/aws[_-]?credentials",
    r"/backup(\.|/|\s|$)",
    r"/dump(\.|/|\s|$)",
    r"/wp-(admin|login|content|includes)(/|\s|$)",
    r"/phpmyadmin(/|\s|$)",
    r"/phpinfo(\.php)?(\s|$)",
    r"/server-(status|info)(\s|$)",
    r"/(actuator|jmx-console|manager)(/|\s|$)",
    r"\.(sql|bak|swp|old|orig|save|tar|tgz|zip|rar|7z)(\s|$|\?)",
    # Soft-monitor: anything with "secret", "password", "token", "apikey"
    # in the path, even if not in the blocklist.
    r"/[^\s]*(secret|password|token|apikey|api_key)[^\s]*",
]

# Combined log format (and gunicorn default) puts the request line in quotes:
#   "GET /path HTTP/1.1" 200
# We extract method, path, status from that.
REQ_RE = re.compile(
    r'"(?P<method>[A-Z]+)\s+(?P<path>[^"\s]+)\s+HTTP/[\d.]+"\s+(?P<status>\d{3})'
)


def iter_lines(paths: list[str]) -> Iterable[str]:
    if not paths:
        yield from sys.stdin
        return
    for p in paths:
        path = Path(p)
        if not path.exists():
            print(f"warning: file not found: {p}", file=sys.stderr)
            continue
        with path.open("r", encoding="utf-8", errors="replace") as f:
            yield from f


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files",
        nargs="*",
        help="Log files to scan. If omitted, reads from stdin.",
    )
    parser.add_argument(
        "--pattern",
        action="append",
        default=[],
        help="Extra regex pattern to flag (repeatable).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="How many top probed paths to show (default 20).",
    )
    args = parser.parse_args()

    patterns = [re.compile(p, re.IGNORECASE) for p in DEFAULT_PATTERNS + args.pattern]

    critical: list[tuple[str, str, str]] = []  # (method, path, status)
    probe_counts: Counter[str] = Counter()
    total_lines = 0
    matched_lines = 0

    for line in iter_lines(args.files):
        total_lines += 1
        m = REQ_RE.search(line)
        if not m:
            continue
        path = m.group("path")
        status = m.group("status")
        method = m.group("method")

        if not any(p.search(path) for p in patterns):
            continue

        matched_lines += 1
        probe_counts[path] += 1
        if status == "200":
            critical.append((method, path, status))

    print(f"Scanned {total_lines} log lines, {matched_lines} matched suspicious patterns.\n")

    if critical:
        print("=" * 72)
        print(f"CRITICAL: {len(critical)} suspicious request(s) returned HTTP 200")
        print("=" * 72)
        for method, path, status in critical:
            print(f"  [{status}] {method} {path}")
        print()
        print("Action required: investigate immediately. Confirm the file/route")
        print("does not actually serve secrets, and rotate any exposed credentials.")
        print()
    else:
        print("OK: no suspicious requests returned HTTP 200.\n")

    if probe_counts:
        print(f"Top {min(args.top, len(probe_counts))} probed paths (all statuses):")
        for path, count in probe_counts.most_common(args.top):
            print(f"  {count:>6}  {path}")
        print()

    return 1 if critical else 0


if __name__ == "__main__":
    sys.exit(main())
