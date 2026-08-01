#!/usr/bin/env python3
"""Retention sweep: delete episodes older than the retention window.

Dry run by default (prints what it would delete). Pass --apply to actually
delete. Schedule it (cron / systemd timer) to enforce the retention period the
Privacy Notice promises.

  # what would be deleted at a 30-day retention:
  MDPLUS_RETENTION_DAYS=30 python3 scripts/purge_expired.py

  # actually delete:
  MDPLUS_RETENTION_DAYS=30 python3 scripts/purge_expired.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from synthetic_harness import retention, store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=int(os.environ.get("MDPLUS_RETENTION_DAYS", "0") or "0"),
        help="Retention window in days (0 disables the sweep).",
    )
    parser.add_argument("--apply", action="store_true", help="Actually delete.")
    args = parser.parse_args()

    root = Path(
        os.environ.get(
            "MDPLUS_EPISODES_ROOT",
            Path(__file__).resolve().parents[1]
            / "outputs" / "synthetic_patient_simulations" / "episodes",
        )
    ).expanduser().resolve()

    if args.days <= 0:
        print("Retention disabled (set --days or MDPLUS_RETENTION_DAYS > 0).")
        return 0

    store.init()
    ids = retention.purge_expired(root, args.days, apply=args.apply)
    if not ids:
        print(f"Nothing older than {args.days} days under {root}.")
        return 0
    verb = "Deleted" if args.apply else "Would delete"
    print(f"{verb} {len(ids)} episode(s) older than {args.days} days:")
    for episode_id in ids:
        print(f"  {episode_id}")
    if not args.apply:
        print("\nRe-run with --apply to delete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
