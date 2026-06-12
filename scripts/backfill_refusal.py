#!/usr/bin/env -S uv run python
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Recompute the `refused` flag on every stored response using the current
detect_refusal logic. Run once after changing the refusal heuristic.

    uv run scripts/backfill_refusal.py            # apply
    uv run scripts/backfill_refusal.py --dry-run  # preview the delta only
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from run_panel import detect_refusal

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("PYTHIA_DB_PATH", ROOT / "db" / "panel.sqlite"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, refused, raw_text FROM responses"
    ).fetchall()

    flips_on, flips_off, updates = 0, 0, []
    for r in rows:
        new = detect_refusal(r["raw_text"])
        if new != r["refused"]:
            updates.append((new, r["id"]))
            if new == 1:
                flips_on += 1
            else:
                flips_off += 1

    print(f"scanned {len(rows)} responses")
    print(f"  refused 0 -> 1: {flips_on}")
    print(f"  refused 1 -> 0: {flips_off}")
    print(f"  total changes:  {len(updates)}")

    if args.dry_run:
        print("(dry-run — no writes)")
        return

    con.executemany("UPDATE responses SET refused=? WHERE id=?", updates)
    con.commit()
    print(f"applied {len(updates)} updates")


if __name__ == "__main__":
    main()
